# utils.py
from pathlib import Path

# ------------------------
# Project paths (absolute)
# ------------------------
FACE_MODEL_PATH = Path("/Users/muditagrawal/Projects/zee work/Smart Video Clipping Tool/face_clip/models/yolov8n-face-lindevs.pt")
OBJECT_MODEL_PATH = Path("/Users/muditagrawal/Projects/zee work/Smart Video Clipping Tool/face_clip/models/yolo11m.pt")


# ------------------------
# Detection utils
# ------------------------
def yolo_to_deepsort(results):
    detections = []

    if not results or len(results) == 0:
        return detections

    r = results[0]
    if r.boxes is None or len(r.boxes) == 0:
        return detections

    boxes = r.boxes.xyxy.cpu().numpy()
    scores = r.boxes.conf.cpu().numpy()
    classes = r.boxes.cls.cpu().numpy().astype(int)
    names = r.names

    for (x1, y1, x2, y2), score, cls_id in zip(boxes, scores, classes):
        w = x2 - x1
        h = y2 - y1
        xc = x1 + w / 2
        yc = y1 + h / 2

        class_name = names.get(cls_id, "obj")

        detections.append([
            [float(xc), float(yc), float(w), float(h)],
            float(score),
            class_name
        ])

    return detections