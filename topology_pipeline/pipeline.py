"""Core pipeline: image → nodes + links → CSV files."""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MODEL = os.path.join(BASE_DIR, "VS_Code", "best.pt")


def _filter_edge_boxes(nodes: list, img_w: int, img_h: int,
                       edge_px: int = 50) -> list:
    """Remove bounding boxes stuck to image edges (GNS3 sidebar false positives)."""
    return [n for n in nodes if n["bbox"][0] > edge_px and n["bbox"][1] > edge_px]


def run(
    image_path: str,
    dataset_dir: str,
    model_path: str = None,
    conf: float = 0.15,
    progress_cb=None,
) -> dict:
    """
    Run the full topology detection pipeline.

    전략:
      1. Topology Summary 패널 OCR (GNS3 전체 화면 스크린샷이면 신뢰도 높음)
      2. Summary에서 장비/링크를 읽지 못하면 YOLO+Hough fallback

    Returns dict with keys: nodes(list), links(list), devices_csv, links_csv
    """
    if model_path is None:
        model_path = DEFAULT_MODEL

    def log(msg: str):
        if progress_cb:
            progress_cb(msg)

    import cv2
    import torch
    from . import ocr as _ocr
    from . import csv_writer as _cw

    log("이미지 로드 중...")
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"이미지 로드 실패: {image_path}")

    gpu = torch.cuda.is_available()

    # ------------------------------------------------------------------
    # 1단계: Topology Summary 패널 OCR (신뢰도 높음)
    # ------------------------------------------------------------------
    log("Topology Summary 패널 탐색 중...")
    from . import topo_summary as _ts
    reader = _ocr.load_reader(gpu=gpu)

    roi = _ts.detect_summary_panel(img)
    summary_devices, summary_links = [], []

    if roi:
        log(f"  → 패널 감지: x={roi[0]}~{roi[2]}")
        ocr_lines = _ts.ocr_summary_panel(img, reader, roi=roi)
        log(f"  → OCR 텍스트 {len(ocr_lines)}줄")
        summary_devices, summary_links = _ts.parse_summary_text(ocr_lines)
        log(f"  → 장비 {len(summary_devices)}개 / 링크 {len(summary_links)}개 파싱")
    else:
        log("  → Topology Summary 패널 없음 — YOLO 모드로 전환")

    if summary_devices and summary_links:
        # Summary 파싱 성공 → 바로 CSV 생성
        log("CSV 생성 중 (Summary 모드)...")
        os.makedirs(dataset_dir, exist_ok=True)
        dev_path = os.path.join(dataset_dir, "devices.csv")
        lnk_path = os.path.join(dataset_dir, "links.csv")
        _write_summary_devices_csv(summary_devices, dev_path)
        _write_summary_links_csv(summary_links, lnk_path)
        log("  → CSV 저장 완료")
        return {
            "nodes": summary_devices,
            "links": summary_links,
            "devices_csv": dev_path,
            "links_csv": lnk_path,
            "mode": "summary_ocr",
        }

    # ------------------------------------------------------------------
    # 2단계: YOLO + Hough fallback (캔버스만 캡처한 이미지 등)
    # ------------------------------------------------------------------
    log("YOLO 노드 감지 중...")
    from . import detector as _det
    from . import line_tracer as _lt

    model = _det.load_model(model_path)
    nodes = _det.detect_nodes(img, model, conf=conf)
    h, w = img.shape[:2]
    nodes = _filter_edge_boxes(nodes, w, h)
    log(f"  → {len(nodes)}개 노드 감지 (가장자리 필터 후)")

    log("OCR 레이블 추출 중...")
    for node in nodes:
        node["label"] = _ocr.extract_label_near_node(img, node, reader)
    log("  → 레이블 추출 완료")

    log("연결선 추적 중...")
    lines = _lt.detect_lines(img, nodes)
    links = _lt.find_connected_nodes(lines, nodes)
    log(f"  → {len(links)}개 연결 감지")

    log("CSV 생성 중 (YOLO 모드)...")
    os.makedirs(dataset_dir, exist_ok=True)
    dev_path = os.path.join(dataset_dir, "devices.csv")
    lnk_path = os.path.join(dataset_dir, "links.csv")
    _cw.write_devices_csv(nodes, dev_path)
    _cw.write_links_csv(links, nodes, lnk_path)
    log("  → CSV 저장 완료")

    _det.release_model(model)

    return {
        "nodes": nodes,
        "links": links,
        "devices_csv": dev_path,
        "links_csv": lnk_path,
        "mode": "yolo",
    }


# ------------------------------------------------------------------
# Summary 모드 전용 CSV 작성 (csv_writer 의 장비 타입 매핑 없이 단순 출력)
# ------------------------------------------------------------------
def _write_summary_devices_csv(devices: list, path: str) -> None:
    import csv
    fields = [
        "device_name", "device_type", "vendor", "model",
        "mgmt_ip", "mgmt_subnet_mask", "mgmt_vlan",
        "site", "role", "description",
    ]
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for d in devices:
            writer.writerow({k: d.get(k, "") for k in fields})


def _write_summary_links_csv(links: list, path: str) -> None:
    import csv
    fields = [
        "link_id", "device_a", "port_a", "device_b", "port_b",
        "link_type", "speed", "description",
    ]
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for lnk in links:
            row = {k: lnk.get(k, "") for k in fields}
            row.setdefault("link_type", "ethernet")
            row.setdefault("description", "auto: topology summary")
            writer.writerow(row)
