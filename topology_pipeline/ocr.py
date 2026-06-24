"""EasyOCR-based label extraction near detected nodes."""

_reader = None


def load_reader(gpu: bool = True):
    global _reader
    import easyocr
    _reader = easyocr.Reader(["en"], gpu=gpu)
    return _reader


def extract_label_near_node(img, node: dict, reader, padding: int = 20) -> str:
    h, w = img.shape[:2]
    x1, y1, x2, y2 = node["bbox"]
    # Search the strip directly below the bounding box
    roi = img[y2: min(h, y2 + 40), max(0, x1 - padding): min(w, x2 + padding)]
    if roi.size == 0:
        return ""
    results = reader.readtext(roi, detail=1)
    texts = [text for _, text, conf in results if conf > 0.5]
    return " ".join(texts) if texts else ""
