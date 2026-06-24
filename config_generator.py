# -*- coding: utf-8 -*-
"""
컨피그 생성 모듈
=================
devices.csv에 등록된 장비 1개당 TXT 파일 1개를 생성한다.

지원 범위:
  - L2/L3 Switch (vendor=Cisco) -> Cisco IOS 스타일 명령어
      VLAN 생성, 인터페이스(access/trunk), SVI, 정적 라우트, OSPF(다중 area), 게이트웨이 이중화(HSRP/GLBP/ECMP)
  - Firewall (vendor=Fortinet) -> FortiGate CLI 스타일 명령어
      인터페이스(VLAN 포함), 보안정책, NAT(outbound)

범위 밖(다음 단계로 미룸):
  - L4 LB(F5) : Pool/Virtual Server 구조라 별도 템플릿 필요
  - 기타 vendor : 매핑 안내만 출력

description 처리:
  - "{장비명} 업링크/다운링크/피어링크/연결" 패턴은 영문 코드(UPLINK_TO_xxx 등)로 변환
  - 매핑되지 않는 한글 텍스트는 장비에 올리지 않도록 생략

관리 IP 처리:
  - devices.csv의 mgmt_vlan/mgmt_ip/mgmt_subnet_mask를 관리 VLAN 인터페이스로 자동 보강
  - l3_config.csv에 같은 인터페이스가 이미 정의돼 있으면 그쪽이 우선

게이트웨이 이중화:
  - l3_config.csv의 gateway_redundancy_mode(hsrp/glbp/ecmp/none)에 따라 VLAN별로 다르게 생성

이 모듈은 GUI 버튼("TXT 컨피그 생성")에서 호출되며, 파일은 호출 시점에만
./output/configs/ 아래에 생성된다(자동 생성하지 않음).
"""

import os
import re
import pandas as pd


# -----------------------------
# description 영문 변환
# -----------------------------
_LINK_KEYWORD_MAP = [
    ("피어링크", "PEER_LINK_TO"),
    ("업링크", "UPLINK_TO"),
    ("다운링크", "DOWNLINK_TO"),
    ("연결", "LINK_TO"),
]

_DEVICE_PREFIX_PATTERN = re.compile(r"^([A-Za-z0-9\-]+)\s*(.*)$")


def translate_description(raw_description: str) -> str:
    """
    한글 description을 장비에 안전하게 들어갈 수 있는 영문 코드로 변환한다.
    - "{장비명} 업링크" / "다운링크" / "피어링크" / "연결" 패턴 -> "UPLINK_TO_장비명" 등으로 변환
    - 위 패턴에 해당하지 않는 한글 텍스트는 비워서 반환한다(장비에 한글이 올라가지 않도록).
    - 영문/숫자/공백/기본 기호만으로 이루어진 description은 그대로 둔다.
    """
    if not raw_description:
        return ""

    text = raw_description.strip()

    match = _DEVICE_PREFIX_PATTERN.match(text)
    if match:
        device_prefix, rest = match.group(1), match.group(2)
        for keyword, eng_prefix in _LINK_KEYWORD_MAP:
            if rest.startswith(keyword):
                device_token = device_prefix.upper().replace("-", "")
                return f"{eng_prefix}_{device_token}"

    if all(ord(ch) < 128 for ch in text):
        return text

    return ""


# -----------------------------
# 게이트웨이 이중화(HSRP/GLBP/ECMP) 명령어 생성
# -----------------------------
def generate_gateway_redundancy_lines(row) -> list:
    """
    SVI 행의 gateway_redundancy_mode 값에 따라 게이트웨이 이중화 명령어를 생성한다.
    - hsrp: standby 1 ip / priority / preempt
    - glbp: glbp 1 ip / priority / preempt / load-balancing (host-dependent 기본값)
    - ecmp: 별도 VIP 없이 OSPF 동일 코스트 멀티패스로 양쪽 코어를 동시에 사용 (A-A)
    - none/빈값: 아무것도 생성하지 않음
    """
    mode = (row.get("gateway_redundancy_mode") or "").strip().lower()
    vip = row.get("hsrp_vrrp_vip", "")
    priority = row.get("priority", "")

    lines = []
    if mode == "hsrp":
        if vip:
            lines.append(" standby 1 ip " + vip)
            if priority:
                lines.append(" standby 1 priority " + priority)
                lines.append(" standby 1 preempt")
    elif mode == "glbp":
        if vip:
            lines.append(" glbp 1 ip " + vip)
            if priority:
                lines.append(" glbp 1 priority " + priority)
                lines.append(" glbp 1 preempt")
            lines.append(" glbp 1 load-balancing host-dependent")
    elif mode == "ecmp":
        lines.append(" ! gateway_redundancy_mode=ecmp: A-A via OSPF equal-cost multipath (no VIP)")

    return lines


