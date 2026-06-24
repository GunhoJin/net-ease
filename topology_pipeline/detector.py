"""YOLO-based node detection."""

_model = None


def load_model(model_path: str, device: str = None):
    global _model
    import torch
    from ultralytics import YOLO
    dev = device or ("cuda" if torch.cuda.is_available() else "cpu")
    _model = YOLO(model_path)
    _model.to(dev)
    return _model


def detect_nodes(img, model, conf: float = 0.25) -> list:
    results = model(img, conf=conf, verbose=False)[0]
    nodes = []
    for i, box in enumerate(results.boxes):
        x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
        nodes.append({
            "id": i,
            "class": model.names[int(box.cls)],
            "conf": round(float(box.conf), 3),
            "bbox": [x1, y1, x2, y2],
            "center": [(x1 + x2) // 2, (y1 + y2) // 2],
            "label": "",
        })
    return nodes


def release_model(model):
    try:
        import torch
        del model
        torch.cuda.empty_cache()
    except Exception:
        pass
