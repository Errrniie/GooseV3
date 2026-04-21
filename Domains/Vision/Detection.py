from __future__ import annotations

from typing import Any, Dict, List

from ultralytics import YOLO

import Config.Vision_Config as vcfg

MODEL_PATH = "yolov8n.pt"
DEVICE = "cuda"

model = YOLO(MODEL_PATH)
model.to(DEVICE)


def detect_objects(frame) -> List[Dict[str, Any]]:
    """
    Run YOLO once; return all boxes for configured person/bird classes.

    Each item: class_id, class_name, confidence, bbox [x1,y1,x2,y2], center [cx,cy].
    Reads thresholds from Config.Vision_Config (API-synced).
    """
    yconf = float(vcfg.VISION_YOLO_MIN_CONF)
    pid = int(vcfg.VISION_CLASS_PERSON_ID)
    bid = int(vcfg.VISION_CLASS_BIRD_ID)
    max_det = int(vcfg.VISION_MAX_DETECTIONS)
    classes = [pid, bid]

    results = model(
        frame,
        device=0,
        conf=yconf,
        classes=classes,
        max_det=max_det,
        verbose=False,
    )

    if not results or not results[0].boxes:
        return []

    boxes = results[0].boxes
    if not hasattr(boxes, "conf") or not hasattr(boxes, "xyxy") or not hasattr(boxes, "cls"):
        return []

    n = len(boxes.conf)
    if n == 0:
        return []

    xyxy = boxes.xyxy.cpu().numpy()
    confs = boxes.conf.cpu().numpy()
    clss = boxes.cls.cpu().numpy().astype(int)

    names = vcfg.CLASS_ID_TO_NAME
    out: List[Dict[str, Any]] = []
    for i in range(n):
        cid = int(clss[i])
        x1, y1, x2, y2 = (int(xyxy[i, j]) for j in range(4))
        cf = float(confs[i])
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        out.append(
            {
                "class_id": cid,
                "class_name": names.get(cid, str(cid)),
                "confidence": cf,
                "bbox": [x1, y1, x2, y2],
                "center": [cx, cy],
            }
        )
    return out


def detect_human(frame):
    """
    Legacy: single best box by confidence over person/bird (for old tests/scripts).

    Returns:
        target_detected, bbox_center, bbox tuple, confidence, class_id
    """
    dets = detect_objects(frame)
    if not dets:
        return False, None, None, 0.0, None

    best = max(dets, key=lambda d: d["confidence"])
    x1, y1, x2, y2 = best["bbox"]
    cx, cy = best["center"]
    return (
        True,
        (cx, cy),
        (x1, y1, x2, y2),
        float(best["confidence"]),
        int(best["class_id"]),
    )
