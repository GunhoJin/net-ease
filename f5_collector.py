# -*- coding: utf-8 -*-
"""
F5 BIG-IP 정보 수집 스크립트
============================
SSH로 F5 BIG-IP에 접속해 tmsh/bash 명령을 실행하고, 결과를 파일로 저장한다.

- 로그인 쉘 자동 감지: root(bash) → `tmsh -q -c "<cmd>"`, admin(tmsh) → 명령 직접 실행
- 명령 파일에서 `bash:` 접두어를 붙이면 bash 명령으로 실행 (tmsh 쉘이면 `run util bash -c`)
- 여러 장비 병렬 수집 (ThreadPoolExecutor)
- 결과 저장:
    output/f5/<timestamp>/<host>/<NN>_<command>.txt   명령별 출력
    output/f5/<timestamp>/<host>/_all.txt              전체 출력 합본
    output/f5/<timestamp>/summary.csv                  장비별 요약 (버전/플랫폼/시리얼/HA 상태)

사용 예:
    # 단일 장비 (비밀번호는 프롬프트 입력)
    python f5_collector.py --host 10.0.0.10 -u admin

    # 장비 목록 CSV + 사용자 명령 파일, 동시 5대
    python f5_collector.py --inventory f5_devices.csv --commands f5_commands.txt -w 5

    # 비밀번호를 환경변수로 전달 (CSV password 컬럼이 비어있을 때 사용)
    F5_PASSWORD='...' python f5_collector.py --inventory f5_devices.csv

의존성: pip install paramiko
"""

import argparse
import csv
import getpass
import logging
import os
import re
import shlex
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

try:
    import paramiko
except ImportError:  # pragma: no cover
    sys.exit("paramiko 가 필요합니다: pip install paramiko")


log = logging.getLogger("f5_collector")

# -----------------------------
# 기본 수집 명령 (tmsh 기준)
# -----------------------------
DEFAULT_COMMANDS = [
    # 시스템
    "show sys version",
    "show sys hardware",
    "list sys global-settings hostname",
    "show sys license",
    "list sys provision",
    "list sys management-ip",
    "list sys management-route",
    "show sys cpu",
    "show sys memory",
    "list sys ntp",
    "list sys dns",
    "list sys syslog",
    "list sys snmp",
    # HA
    "show cm failover-status",
    "show cm sync-status",
    "list cm device-group",
    # 네트워크
    "show net interface",
    "list net trunk",
    "list net vlan",
    "list net self",
    "list net route",
    "list net route-domain",
    # LTM
    "list ltm virtual",
    "show ltm virtual",
    "list ltm pool",
    "show ltm pool members",
    "list ltm node",
    "list ltm snatpool",
    "list ltm profile client-ssl",
    # 인증서
    "list sys crypto cert",
]

MARKER = "__NETEASE_OK__"


# -----------------------------
# 데이터 구조
# -----------------------------
@dataclass
class Device:
    host: str
    username: str
    password: str
    port: int = 22
    name: str = ""

    @property
    def label(self) -> str:
        return self.name or self.host


@dataclass
class Result:
    device: Device
    ok: bool = False
    error: str = ""
    shell: str = ""
    outputs: dict = field(default_factory=dict)  # cmd -> output
    out_dir: Path | None = None


# -----------------------------
# 입력 처리
# -----------------------------
def load_commands(path: str | None) -> list[str]:
    """명령 파일 로드. 빈 줄/`#` 주석 무시."""
    if not path:
        return list(DEFAULT_COMMANDS)
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def load_inventory(path: str, default_user: str, default_pw: str, default_port: int) -> list[Device]:
    """CSV 컬럼: host(필수), port, username, password, name"""
    devices = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
            host = row.get("host", "")
            if not host or host.startswith("#"):
                continue
            devices.append(Device(
                host=host,
                port=int(row.get("port") or default_port),
                username=row.get("username") or default_user,
                password=row.get("password") or default_pw,
                name=row.get("name", ""),
            ))
    return devices


# -----------------------------
# SSH 실행
# -----------------------------
def _exec(client: paramiko.SSHClient, command: str, timeout: int) -> tuple[int, str]:
    """exec 채널로 명령 1개 실행 → (exit_status, stdout+stderr)"""
    _, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out + (("\n" + err) if err.strip() else "")


def detect_shell(client: paramiko.SSHClient, timeout: int) -> str:
    """로그인 쉘 판별: bash 면 echo 가 그대로 실행됨, tmsh 면 문법 오류."""
    _, out = _exec(client, f"echo {MARKER}", timeout)
    return "bash" if out.strip() == MARKER else "tmsh"


def build_command(cmd: str, shell: str) -> str:
    """쉘 종류에 맞춰 실제 전송할 명령 문자열 생성."""
    if cmd.lower().startswith("bash:"):
        bash_cmd = cmd[5:].strip()
        return bash_cmd if shell == "bash" else f"run util bash -c {shlex.quote(bash_cmd)}"
    return f"tmsh -q -c {shlex.quote(cmd)}" if shell == "bash" else cmd


def collect(dev: Device, commands: list[str], timeout: int) -> Result:
    res = Result(device=dev)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            dev.host, port=dev.port, username=dev.username, password=dev.password,
            timeout=timeout, banner_timeout=timeout, auth_timeout=timeout,
            look_for_keys=not dev.password, allow_agent=not dev.password,
        )
        res.shell = detect_shell(client, timeout)
        log.info("[%s] 접속 성공 (shell=%s)", dev.label, res.shell)

        for cmd in commands:
            try:
                rc, out = _exec(client, build_command(cmd, res.shell), timeout)
                if rc != 0:
                    out = f"{out}\n[exit status {rc}]"
            except Exception as e:  # 개별 명령 실패는 기록만 하고 계속
                out = f"[ERROR] {type(e).__name__}: {e}"
            res.outputs[cmd] = out.rstrip() + "\n"
            log.debug("[%s] done: %s", dev.label, cmd)
        res.ok = True
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"
        log.error("[%s] 실패: %s", dev.label, res.error)
    finally:
        client.close()
    return res


