# -*- coding: utf-8 -*-
"""
자동 컨피그 채우기 모듈.

devices.csv (name만 있는 상태) + links.csv + 사용자 지정 VLAN/서브넷 →
  devices  : device_type, vendor, mgmt_ip, mgmt_subnet_mask, mgmt_vlan 채우기
  vlans    : VLAN 목록 생성
  interfaces : links 기반 trunk/access 자동 결정
  l3_config  : L3 장비 SVI + 기본 라우팅 생성
"""

import re
import ipaddress
import pandas as pd


# ──────────────────────────────────────────────
# 장비 타입 추론
# ──────────────────────────────────────────────

_FW_RE = re.compile(r'FW|FIREWALL|FORTI|FG[-_]?|ASA', re.I)
_LB_RE = re.compile(r'F5|\bLTM\b|\bLB\b', re.I)
_L3_RE = re.compile(r'L3|CORE|DIST|MLS', re.I)
_L2_RE = re.compile(r'L2|ACCESS|CISCO', re.I)
_RT_RE = re.compile(r'^R\d|^RTR|^ROUTER|^GW\d', re.I)


def infer_device_type(name: str) -> tuple:
    """장비명 → (device_type, vendor)."""
    if _FW_RE.search(name):
        vendor = 'Fortinet' if re.search(r'FORTI|FG[-_]?', name, re.I) else 'Cisco'
        return 'Firewall', vendor
    if _LB_RE.search(name):
        return 'F5 LTM', 'F5'
    if _L3_RE.search(name):
        return 'L3 Switch', 'Cisco'
    if _L2_RE.search(name):
        return 'L2 Switch', 'Cisco'
    if _RT_RE.match(name):
        return 'Router', 'Cisco'
    return 'L3 Switch', 'Cisco'


_TIER = {'Firewall': 0, 'Router': 0, 'L3 Switch': 1, 'L2 Switch': 2, 'F5 LTM': 2}

def _tier(dtype: str) -> int:
    return _TIER.get(dtype, 1)


# ──────────────────────────────────────────────
# 관리 IP 순차 할당
# ──────────────────────────────────────────────

def _assign_mgmt_ips(device_names: list, dtype_map: dict,
                     mgmt_subnet: str) -> dict:
    """device_name → (ip_str, netmask_str). 티어 오름차순 → 이름 오름차순."""
    net   = ipaddress.IPv4Network(mgmt_subnet, strict=False)
    hosts = list(net.hosts())
    mask  = str(net.netmask)

    ordered = sorted(
        device_names,
        key=lambda n: (_tier(dtype_map.get(n, 'L3 Switch')), n)
    )
    return {name: (str(hosts[i]), mask)
            for i, name in enumerate(ordered) if i < len(hosts)}


# ──────────────────────────────────────────────
# vlans.csv
# ──────────────────────────────────────────────

def _build_vlans_df(vlan_configs: list) -> pd.DataFrame:
    rows = []
    for vc in vlan_configs:
        rows.append({
            'vlan_id':     str(vc['vlan_id']),
            'vlan_name':   vc['vlan_name'],
            'purpose':     'management' if vc.get('is_mgmt') else 'data',
            'site':        '',
            'description': f"auto: {vc.get('subnet', '')}",
        })
    return pd.DataFrame(rows)


# ──────────────────────────────────────────────
# interfaces.csv
# ──────────────────────────────────────────────

def _build_interfaces_df(devices_df: pd.DataFrame,
                          links_df: pd.DataFrame,
                          vlan_configs: list) -> pd.DataFrame:
    dtype_map = {r['device_name']: r.get('device_type', 'L3 Switch')
                 for _, r in devices_df.iterrows() if r.get('device_name')}

    all_vlans = ','.join(str(v['vlan_id']) for v in vlan_configs)

    rows = []
    seen = set()

    def _add(dev, port, peer):
        if not dev or not port:
            return
        key = (dev, port)
        if key in seen:
            return
        seen.add(key)

        dev_t  = _tier(dtype_map.get(dev,  'L3 Switch'))
        peer_t = _tier(dtype_map.get(peer, 'L3 Switch'))

        # 항상 trunk (L2/L3 경계 불문) — 단방향 고려 없이 양쪽 trunk
        # 운영자가 access 변환이 필요한 포트만 수동 수정
        rows.append({
            'device_name':         dev,
            'port_name':           port,
            'mode':                'trunk',
            'access_vlan':         '',
            'trunk_allowed_vlans': all_vlans,
            'native_vlan':         '1',
            'port_status':         'up',
            'description':         f'to {peer}',
        })

    for _, lnk in links_df.iterrows():
        _add(lnk.get('device_a', ''), lnk.get('port_a', ''), lnk.get('device_b', ''))
        _add(lnk.get('device_b', ''), lnk.get('port_b', ''), lnk.get('device_a', ''))

    return pd.DataFrame(rows)


# ──────────────────────────────────────────────
# l3_config.csv
# ──────────────────────────────────────────────