# -----------------------------
# Cisco IOS 스타일 생성
# -----------------------------
def generate_cisco_config(device_name: str, devices_df, vlans_df, interfaces_df, l3_df, ospf_df) -> str:
    lines = []
    lines.append("! " + "=" * 60)
    lines.append(f"! {device_name} - Auto-generated config (Cisco IOS style)")
    lines.append("! " + "=" * 60)
    lines.append("enable")
    lines.append("configure terminal")
    lines.append("!")

    # ---- VLAN 생성 ----
    dev_intf = interfaces_df[interfaces_df["device_name"] == device_name]
    referenced_vlans = set()
    for _, row in dev_intf.iterrows():
        if row["access_vlan"]:
            referenced_vlans.add(row["access_vlan"].strip())
        if row["trunk_allowed_vlans"]:
            for v in row["trunk_allowed_vlans"].split(","):
                v = v.strip()
                if v:
                    referenced_vlans.add(v)

    if referenced_vlans:
        lines.append("! --- VLAN Configuration ---")
        for vid in sorted(referenced_vlans, key=lambda x: int(x) if x.isdigit() else 0):
            vlan_row = vlans_df[vlans_df["vlan_id"] == vid]
            vlan_name = vlan_row.iloc[0]["vlan_name"] if not vlan_row.empty else f"VLAN{vid}"
            lines.append(f"vlan {vid}")
            lines.append(f" name {vlan_name}")
            lines.append("!")

    # ---- 인터페이스 설정 (access/trunk/routed) ----
    dev_ospf = ospf_df[ospf_df["device_name"] == device_name] if ospf_df is not None else pd.DataFrame()
    dev_l3 = l3_df[l3_df["device_name"] == device_name]
    routed_rows = dev_l3[dev_l3["config_type"] == "RoutedInterface"]

    if not dev_intf.empty:
        lines.append("! --- Interface Configuration ---")
        for _, row in dev_intf.iterrows():
            lines.append(f"interface {row['port_name']}")
            safe_description = translate_description(row.get("description", ""))
            if safe_description:
                lines.append(f" description {safe_description}")
            if row["mode"] == "trunk":
                lines.append(" switchport mode trunk")
                if row["trunk_allowed_vlans"]:
                    lines.append(f" switchport trunk allowed vlan {row['trunk_allowed_vlans']}")
                if row["native_vlan"]:
                    lines.append(f" switchport trunk native vlan {row['native_vlan']}")
            elif row["mode"] == "access":
                lines.append(" switchport mode access")
                if row["access_vlan"]:
                    lines.append(f" switchport access vlan {row['access_vlan']}")
            elif row["mode"] == "routed":
                lines.append(" no switchport")
                ip_match = routed_rows[routed_rows["interface_name"] == row["port_name"]]
                if not ip_match.empty:
                    r = ip_match.iloc[0]
                    if r["ip_address"] and r["subnet_mask"]:
                        lines.append(f" ip address {r['ip_address']} {r['subnet_mask']}")
            if row["port_status"] == "enabled":
                lines.append(" no shutdown")
            else:
                lines.append(" shutdown")
            lines.append("!")

    # ---- L3: SVI ----
    svi_rows = dev_l3[dev_l3["config_type"] == "SVI"]

    dev_row = devices_df[devices_df["device_name"] == device_name]
    mgmt_svi_row = None
    if not dev_row.empty:
        mgmt_vlan = dev_row.iloc[0].get("mgmt_vlan", "")
        mgmt_ip = dev_row.iloc[0].get("mgmt_ip", "")
        mgmt_mask = dev_row.iloc[0].get("mgmt_subnet_mask", "")
        if mgmt_vlan and mgmt_ip and mgmt_mask:
            mgmt_interface_name = f"Vlan{mgmt_vlan}"
            already_defined = (svi_rows["interface_name"] == mgmt_interface_name).any()
            if not already_defined:
                mgmt_svi_row = {
                    "interface_name": mgmt_interface_name,
                    "ip_address": mgmt_ip,
                    "subnet_mask": mgmt_mask,
                    "hsrp_vrrp_vip": "",
                    "priority": "",
                }

    if not svi_rows.empty or mgmt_svi_row is not None:
        lines.append("! --- L3 SVI Configuration ---")
        for _, row in svi_rows.iterrows():
            lines.append(f"interface {row['interface_name']}")
            if row["ip_address"] and row["subnet_mask"]:
                lines.append(f" ip address {row['ip_address']} {row['subnet_mask']}")
            # 게이트웨이 이중화 (gateway_redundancy_mode: hsrp/glbp/ecmp/none)
            lines.extend(generate_gateway_redundancy_lines(row))
            # OSPF 인터페이스 레벨 설정 (priority/cost/passive)
            ospf_match = dev_ospf[dev_ospf["interface_name"] == row["interface_name"]] if not dev_ospf.empty else pd.DataFrame()
            if not ospf_match.empty:
                ospf_row = ospf_match.iloc[0]
                if ospf_row["priority"]:
                    lines.append(f" ip ospf priority {ospf_row['priority']}")
                if ospf_row["cost"]:
                    lines.append(f" ip ospf cost {ospf_row['cost']}")
            lines.append(" no shutdown")
            lines.append("!")

        if mgmt_svi_row is not None:
            lines.append(f"interface {mgmt_svi_row['interface_name']}")
            lines.append(f" ip address {mgmt_svi_row['ip_address']} {mgmt_svi_row['subnet_mask']}")
            lines.append(" no shutdown")
            lines.append("!")

    # ---- L3: 정적 라우트 ----
    static_rows = dev_l3[dev_l3["config_type"] == "StaticRoute"]
    if not static_rows.empty:
        lines.append("! --- Static Route Configuration ---")
        for _, row in static_rows.iterrows():
            dest = row["destination_network"]
            next_hop = row["next_hop"]
            if dest and next_hop:
                if "/" in dest:
                    network, prefix = dest.split("/", 1)
                    prefix_to_mask = {
                        "0": "0.0.0.0", "8": "255.0.0.0", "16": "255.255.0.0",
                        "24": "255.255.255.0", "32": "255.255.255.255",
                    }
                    mask = prefix_to_mask.get(prefix, "255.255.255.0")
                    lines.append(f"ip route {network} {mask} {next_hop}")
                else:
                    lines.append(f"ip route {dest} 255.255.255.255 {next_hop}")
        lines.append("!")

    # ---- L3: OSPF ----
    if not dev_ospf.empty:
        process_id = dev_ospf.iloc[0]["ospf_process_id"]
        router_id = dev_ospf.iloc[0]["router_id"]

        lines.append("! --- OSPF Configuration ---")
        lines.append(f"router ospf {process_id}")
        if router_id:
            lines.append(f" router-id {router_id}")

        for _, ospf_row in dev_ospf.iterrows():
            svi_match = svi_rows[svi_rows["interface_name"] == ospf_row["interface_name"]]
            if svi_match.empty or not svi_match.iloc[0]["ip_address"]:
                continue
            ip_addr = svi_match.iloc[0]["ip_address"]
            mask_to_wildcard = {
                "255.255.255.0": "0.0.0.255",
                "255.255.0.0": "0.0.255.255",
                "255.0.0.0": "0.255.255.255",
                "255.255.255.255": "0.0.0.0",
            }
            wildcard = mask_to_wildcard.get(svi_match.iloc[0]["subnet_mask"], "0.0.0.255")
            lines.append(f" network {ip_addr} {wildcard} area {ospf_row['area_id']}")

        passive_rows = dev_ospf[dev_ospf["passive_interface"].str.lower() == "yes"]
        for _, prow in passive_rows.iterrows():
            lines.append(f" passive-interface {prow['interface_name']}")

        lines.append("!")

    lines.append("end")
    lines.append("write memory")
    return "\n".join(lines)


