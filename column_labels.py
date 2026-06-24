# -*- coding: utf-8 -*-
"""
컬럼명 한글 라벨 매핑
=====================
CSV 파일의 실제 컬럼명(영문, dataset/*.csv 헤더 및 DataFrame 컬럼명)은 그대로 두고,
GUI 화면(Treeview 헤딩, 입력 폼 라벨)에 표시할 때만 한글 라벨로 바꿔서 보여준다.

- CSV 저장/로드, config_generator.py 등 데이터 처리 로직은 전혀 영향받지 않는다.
- GUI에서만 COLUMN_LABELS.get(영문컬럼명, 영문컬럼명) 형태로 변환해서 보여준다.
- 매핑이 없는 컬럼은 영문 컬럼명을 그대로 표시한다.
"""

COLUMN_LABELS = {
    # devices.csv
    "device_name": "장비명",
    "device_type": "장비유형",
    "vendor": "제조사",
    "model": "모델",
    "mgmt_ip": "관리IP",
    "mgmt_subnet_mask": "관리서브넷마스크",
    "mgmt_vlan": "관리VLAN",
    "site": "사이트",
    "role": "역할",
    "description": "설명",

    # links.csv
    "link_id": "링크ID",
    "device_a": "장비A",
    "port_a": "포트A",
    "device_b": "장비B",
    "port_b": "포트B",
    "link_type": "링크유형",
    "speed": "속도",

    # vlans.csv
    "vlan_id": "VLAN ID",
    "vlan_name": "VLAN명",
    "purpose": "용도",

    # interfaces.csv
    "port_name": "포트명",
    "mode": "모드",
    "access_vlan": "액세스VLAN",
    "trunk_allowed_vlans": "트렁크허용VLAN",
    "native_vlan": "네이티브VLAN",
    "port_status": "포트상태",

    # l3_config.csv
    "config_type": "설정유형",
    "interface_name": "인터페이스명",
    "ip_address": "IP주소",
    "subnet_mask": "서브넷마스크",
    "gateway_redundancy_mode": "게이트웨이이중화방식",
    "hsrp_vrrp_vip": "HSRP/VRRP 가상IP",
    "priority": "우선순위",
    "routing_protocol": "라우팅프로토콜",
    "destination_network": "목적지네트워크",
    "next_hop": "다음홉",

    # fw_policy.csv
    "policy_id": "정책ID",
    "policy_name": "정책명",
    "src_intf": "출발인터페이스",
    "dst_intf": "도착인터페이스",
    "src_subnet": "출발서브넷",
    "dst_subnet": "도착서브넷",
    "service": "서비스",
    "action": "동작",
    "nat_enable": "NAT사용여부",
    "nat_type": "NAT유형",

    # ospf_config.csv
    "ospf_process_id": "OSPF 프로세스ID",
    "router_id": "라우터ID",
    "area_id": "에리어ID",
    "network_type": "네트워크유형",
    "cost": "코스트",
    "passive_interface": "패시브인터페이스",
}


def get_label(column_name: str) -> str:
    """영문 컬럼명에 대응하는 한글 라벨을 반환한다. 매핑이 없으면 원래 이름을 그대로 반환한다."""
    return COLUMN_LABELS.get(column_name, column_name)