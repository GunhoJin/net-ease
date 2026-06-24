"""OpenCV Hough-line connection detection."""
import math
import cv2
import numpy as np


def mask_nodes(img: np.ndarray, nodes: list, margin: int = 10) -> np.ndarray:
    masked = img.copy()
    for node in nodes:
        x1, y1, x2, y2 = node["bbox"]
        cv2.rectangle(
            masked,
            (max(0, x1 - margin), max(0, y1 - margin)),
            (min(img.shape[1], x2 + margin), min(img.shape[0], y2 + margin)),
            (255, 255, 255), -1,
        )
    return masked


def _nodes_roi(nodes: list, img_shape: tuple, padding: int = 80):
    """Canvas ROI that tightly wraps all detected nodes."""
    h, w = img_shape[:2]
    xs = [n["bbox"][0] for n in nodes] + [n["bbox"][2] for n in nodes]
    ys = [n["bbox"][1] for n in nodes] + [n["bbox"][3] for n in nodes]
    return (
        max(0, min(xs) - padding),
        max(0, min(ys) - padding),
        min(w, max(xs) + padding),
        min(h, max(ys) + padding),
    )


def detect_lines(img: np.ndarray, nodes: list):
    masked = mask_nodes(img, nodes)

    # Restrict Hough to the region that contains nodes → filters UI panel noise
    if nodes:
        rx1, ry1, rx2, ry2 = _nodes_roi(nodes, img.shape)
        roi_img = masked[ry1:ry2, rx1:rx2]
        offset = (rx1, ry1)
    else:
        roi_img = masked
        offset = (0, 0)

    gray = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(blurred, 50, 150)
    lines_roi = cv2.HoughLinesP(
        edges, 1, np.pi / 180,
        threshold=40, minLineLength=30, maxLineGap=15,
    )

    if lines_roi is None:
        return None

    # Translate ROI-local coordinates back to full-image coordinates
    ox, oy = offset
    lines_full = lines_roi.copy()
    lines_full[:, 0, 0] += ox
    lines_full[:, 0, 1] += oy
    lines_full[:, 0, 2] += ox
    lines_full[:, 0, 3] += oy
    return lines_full


def find_connected_nodes(lines, nodes: list, max_dist: int = 60) -> list:
    if lines is None or not nodes:
        return []

    links = []
    seen: set = set()
    link_id = 1

    for line in lines:
        x1, y1, x2, y2 = line[0]
        src = min(nodes, key=lambda n: math.hypot(x1 - n["center"][0], y1 - n["center"][1]))
        dst = min(nodes, key=lambda n: math.hypot(x2 - n["center"][0], y2 - n["center"][1]))

        if src["id"] == dst["id"]:
            continue
        if math.hypot(x1 - src["center"][0], y1 - src["center"][1]) > max_dist:
            continue
        if math.hypot(x2 - dst["center"][0], y2 - dst["center"][1]) > max_dist:
            continue

        pair = tuple(sorted([src["id"], dst["id"]]))
        if pair in seen:
            continue
        seen.add(pair)

        links.append({
            "link_id": f"L{link_id:03d}",
            "node_a_id": src["id"],
            "node_b_id": dst["id"],
        })
        link_id += 1

    return links