# -----------------------------
# FortiGate CLI 스타일 생성
# -----------------------------
SERVICE_NAME_MAP = {
    "ALL": "ALL",
    "HTTP": "HTTP",
    "HTTPS": "HTTPS",
    "HTTP_HTTPS": "HTTP,HTTPS",
    "MYSQL": "MYSQL",
    "SSH": "SSH",
    "DNS": "DNS",
}


def generate_fortigate_config(device_name: str, devices_df, vlans_df, interfaces_df, l3_df, fw_policy_df) -> str:
    lines = []
    lines.append("# " + "=" * 60)
    lines.append(f"# {device_name} - Auto-generated config (FortiGate CLI style)")
    lines.append("# " + "=" * 60)
    lines.append("")

    dev_intf = interfaces_df[interfaces_df["device_name"] == device_name]
    if not dev_intf.empty:
        lines.append("config system interface")
        for _, row in dev_intf.iterrows():
            lines.append(f'    edit "{row["port_name"]}"')
            safe_description = translate_description(row.get("description", ""))
            if safe_description:
                lines.append(f'        set alias "{safe_description[:25]}"')
            if row["access_vlan"]:
                lines.append(f'        set vlanid {row["access_vlan"]}')
            if row["port_status"] == "enabled":
                lines.append("        set status up")
            else:
                lines.append("        set status down")
            lines.append("    next")
        lines.append("end")
        lines.append("")

    dev_l3 = l3_df[l3_df["device_name"] == device_name]
    ip_rows = dev_l3[dev_l3["config_type"].isin(["SVI", "SelfIP"])]

    dev_row = devices_df[devices_df["device_name"] == device_name]
    mgmt_ip_row = None
    if not dev_row.empty:
        mgmt_vlan = dev_row.iloc[0].get("mgmt_vlan", "")
        mgmt_ip = dev_row.iloc[0].get("mgmt_ip", "")
        mgmt_mask = dev_row.iloc[0].get("mgmt_subnet_mask", "")
        if mgmt_vlan and mgmt_ip and mgmt_mask:
            mgmt_interface_name = f"Vlan{mgmt_vlan}"
            already_defined = (ip_rows["interface_name"] == mgmt_interface_name).any()
            if not already_defined:
                mgmt_ip_row = {
                    "interface_name": mgmt_interface_name,
                    "ip_address": mgmt_ip,
                    "subnet_mask": mgmt_mask,
                }

    if not ip_rows.empty or mgmt_ip_row is not None:
        lines.append("config system interface")
        for _, row in ip_rows.iterrows():
            if row["ip_address"] and row["subnet_mask"]:
                lines.append(f'    edit "{row["interface_name"]}"')
                lines.append(f'        set ip {row["ip_address"]} {row["subnet_mask"]}')
                lines.append("        set allowaccess ping")
                lines.append("    next")
        if mgmt_ip_row is not None:
            lines.append(f'    edit "{mgmt_ip_row["interface_name"]}"')
            lines.append(f'        set ip {mgmt_ip_row["ip_address"]} {mgmt_ip_row["subnet_mask"]}')
            lines.append("        set allowaccess ping https ssh")
            lines.append("    next")
        lines.append("end")
        lines.append("")

    static_rows = dev_l3[dev_l3["config_type"] == "StaticRoute"]
    if not static_rows.empty:
        lines.append("config router static")
        seq = 1
        for _, row in static_rows.iterrows():
            dest = row["destination_network"]
            next_hop = row["next_hop"]
            if dest and next_hop:
                if "/" in dest:
                    network, prefix = dest.split("/", 1)
                    prefix_to_mask = {
                        "0": "0.0.0.0", "8": "255.0.0.0", "16": "255.255.0.0",
                        "24": "255.255.255.0", "32": "255.255.255.255",
                    }
                    mask = prefix_to_mask.get(prefix, "255.255.255.0")
                else:
                    network, mask = dest, "255.255.255.255"
                lines.append(f"    edit {seq}")
                lines.append(f"        set dst {network} {mask}")
                lines.append(f"        set gateway {next_hop}")
                lines.append("    next")
                seq += 1
        lines.append("end")
        lines.append("")

    dev_policy = fw_policy_df[fw_policy_df["device_name"] == device_name]
    if not dev_policy.empty:
        subnets = set()
        for _, row in dev_policy.iterrows():
            if row["src_subnet"]:
                subnets.add(row["src_subnet"])
            if row["dst_subnet"]:
                subnets.add(row["dst_subnet"])

        def subnet_to_addr_name(subnet: str) -> str:
            if subnet in ("0.0.0.0/0", "all", "any"):
                return "all"
            return f"ADDR_{subnet.replace('/', '_').replace('.', '-')}"

        def subnet_to_netmask(subnet: str):
            ip_part, prefix_part = subnet.split("/", 1)
            prefix_to_mask = {
                "0": "0.0.0.0", "8": "255.0.0.0", "16": "255.255.0.0",
                "24": "255.255.255.0", "32": "255.255.255.255",
            }
            return ip_part, prefix_to_mask.get(prefix_part, "255.255.255.0")

        custom_subnets = [s for s in subnets if s not in ("0.0.0.0/0", "all", "any")]
        if custom_subnets:
            lines.append("config firewall address")
            for subnet in sorted(custom_subnets):
                ip_part, mask = subnet_to_netmask(subnet)
                addr_name = subnet_to_addr_name(subnet)
                lines.append(f'    edit "{addr_name}"')
                lines.append(f"        set subnet {ip_part} {mask}")
                lines.append("    next")
            lines.append("end")
            lines.append("")

        lines.append("config firewall policy")
        for _, row in dev_policy.iterrows():
            lines.append(f"    edit {row['policy_id']}")
            lines.append(f'        set name "{row["policy_name"]}"')
            lines.append(f'        set srcintf "{row["src_intf"]}"')
            lines.append(f'        set dstintf "{row["dst_intf"]}"')
            lines.append(f'        set srcaddr "{subnet_to_addr_name(row["src_subnet"])}"')
            lines.append(f'        set dstaddr "{subnet_to_addr_name(row["dst_subnet"])}"')

            service = SERVICE_NAME_MAP.get(row["service"], row["service"])
            lines.append(f'        set service "{service}"')
            lines.append(f"        set action {row['action']}")
            lines.append("        set schedule \"always\"")

            if row["action"] == "accept":
                lines.append("        set logtraffic all")

            if row["nat_enable"] == "enable":
                lines.append("        set nat enable")

            lines.append("    next")
        lines.append("end")
        lines.append("")

    if not lines or len(lines) <= 4:
        lines.append("# (No configuration generated for this device - check dataset CSV)")

    return "\n".join(lines)


