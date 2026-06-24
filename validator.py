# -*- coding: utf-8 -*-
"""
입력값 검증 모듈
================
CSV 데이터의 품질을 검증한다. GUI에서 저장 전에 호출하거나,
TXT 생성 전에 일괄 검증할 때 사용한다.

반환값은 항상 list[str] 형태의 오류/경고 메시지 목록이다.
빈 리스트이면 검증 통과.
"""

import re
from typing import Optional
import pandas as pd


# -----------------------------
# 공통 유틸리티
# -----------------------------
_IPV4 = re.compile(
    r"^(25[0-5]|2[0-4]\d|[01]?\d\d?)\."
    r"(25[0-5]|2[0-4]\d|[01]?\d\d?)\."
    r"(25[0-5]|2[0-4]\d|[01]?\d\d?)\."
    r"(25[0-5]|2[0-4]\d|[01]?\d\d?)$"
)
_CIDR = re.compile(r"^[\d.]+/(\d{1,2})$")


def _is_valid_ip(value: str) -> bool:
    return bool(_IPV4.match(value.strip())) if value.strip() else True  # 빈 값은 허용


def _is_valid_cidr(value: str) -> bool:
    if not value.strip():
        return True
    m = _CIDR.match(value.strip())
    if not m:
        return False
    prefix = int(m.group(1))
    ip_part = value.strip().split("/")[0]
    return 0 <= prefix <= 32 and _is_valid_ip(ip_part)


def _is_valid_subnet_mask(value: str) -> bool:
    """255.255.255.0 같은 서브넷 마스크 형식 검증"""
    valid_masks = {
        "0.0.0.0", "128.0.0.0", "192.0.0.0", "224.0.0.0",
        "240.0.0.0", "248.0.0.0", "252.0.0.0", "254.0.0.0",
        "255.0.0.0", "255.128.0.0", "255.192.0.0", "255.224.0.0",
        "255.240.0.0", "255.248.0.0", "255.252.0.0", "255.254.0.0",
        "255.255.0.0", "255.255.128.0", "255.255.192.0", "255.255.224.0",
        "255.255.240.0", "255.255.248.0", "255.255.252.0", "255.255.254.0",
        "255.255.255.0", "255.255.255.128", "255.255.255.192",
        "255.255.255.224", "255.255.255.240", "255.255.255.248",
        "255.255.255.252", "255.255.255.254", "255.255.255.255",
    }
    return value.strip() in valid_masks if value.strip() else True


# -----------------------------
# 파일별 필수 컬럼 정의
# -----------------------------
REQUIRED_COLUMNS = {
    "devices":    ["device_name", "device_type", "vendor", "mgmt_ip"],
    "links":      ["link_id", "device_a", "port_a", "device_b", "port_b"],
    "vlans":      ["vlan_id", "vlan_name"],
    "interfaces": ["device_name", "port_name", "mode"],
    "l3_config":  ["device_name", "config_type"],
    "fw_policy":  ["policy_id", "device_name", "src_intf", "dst_intf", "action"],
    "ospf_config":["device_name", "ospf_process_id", "router_id", "interface_name", "area_id"],
}


# -----------------------------
# 개별 파일 검증 함수
# -----------------------------
def validate_devices(df: pd.DataFrame) -> list[str]:
    issues = []
    key = "devices.csv"

    # 필수 컬럼 빈 값
    for col in ["device_name", "device_type", "vendor", "mgmt_ip"]:
        if col not in df.columns:
            continue
        empty = df[df[col].str.strip() == ""]
        for idx in empty.index:
            issues.append(f"[{key}] 행 {idx+1}: '{col}' 필수 값이 비어 있습니다.")

    # device_name 중복
    if "device_name" in df.columns:
        dup = df[df.duplicated("device_name", keep=False)]["device_name"].unique()
        for d in dup:
            issues.append(f"[{key}] device_name 중복: '{d}'")

    # IP 포맷
    for col in ["mgmt_ip"]:
        if col not in df.columns:
            continue
        for idx, row in df.iterrows():
            if row[col].strip() and not _is_valid_ip(row[col]):
                issues.append(f"[{key}] 행 {idx+1}: '{col}' IP 형식 오류 → '{row[col]}'")

    # 서브넷 마스크
    if "mgmt_subnet_mask" in df.columns:
        for idx, row in df.iterrows():
            if row["mgmt_subnet_mask"].strip() and not _is_valid_subnet_mask(row["mgmt_subnet_mask"]):
                issues.append(f"[{key}] 행 {idx+1}: 'mgmt_subnet_mask' 형식 오류 → '{row['mgmt_subnet_mask']}'")

    return issues