def _build_l3_config_df(devices_df: pd.DataFrame,
                         vlan_configs: list,
                         ip_map: dict) -> pd.DataFrame:
    L3_TYPES = {'Router', 'L3 Switch', 'Firewall'}

    mgmt_vc   = next((v for v in vlan_configs if v.get('is_mgmt')), vlan_configs[0])
    data_vcs  = [v for v in vlan_configs if not v.get('is_mgmt')]

    # L3 장비 목록 (정렬 유지)
    l3_devs = [r['device_name'] for _, r in devices_df.iterrows()
               if r.get('device_type') in L3_TYPES and r.get('device_name')]

    rows = []

    for _, dev in devices_df.iterrows():
        name  = str(dev.get('device_name', '')).strip()
        dtype = str(dev.get('device_type', '')).strip()
        if dtype not in L3_TYPES or not name:
            continue

        mgmt_ip, mgmt_mask = ip_map.get(name, ('', ''))

        # ── 관리 SVI ──
        rows.append({
            'device_name':             name,
            'config_type':             'SVI',
            'vlan_id':                 str(mgmt_vc['vlan_id']),
            'interface_name':          f"Vlan{mgmt_vc['vlan_id']}",
            'ip_address':              mgmt_ip,
            'subnet_mask':             mgmt_mask,
            'gateway_redundancy_mode': '',
            'hsrp_vrrp_vip':           '',
            'priority':                '',
            'routing_protocol':        '',
            'destination_network':     '',
            'next_hop':                '',
            'description':             f'{mgmt_vc["vlan_name"]} SVI (auto)',
        })

        # ── 데이터 VLAN SVI ──
        idx = l3_devs.index(name) if name in l3_devs else 0
        for vc in data_vcs:
            try:
                net    = ipaddress.IPv4Network(vc['subnet'], strict=False)
                hosts  = list(net.hosts())
                svi_ip = str(hosts[idx]) if idx < len(hosts) else ''
                mask   = str(net.netmask)
            except Exception:
                svi_ip, mask = '', ''

            rows.append({
                'device_name':             name,
                'config_type':             'SVI',
                'vlan_id':                 str(vc['vlan_id']),
                'interface_name':          f"Vlan{vc['vlan_id']}",
                'ip_address':              svi_ip,
                'subnet_mask':             mask,
                'gateway_redundancy_mode': '',
                'hsrp_vrrp_vip':           '',
                'priority':                '',
                'routing_protocol':        '',
                'destination_network':     '',
                'next_hop':                '',
                'description':             f'{vc["vlan_name"]} SVI (auto)',
            })

        # ── 기본 정적 라우트 (Router / L3 Switch) ──
        if dtype in ('Router', 'L3 Switch'):
            rows.append({
                'device_name':             name,
                'config_type':             'static_route',
                'vlan_id':                 '',
                'interface_name':          '',
                'ip_address':              '',
                'subnet_mask':             '',
                'gateway_redundancy_mode': '',
                'hsrp_vrrp_vip':           '',
                'priority':                '',
                'routing_protocol':        'static',
                'destination_network':     '0.0.0.0/0',
                'next_hop':                '',
                'description':             'Default route (next_hop 직접 입력)',
            })

    return pd.DataFrame(rows)


# ──────────────────────────────────────────────
# 메인 진입점
# ──────────────────────────────────────────────

def auto_fill(devices_df: pd.DataFrame,
              links_df: pd.DataFrame,
              vlan_configs: list) -> dict:
    """
    vlan_configs 예시:
      [
        {'vlan_id': 100, 'vlan_name': 'Management', 'subnet': '192.168.100.0/24', 'is_mgmt': True},
        {'vlan_id': 200, 'vlan_name': 'Data',       'subnet': '10.0.0.0/24',      'is_mgmt': False},
      ]

    반환:
      {'devices': df, 'vlans': df, 'interfaces': df, 'l3_config': df}
    """
    mgmt_vc = next((v for v in vlan_configs if v.get('is_mgmt')), vlan_configs[0])

    # 1. 장비 타입 추론
    dtype_map = {}
    for _, row in devices_df.iterrows():
        name = str(row.get('device_name', '')).strip()
        if name:
            dtype_map[name] = infer_device_type(name)

    # 2. 관리 IP 할당
    device_names = [str(r['device_name']).strip()
                    for _, r in devices_df.iterrows()
                    if str(r.get('device_name', '')).strip()]
    ip_map = _assign_mgmt_ips(
        device_names,
        {n: dtype_map[n][0] for n in dtype_map},
        mgmt_vc['subnet'],
    )

    # 3. devices_df 업데이트 (기존 값이 비어있을 때만)
    new_dev = devices_df.copy()
    for i, row in new_dev.iterrows():
        name = str(row.get('device_name', '')).strip()
        if not name:
            continue
        dtype, vendor = dtype_map.get(name, ('L3 Switch', 'Cisco'))
        ip, mask      = ip_map.get(name, ('', ''))

        def _fill(col, val):
            if not str(new_dev.at[i, col]).strip():
                new_dev.at[i, col] = val

        _fill('device_type',      dtype)
        _fill('vendor',           vendor)
        _fill('mgmt_ip',          ip)
        _fill('mgmt_subnet_mask', mask)
        _fill('mgmt_vlan',        str(mgmt_vc['vlan_id']))

    # 4. 나머지 DF 생성
    vlans_df = _build_vlans_df(vlan_configs)
    iface_df = _build_interfaces_df(new_dev, links_df, vlan_configs)
    l3_df    = _build_l3_config_df(new_dev, vlan_configs, ip_map)

    return {
        'devices':    new_dev,
        'vlans':      vlans_df,
        'interfaces': iface_df,
        'l3_config':  l3_df,
    }