# -----------------------------
# Cisco IOS 라우터 스타일 생성
# -----------------------------
def generate_cisco_router_config(device_name: str, devices_df, vlans_df, interfaces_df, l3_df, ospf_df) -> str:
    lines = []
    lines.append("! " + "=" * 60)
    lines.append(f"! {device_name} - Auto-generated config (Cisco IOS style)")
    lines.append("! " + "=" * 60)
    lines.append("enable")
    lines.append("configure terminal")
    lines.append("!")

    dev_l3 = l3_df[l3_df["device_name"] == device_name]
    routed_rows = dev_l3[dev_l3["config_type"] == "RoutedInterface"]
    dev_intf = interfaces_df[interfaces_df["device_name"] == device_name]
    dev_ospf = ospf_df[ospf_df["device_name"] == device_name] if ospf_df is not None else pd.DataFrame()

    # ---- 인터페이스 설정 ----
    if not dev_intf.empty:
        lines.append("! --- Interface Configuration ---")
        for _, row in dev_intf.iterrows():
            lines.append(f"interface {row['port_name']}")
            safe_description = translate_description(row.get("description", ""))
            if safe_description:
                lines.append(f" description {safe_description}")
            ip_match = routed_rows[routed_rows["interface_name"] == row["port_name"]]
            if not ip_match.empty:
                r = ip_match.iloc[0]
                if r["ip_address"] and r["subnet_mask"]:
                    lines.append(f" ip address {r['ip_address']} {r['subnet_mask']}")
            if row["port_status"] == "enabled":
                lines.append(" no shutdown")
            else:
                lines.append(" shutdown")
            lines.append("!")

    # ---- 정적 라우트 ----
    static_rows = dev_l3[dev_l3["config_type"] == "StaticRoute"]
    if not static_rows.empty:
        lines.append("! --- Static Route Configuration ---")
        for _, row in static_rows.iterrows():
            dest = row["destination_network"]
            next_hop = row["next_hop"]
            if dest and next_hop:
                if "/" in dest:
                    network, prefix = dest.split("/", 1)
                    prefix_to_mask = {
                        "0": "0.0.0.0", "8": "255.0.0.0", "16": "255.255.0.0",
                        "24": "255.255.255.0", "32": "255.255.255.255",
                    }
                    mask = prefix_to_mask.get(prefix, "255.255.255.0")
                    lines.append(f"ip route {network} {mask} {next_hop}")
                else:
                    lines.append(f"ip route {dest} 255.255.255.255 {next_hop}")
        lines.append("!")

    # ---- OSPF ----
    if not dev_ospf.empty:
        process_id = dev_ospf.iloc[0]["ospf_process_id"]
        router_id = dev_ospf.iloc[0]["router_id"]
        lines.append("! --- OSPF Configuration ---")
        lines.append(f"router ospf {process_id}")
        if router_id:
            lines.append(f" router-id {router_id}")
        mask_to_wildcard = {
            "255.255.255.252": "0.0.0.3",
            "255.255.255.0": "0.0.0.255",
            "255.255.0.0": "0.0.255.255",
            "255.0.0.0": "0.255.255.255",
            "255.255.255.255": "0.0.0.0",
        }
        for _, ospf_row in dev_ospf.iterrows():
            ip_match = routed_rows[routed_rows["interface_name"] == ospf_row["interface_name"]]
            if ip_match.empty or not ip_match.iloc[0]["ip_address"]:
                continue
            ip_addr = ip_match.iloc[0]["ip_address"]
            wildcard = mask_to_wildcard.get(ip_match.iloc[0]["subnet_mask"], "0.0.0.255")
            lines.append(f" network {ip_addr} {wildcard} area {ospf_row['area_id']}")
        passive_rows = dev_ospf[dev_ospf["passive_interface"].str.lower() == "yes"]
        for _, prow in passive_rows.iterrows():
            lines.append(f" passive-interface {prow['interface_name']}")
        lines.append("!")

    lines.append("end")
    lines.append("write memory")
    return "\n".join(lines)


