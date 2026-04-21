# =============================================================================
# Vision / YOLO (synced from ConfigManager + runtime_config.json ``vision``)
# =============================================================================

VISION_YOLO_MIN_CONF = 0.25
VISION_HUMAN_MIN_CONF = 0.8
VISION_BIRD_MIN_CONF = 0.35

VISION_CLASS_PERSON_ID = 0
VISION_CLASS_BIRD_ID = 14

VISION_MAX_DETECTIONS = 50

CLASS_ID_TO_NAME = {
    VISION_CLASS_PERSON_ID: "person",
    VISION_CLASS_BIRD_ID: "bird",
}