def validate_vlans(df: pd.DataFrame) -> list[str]:
    issues = []
    key = "vlans.csv"

    # vlan_id 중복
    if "vlan_id" in df.columns:
        dup = df[df.duplicated("vlan_id", keep=False)]["vlan_id"].unique()
        for d in dup:
            issues.append(f"[{key}] VLAN ID 중복: '{d}'")

    # vlan_id 숫자 범위 (1~4094)
    if "vlan_id" in df.columns:
        for idx, row in df.iterrows():
            vid = row["vlan_id"].strip()
            if vid and (not vid.isdigit() or not (1 <= int(vid) <= 4094)):
                issues.append(f"[{key}] 행 {idx+1}: vlan_id 범위 오류(1~4094) → '{vid}'")

    # 필수 컬럼 빈 값
    for col in ["vlan_id", "vlan_name"]:
        if col not in df.columns:
            continue
        empty = df[df[col].str.strip() == ""]
        for idx in empty.index:
            issues.append(f"[{key}] 행 {idx+1}: '{col}' 필수 값이 비어 있습니다.")

    return issues


def validate_interfaces(df: pd.DataFrame, device_names: set, vlan_ids: set) -> list[str]:
    issues = []
    key = "interfaces.csv"

    for idx, row in df.iterrows():
        # device_name 키 일치
        if "device_name" in df.columns and row["device_name"].strip():
            if row["device_name"] not in device_names:
                issues.append(f"[{key}] 행 {idx+1}: device_name '{row['device_name']}' 이 devices.csv에 없습니다.")

        # mode 값 검증
        if "mode" in df.columns:
            mode = row["mode"].strip().lower()
            if mode not in ("access", "trunk", "routed", ""):
                issues.append(f"[{key}] 행 {idx+1}: mode 값 오류(access/trunk/routed) → '{row['mode']}'")

        # access VLAN 참조
        if "access_vlan" in df.columns and row.get("access_vlan", "").strip():
            if row["access_vlan"].strip() not in vlan_ids:
                issues.append(f"[{key}] 행 {idx+1}: access_vlan '{row['access_vlan']}' 이 vlans.csv에 없습니다.")

        # trunk allowed vlans 참조
        if "trunk_allowed_vlans" in df.columns and row.get("trunk_allowed_vlans", "").strip():
            for v in row["trunk_allowed_vlans"].split(","):
                v = v.strip()
                if v and v not in vlan_ids:
                    issues.append(f"[{key}] 행 {idx+1}: trunk_allowed_vlans 중 '{v}' 이 vlans.csv에 없습니다.")

    return issues


def validate_l3_config(df: pd.DataFrame, device_names: set) -> list[str]:
    issues = []
    key = "l3_config.csv"

    valid_config_types = {"SVI", "StaticRoute", "SelfIP", "RoutedInterface"}
    valid_redundancy_modes = {"hsrp", "glbp", "ecmp", "none", ""}

    for idx, row in df.iterrows():
        # device_name 키 일치
        if "device_name" in df.columns and row["device_name"].strip():
            if row["device_name"] not in device_names:
                issues.append(f"[{key}] 행 {idx+1}: device_name '{row['device_name']}' 이 devices.csv에 없습니다.")

        # config_type 값 검증
        if "config_type" in df.columns:
            ct = row["config_type"].strip()
            if ct and ct not in valid_config_types:
                issues.append(f"[{key}] 행 {idx+1}: config_type 오류(SVI/StaticRoute/SelfIP) → '{ct}'")

        # IP 포맷
        for col in ["ip_address", "hsrp_vrrp_vip", "next_hop"]:
            if col in df.columns and row.get(col, "").strip():
                if not _is_valid_ip(row[col]):
                    issues.append(f"[{key}] 행 {idx+1}: '{col}' IP 형식 오류 → '{row[col]}'")

        # 서브넷 마스크
        if "subnet_mask" in df.columns and row.get("subnet_mask", "").strip():
            if not _is_valid_subnet_mask(row["subnet_mask"]):
                issues.append(f"[{key}] 행 {idx+1}: subnet_mask 형식 오류 → '{row['subnet_mask']}'")

        # destination_network CIDR
        if "destination_network" in df.columns and row.get("destination_network", "").strip():
            if not _is_valid_cidr(row["destination_network"]):
                issues.append(f"[{key}] 행 {idx+1}: destination_network CIDR 형식 오류 → '{row['destination_network']}'")

        # gateway_redundancy_mode 값 검증
        if "gateway_redundancy_mode" in df.columns:
            mode = row.get("gateway_redundancy_mode", "").strip().lower()
            if mode not in valid_redundancy_modes:
                issues.append(f"[{key}] 행 {idx+1}: gateway_redundancy_mode 오류(hsrp/glbp/ecmp/none) → '{mode}'")

    return issues