# -----------------------------
# 장비 1개에 대한 컨피그 생성 (벤더별 분기)
# -----------------------------
def generate_device_config(device_name: str, devices_df, vlans_df, interfaces_df, l3_df, fw_policy_df, ospf_df) -> str:
    """
    device_name 하나에 대해 벤더/타입에 맞는 컨피그 텍스트를 생성해서 반환한다.
    지원하지 않는 벤더는 안내 메시지를 담은 텍스트를 반환한다(예외를 던지지 않음).
    """
    dev_row = devices_df[devices_df["device_name"] == device_name]
    if dev_row.empty:
        return f"! {device_name} not found in devices.csv."

    device_type = dev_row.iloc[0]["device_type"]
    vendor = dev_row.iloc[0]["vendor"]

    if vendor == "Cisco" and device_type in ("L2 Switch", "L3 Switch"):
        return generate_cisco_config(device_name, devices_df, vlans_df, interfaces_df, l3_df, ospf_df)

    if vendor == "Cisco" and device_type == "Router":
        return generate_cisco_router_config(device_name, devices_df, vlans_df, interfaces_df, l3_df, ospf_df)

    if vendor == "Fortinet" and device_type == "Firewall":
        return generate_fortigate_config(
            device_name, devices_df, vlans_df, interfaces_df, l3_df, fw_policy_df
        )

    return (
        f"# {device_name} ({vendor} / {device_type})\n"
        f"# Auto-generation is not yet supported for this device type.\n"
        f"# F5 L4 LB requires a separate Pool/Virtual Server template, planned for a later stage.\n"
    )


def generate_all_configs(devices_df, vlans_df, interfaces_df, l3_df, fw_policy_df, ospf_df, output_dir: str) -> list:
    """
    devices.csv의 모든 장비에 대해 TXT 파일을 생성한다.
    파일은 output_dir/configs/ 아래에 {device_name}.txt로 저장된다.
    반환값: 생성된 파일 경로 리스트
    """
    configs_dir = os.path.join(output_dir, "configs")
    os.makedirs(configs_dir, exist_ok=True)

    generated_paths = []
    for _, dev_row in devices_df.iterrows():
        device_name = dev_row["device_name"]
        config_text = generate_device_config(
            device_name, devices_df, vlans_df, interfaces_df, l3_df, fw_policy_df, ospf_df
        )
        file_path = os.path.join(configs_dir, f"{device_name}.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(config_text)
        generated_paths.append(file_path)

    return generated_paths