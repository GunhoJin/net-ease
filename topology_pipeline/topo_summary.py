"""
GNS3 Topology Summary 패널 OCR 파싱.

GNS3 우측 Topology Summary 패널 텍스트 형식:
    Node                         Console
    DeviceName                   telnet localhost:XXXX
      port_a <=> port_b RemoteDevice
      ...
"""
import re
import cv2
import numpy as np


# ---- 패널 감지 ----

def detect_summary_panel(img):
    """
    이미지에서 Topology Summary 패널 영역을 찾아 반환.
    반환: (x1, y1, x2, y2) 또는 None
    """
    h, w = img.shape[:2]
    search_start = int(w * 0.4)
    right = img[:, search_start:]
    gray = cv2.cvtColor(right, cv2.COLOR_BGR2GRAY)

    col_std = np.std(gray, axis=0)
    std_diff = np.abs(np.diff(col_std.astype(float)))
    peaks = np.where(std_diff > 8)[0]

    if len(peaks) > 0:
        divider_x = search_start + int(peaks[0]) + 1
        if divider_x < int(w * 0.75):
            return (divider_x, 0, w, h)

    return (int(w * 0.55), 0, w, h)


# ---- OCR ----

def _preprocess_panel(panel: np.ndarray) -> np.ndarray:
    """
    OCR 전처리: 업스케일 + CLAHE + 언샤프마스킹.
    작은 텍스트(R1, R2 등 2자 장비명) 인식률 향상.
    """
    panel = cv2.resize(panel, None, fx=2.5, fy=2.5,
                       interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(panel, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    blur = cv2.GaussianBlur(gray, (0, 0), 3)
    gray = cv2.addWeighted(gray, 1.5, blur, -0.5, 0)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def ocr_summary_panel(img, reader, roi=None):
    """Topology Summary 패널에 OCR을 실행해 텍스트 라인 목록 반환."""
    if roi is None:
        roi = detect_summary_panel(img)
    if roi is None:
        return []

    x1, y1, x2, y2 = roi
    panel = img[y1:y2, x1:x2]
    panel = _preprocess_panel(panel)
    results = reader.readtext(panel, detail=0, paragraph=False,
                              width_ths=0.7, height_ths=0.7)
    return results


# ---- OCR 보정 ----

_TELNET_RE = re.compile(r'telnet\s+localhost[:\s](\d+)', re.I)


def _fix_ocr(text: str) -> str:
    """GNS3 Topology Summary에서 자주 발생하는 OCR 오류 보정."""
    # 1. [ 뒤에 숫자 → L  (OCR: L3-1 → [3-1)
    text = re.sub(r'\[(\d)', r'L\1', text)

    # 2. 라인이 > 또는 숫자/기호+> 로 시작 = port_a 소실된 연결 라인
    #    예: '> e0 L3-1', '77> e0 L3-2', 'I> el L3-1', '{7> el L3-2'
    text = re.sub(r'^\s*[{I\d\[\s]*>\s*', '<=> ', text)

    # 3. 라인 내부 arrow 변형 → <=>
    text = re.sub(r'(?<!\w)<\s*[=\-]?\s*>(?!\w)', '<=>', text)

    # 4. 포트명 숫자/알파벳 혼동
    # eu → e0, el → e1 (숫자 0→u, 1→l 오인식)
    text = re.sub(r'\beu\b', 'e0', text)
    text = re.sub(r'\bel\b', 'e1', text)
    # e0, e1 등에서 0→o
    text = re.sub(r'\b([ef]\d*)o\b', r'\g<1>0', text, flags=re.I)
    text = re.sub(r'(?<=[ef]\d)/o\b', r'/0', text, flags=re.I)
    # f0l1 → f0/1 (슬래시 → l)
    text = re.sub(r'\b([ef]\d+)l(\d)', r'\g<1>/\2', text, flags=re.I)

    # 5. 장비명 보정
    text = text.replace('L?-', 'L2-')
    text = text.replace('L2-?', 'L2-2')
    # 대문자 + i/l 단독 = 숫자 1 오인식  (Ri→R1, Sl→S1 등)
    text = re.sub(r'\b([A-Z])([il])\b', lambda m: m.group(1) + '1', text)

    return text


# ---- 라인 타입 판별 ----

_SKIP_RE = re.compile(
    r'^(topology|summary|node|console|servers|telnet|localhost|CK|RAM|CPU|Gunho)',
    re.I,
)
_PORT_ONLY_RE  = re.compile(r'^[ef]\d+(?:/\d+)?$', re.I)
_PORT_PREFIX_RE = re.compile(r'^([ef]\d+(?:/\d+)?)\b', re.I)
_DEVICE_NAME_RE = re.compile(r'^[A-Z][A-Za-z0-9\-]+$')


def _is_skip(line: str) -> bool:
    return bool(_SKIP_RE.match(line)) or not line


def _is_device_name(line: str) -> bool:
    parts = line.split()
    if not parts:
        return False
    first = parts[0]
    return bool(_DEVICE_NAME_RE.match(first)) and not _SKIP_RE.match(first)


def _try_parse_connection(line: str):
    """
    "port_a <=> port_b DeviceName" 형식 파싱.
    port_a 없어도 port_b/device_b 있으면 허용 (대칭 dedup에서 처리).
    성공 → (port_a, port_b, device_b)  /  실패 → None
    """
    if '<=>' not in line:
        return None
    left, right = line.split('<=>', 1)
    left_parts  = left.strip().split()
    right_parts = right.strip().split()
    port_a  = left_parts[-1] if left_parts else ''
    if len(right_parts) < 2:
        return None
    port_b   = right_parts[0]
    device_b = right_parts[1]
    if not _PORT_PREFIX_RE.match(port_b):
        return None
    # port_a가 있으면 포트 형식 검증, 없으면 빈 문자열로 허용
    if port_a and not _PORT_PREFIX_RE.match(port_a):
        port_a = ''
    return port_a, port_b, device_b


def _reconstruct_lines(raw: list) -> list:
    """
    OCR이 쪼갠 라인 복원:
      - "R" + "2" → "R2"  (장비명 분리)
      - "e15" + "e14 L3-2" → "e15 <=> e14 L3-2"
      - "e15 <=>" + "e15 L3-2" → "e15 <=> e15 L3-2"
    """
    out = []
    i = 0
    while i < len(raw):
        line = raw[i]

        # 알파벳 단독 + 다음이 숫자 단독 → 장비명 복원 (예: "R" + "2" → "R2")
        if (re.match(r'^[A-Z][A-Za-z\-]*$', line.strip())
                and i + 1 < len(raw)
                and re.match(r'^\d+$', raw[i + 1].strip())):
            out.append(line.strip() + raw[i + 1].strip())
            i += 2
            continue

        # 라인이 <=> 로 끝나면 다음 라인과 합치기
        if line.rstrip().endswith('<=>') and i + 1 < len(raw):
            out.append(line.rstrip() + ' ' + raw[i + 1].strip())
            i += 2
            continue

        # 포트명만 있는 라인 + 다음이 "port device" → 연결 복원
        if _PORT_ONLY_RE.match(line.strip()) and i + 1 < len(raw):
            nxt = raw[i + 1].strip()
            nxt_parts = nxt.split()
            if (len(nxt_parts) >= 2
                    and _PORT_PREFIX_RE.match(nxt_parts[0])
                    and _DEVICE_NAME_RE.match(nxt_parts[1])):
                out.append(line.strip() + ' <=> ' + nxt)
                i += 2
                continue

        out.append(line)
        i += 1
    return out


# ---- 메인 파서 ----

def parse_summary_text(lines: list) -> tuple:
    """
    OCR 텍스트 라인 목록을 파싱해 (devices, links) 반환.

    전략: telnet 라인을 섹션 앵커로 사용.
      - 각 'telnet localhost:XXXX' 바로 이전 라인 = 장비명
      - 다음 telnet 라인 전까지 = 해당 장비의 연결 라인
      - 장비명 소실 시 '_Unknown' 임시 이름 부여 후 대칭 dedup으로 복원

    반환:
      devices: list of {"device_name": str}
      links:   list of {"link_id", "device_a", "port_a", "device_b", "port_b"}
    """
    fixed = [_fix_ocr(l.strip()) for l in lines]
    fixed = _reconstruct_lines(fixed)

    # telnet 라인 인덱스 수집
    telnet_indices = [i for i, l in enumerate(fixed) if _TELNET_RE.search(l)]

    sections = []  # list of (device_name: str, conn_lines: list[str])
    for idx, ti in enumerate(telnet_indices):
        # 장비명: telnet 라인 이전 최대 4칸에서 탐색
        device_name = ''
        for k in range(ti - 1, max(ti - 5, -1), -1):
            cand = fixed[k].strip()
            if cand and not _is_skip(cand) and _is_device_name(cand):
                device_name = cand.split()[0]
                break

        # 연결 라인: 다음 telnet 인덱스까지
        next_ti = telnet_indices[idx + 1] if idx + 1 < len(telnet_indices) else len(fixed)
        conn_lines = []
        for k in range(ti + 1, next_ti):
            l = fixed[k].strip()
            if l and not _is_skip(l) and not _is_device_name(l):
                conn_lines.append(l)

        sections.append((device_name, conn_lines))

    # 섹션에서 장비/링크 추출
    devices_seen: dict = {}
    devices: list = []
    links: list = []
    link_id = 1
    unnamed_count = 0

    for device_name, conn_lines in sections:
        if not device_name:
            unnamed_count += 1
            device_name = f'_Unknown{unnamed_count}'

        if device_name not in devices_seen:
            devices_seen[device_name] = len(devices)
            devices.append({'device_name': device_name})

        for line in conn_lines:
            conn = _try_parse_connection(line)
            if not conn:
                continue
            port_a, port_b, device_b = conn
            if device_b not in devices_seen:
                devices_seen[device_b] = len(devices)
                devices.append({'device_name': device_b})
            links.append({
                'link_id':  f'L{link_id:03d}',
                'device_a': device_name,
                'port_a':   port_a,
                'device_b': device_b,
                'port_b':   port_b,
            })
            link_id += 1

    # port_a 누락 링크 보완: 반대 방향 링크에서 port 정보 채우기
    for lnk in links:
        if not lnk['port_a']:
            for other in links:
                if (other['device_a'] == lnk['device_b']
                        and other['device_b'] == lnk['device_a']
                        and other['port_a']
                        and other['port_b'] == lnk['port_b']):
                    lnk['port_a'] = other['port_a']
                    break

    # 중복 링크 제거 (양방향 대칭)
    seen_pairs: set = set()
    deduped: list = []
    for lnk in links:
        a_key = f"{lnk['device_a']}:{lnk['port_a']}" if lnk['port_a'] else lnk['device_a']
        b_key = f"{lnk['device_b']}:{lnk['port_b']}"
        pair = tuple(sorted([a_key, b_key]))
        if pair not in seen_pairs:
            seen_pairs.add(pair)
            deduped.append(lnk)

    # _Unknown 장비는 연결에 쓰인 경우만 유지, 아니면 제거
    used_devices = {lnk['device_a'] for lnk in deduped} | {lnk['device_b'] for lnk in deduped}
    devices = [d for d in devices
               if not d['device_name'].startswith('_Unknown')
               or d['device_name'] in used_devices]

    for i, lnk in enumerate(deduped, start=1):
        lnk['link_id'] = f'L{i:03d}'

    return devices, deduped
