"""Write devices.csv and links.csv from detected topology."""
import csv
import os

DEVICES_FIELDS = [
    "device_name", "device_type", "vendor", "model",
    "mgmt_ip", "mgmt_subnet_mask", "mgmt_vlan",
    "site", "role", "description",
]
LINKS_FIELDS = [
    "link_id", "device_a", "port_a", "device_b", "port_b",
    "link_type", "speed", "description",
]

_TYPE_MAP = {
    "router":           "router",
    "switch":           "switch",
    "switch_multilayer":"layer3_switch",
    "firewall":         "firewall",
    "server":           "server",
    "cloud":            "cloud",
    "pc":               "pc",
    "hub":              "hub",
    "vm":               "vm",
    "wlan":             "wlan_ap",
}


def _node_label(node: dict) -> str:
    return node.get("label") or f"{node['class']}_{node['id']:02d}"


def write_devices_csv(nodes: list, output_path: str) -> None:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DEVICES_FIELDS)
        writer.writeheader()
        for node in nodes:
            writer.writerow({
                "device_name":      _node_label(node),
                "device_type":      _TYPE_MAP.get(node["class"], node["class"]),
                "vendor":           "",
                "model":            "",
                "mgmt_ip":          "",
                "mgmt_subnet_mask": "",
                "mgmt_vlan":        "",
                "site":             "",
                "role":             "",
                "description":      f"auto: {node['class']} conf={node['conf']}",
            })


def write_links_csv(links: list, nodes: list, output_path: str) -> None:
    label_map = {n["id"]: _node_label(n) for n in nodes}
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LINKS_FIELDS)
        writer.writeheader()
        for lnk in links:
            writer.writerow({
                "link_id":     lnk["link_id"],
                "device_a":    label_map.get(lnk["node_a_id"], ""),
                "port_a":      "",
                "device_b":    label_map.get(lnk["node_b_id"], ""),
                "port_b":      "",
                "link_type":   "ethernet",
                "speed":       "",
                "description": "auto-detected",
            })