# -----------------------------
# 요약 파싱
# -----------------------------
def _search(pattern: str, text: str) -> str:
    m = re.search(pattern, text or "", re.MULTILINE)
    return m.group(1).strip() if m else ""


def summarize(res: Result) -> dict:
    o = res.outputs
    ver = o.get("show sys version", "")
    hw = o.get("show sys hardware", "")
    return {
        "name": res.device.name,
        "host": res.device.host,
        "status": "OK" if res.ok else "FAIL",
        "hostname": _search(r"hostname\s+(\S+)", o.get("list sys global-settings hostname", "")),
        "version": _search(r"^\s*Version\s+(\S+)", ver),
        "build": _search(r"^\s*Build\s+(\S+)", ver),
        "edition": _search(r"^\s*Edition\s+(.+)$", ver),
        "platform": (_search(r"^\s*Marketing Name\s+(.+)$", hw)
                     or _search(r"^Platform\s*\n\s*Name\s+(.+)$", hw)),
        "serial": _search(r"Chassis Serial\s+(\S+)", hw) or _search(r"^\s*Appliance Serial\s+(\S+)", hw),
        "failover": _search(r"^\s*Status\s+(\S+)", o.get("show cm failover-status", "")),
        "sync": _search(r"^\s*Status\s+(.+)$", o.get("show cm sync-status", "")),
        "shell": res.shell,
        "error": res.error,
    }


# -----------------------------
# 저장
# -----------------------------
def _safe(s: str, maxlen: int = 60) -> str:
    return re.sub(r"[^\w.-]+", "_", s).strip("_")[:maxlen]


def save_result(res: Result, base: Path) -> None:
    out_dir = base / _safe(res.device.label)
    out_dir.mkdir(parents=True, exist_ok=True)
    res.out_dir = out_dir

    header = (f"# host: {res.device.host}  name: {res.device.name}\n"
              f"# collected: {datetime.now():%Y-%m-%d %H:%M:%S}  shell: {res.shell}\n")
    if not res.ok:
        (out_dir / "_error.txt").write_text(header + res.error + "\n", encoding="utf-8")
        return

    combined = [header]
    for i, (cmd, out) in enumerate(res.outputs.items(), 1):
        (out_dir / f"{i:02d}_{_safe(cmd)}.txt").write_text(f"# {cmd}\n{out}", encoding="utf-8")
        combined.append(f"\n{'=' * 78}\n# {cmd}\n{'=' * 78}\n{out}")
    (out_dir / "_all.txt").write_text("".join(combined), encoding="utf-8")


def write_summary(rows: list[dict], path: Path) -> None:
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig: 엑셀 한글 호환
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


# -----------------------------
# main
# -----------------------------
def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="F5 BIG-IP SSH 정보 수집기")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--host", nargs="+", help="대상 IP/호스트 (여러 개 가능)")
    src.add_argument("--inventory", help="장비 목록 CSV (host,port,username,password,name)")
    p.add_argument("-u", "--username", default=os.environ.get("F5_USERNAME", "admin"))
    p.add_argument("-p", "--port", type=int, default=22)
    p.add_argument("-c", "--commands", help="명령 목록 파일 (한 줄에 1개, 'bash:' 접두어 지원)")
    p.add_argument("-o", "--output", default="output/f5", help="저장 루트 디렉터리 (기본: output/f5)")
    p.add_argument("-w", "--workers", type=int, default=5, help="동시 접속 장비 수 (기본 5)")
    p.add_argument("-t", "--timeout", type=int, default=30, help="접속/명령 타임아웃 초 (기본 30)")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-5s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("paramiko").setLevel(logging.WARNING)

    password = os.environ.get("F5_PASSWORD", "")
    commands = load_commands(args.commands)

    if args.inventory:
        devices = load_inventory(args.inventory, args.username, password, args.port)
        if any(not d.password for d in devices):
            password = password or getpass.getpass("F5 password (CSV 미기재 장비 공통): ")
            for d in devices:
                d.password = d.password or password
    else:
        password = password or getpass.getpass(f"{args.username} password: ")
        devices = [Device(host=h, username=args.username, password=password, port=args.port)
                   for h in args.host]

    if not devices:
        log.error("대상 장비가 없습니다.")
        return 1

    base = Path(args.output) / datetime.now().strftime("%Y%m%d_%H%M%S")
    base.mkdir(parents=True, exist_ok=True)
    log.info("장비 %d대, 명령 %d개 수집 시작 → %s", len(devices), len(commands), base)

    started = time.time()
    rows = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(collect, d, commands, args.timeout): d for d in devices}
        for fut in as_completed(futures):
            res = fut.result()
            save_result(res, base)
            rows.append(summarize(res))
            if res.ok:
                log.info("[%s] 저장 완료 → %s", res.device.label, res.out_dir)

    rows.sort(key=lambda r: (r["name"] or r["host"]))
    write_summary(rows, base / "summary.csv")

    fail = sum(r["status"] == "FAIL" for r in rows)
    log.info("완료: 성공 %d / 실패 %d (%.1fs) → %s",
             len(rows) - fail, fail, time.time() - started, base / "summary.csv")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