def validate_fw_policy(df: pd.DataFrame, device_names: set) -> list[str]:
    issues = []
    key = "fw_policy.csv"

    # policy_id 중복
    if "policy_id" in df.columns:
        dup = df[df.duplicated("policy_id", keep=False)]["policy_id"].unique()
        for d in dup:
            issues.append(f"[{key}] policy_id 중복: '{d}'")

    for idx, row in df.iterrows():
        # device_name 키 일치
        if "device_name" in df.columns and row["device_name"].strip():
            if row["device_name"] not in device_names:
                issues.append(f"[{key}] 행 {idx+1}: device_name '{row['device_name']}' 이 devices.csv에 없습니다.")

        # action 값 검증
        if "action" in df.columns:
            action = row.get("action", "").strip().lower()
            if action and action not in ("accept", "deny"):
                issues.append(f"[{key}] 행 {idx+1}: action 값 오류(accept/deny) → '{action}'")

        # nat_enable 값 검증
        if "nat_enable" in df.columns:
            nat = row.get("nat_enable", "").strip().lower()
            if nat and nat not in ("enable", "disable", ""):
                issues.append(f"[{key}] 행 {idx+1}: nat_enable 값 오류(enable/disable) → '{nat}'")

        # CIDR 형식
        for col in ["src_subnet", "dst_subnet"]:
            if col in df.columns and row.get(col, "").strip():
                val = row[col].strip()
                if val not in ("0.0.0.0/0", "all", "any") and not _is_valid_cidr(val):
                    issues.append(f"[{key}] 행 {idx+1}: '{col}' CIDR 형식 오류 → '{val}'")

    return issues


def validate_ospf_config(df: pd.DataFrame, device_names: set) -> list[str]:
    issues = []
    key = "ospf_config.csv"

    valid_network_types = {"broadcast", "point-to-point", "point-to-multipoint", "non-broadcast", ""}

    for idx, row in df.iterrows():
        # device_name 키 일치
        if "device_name" in df.columns and row["device_name"].strip():
            if row["device_name"] not in device_names:
                issues.append(f"[{key}] 행 {idx+1}: device_name '{row['device_name']}' 이 devices.csv에 없습니다.")

        # router_id IP 형식
        if "router_id" in df.columns and row.get("router_id", "").strip():
            if not _is_valid_ip(row["router_id"]):
                issues.append(f"[{key}] 행 {idx+1}: router_id IP 형식 오류 → '{row['router_id']}'")

        # priority 숫자 범위 (0~255)
        if "priority" in df.columns and row.get("priority", "").strip():
            p = row["priority"].strip()
            if not p.isdigit() or not (0 <= int(p) <= 255):
                issues.append(f"[{key}] 행 {idx+1}: priority 범위 오류(0~255) → '{p}'")

        # cost 숫자 (1~65535)
        if "cost" in df.columns and row.get("cost", "").strip():
            c = row["cost"].strip()
            if not c.isdigit() or not (1 <= int(c) <= 65535):
                issues.append(f"[{key}] 행 {idx+1}: cost 범위 오류(1~65535) → '{c}'")

        # network_type 값 검증
        if "network_type" in df.columns:
            nt = row.get("network_type", "").strip().lower()
            if nt not in valid_network_types:
                issues.append(f"[{key}] 행 {idx+1}: network_type 오류 → '{nt}'")

        # passive_interface 값 검증
        if "passive_interface" in df.columns:
            pi = row.get("passive_interface", "").strip().lower()
            if pi and pi not in ("yes", "no"):
                issues.append(f"[{key}] 행 {idx+1}: passive_interface 값 오류(yes/no) → '{pi}'")

    return issues


# -----------------------------
# 전체 일괄 검증
# -----------------------------
def validate_all(dfs: dict) -> list[str]:
    """
    dfs: {"devices": df, "vlans": df, "interfaces": df,
          "l3_config": df, "fw_policy": df, "ospf_config": df} 형태
    반환: 모든 오류/경고 메시지 리스트 (빈 리스트 = 통과)
    """
    issues = []

    devices_df = dfs.get("devices", pd.DataFrame())
    vlans_df = dfs.get("vlans", pd.DataFrame())

    device_names = set(devices_df["device_name"].str.strip()) if "device_name" in devices_df.columns else set()
    vlan_ids = set(vlans_df["vlan_id"].str.strip()) if "vlan_id" in vlans_df.columns else set()

    if "devices" in dfs:
        issues.extend(validate_devices(dfs["devices"]))
    if "vlans" in dfs:
        issues.extend(validate_vlans(dfs["vlans"]))
    if "interfaces" in dfs:
        issues.extend(validate_interfaces(dfs["interfaces"], device_names, vlan_ids))
    if "l3_config" in dfs:
        issues.extend(validate_l3_config(dfs["l3_config"], device_names))
    if "fw_policy" in dfs:
        issues.extend(validate_fw_policy(dfs["fw_policy"], device_names))
    if "ospf_config" in dfs:
        issues.extend(validate_ospf_config(dfs["ospf_config"], device_names))

    return issues