from ultralytics import YOLO

CONF_THRESH = 0.6
MODEL_PATH = "yolov8n.pt"
DEVICE = "cuda"

model = YOLO(MODEL_PATH)
model.to(DEVICE)

def detect_human(frame):
    """
    Runs YOLO once to detect humans and birds.
    Returns:
        target_detected (bool)
        bbox_center (cx, cy) or None
        bbox (x1, y1, x2, y2) or None
        confidence (float)
        class_id (int) - 0=person, 14=bird
    """
    results = model(
        frame,
        device=0,
        conf=CONF_THRESH,
        classes=[0, 14],  # 0=person, 14=bird
        verbose=False
    )

    if not results or not results[0].boxes:
        return False, None, None, 0.0, None

    boxes = results[0].boxes
    if not hasattr(boxes, 'conf') or not hasattr(boxes, 'xyxy') or not hasattr(boxes, 'cls'):
        return False, None, None, 0.0, None

    best_conf = 0.0
    best_box = None
    best_class = None

    for i in range(len(boxes.conf)):
        conf = boxes.conf[i].item()
        if conf > best_conf:
            best_conf = conf
            best_box = boxes.xyxy[i].cpu().numpy().astype(int)
            best_class = int(boxes.cls[i].item())

    if best_box is None:
        return False, None, None, 0.0, None

    x1, y1, x2, y2 = best_box
    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2

    return True, (cx, cy), (x1, y1, x2, y2), best_conf, best_class
