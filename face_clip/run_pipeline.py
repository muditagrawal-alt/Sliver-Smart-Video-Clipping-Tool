import cv2
from pathlib import Path
from ultralytics import YOLO
from deep_sort_realtime.deepsort_tracker import DeepSort

from pipeline.clip_logic import select_focus
from pipeline.clip_writer import ClipWriter
from pipeline.scene_scoring import score_scene
from pipeline.scene_buffer import SceneBuffer
from pipeline.clip_selector import should_start_clip, should_end_clip
from pipeline.audio_merge import merge_audio

# =========================
# CONFIG
# =========================
PERSON_CONF = 0.45
FACE_CONF = 0.6
OBJECT_CONF = 0.2

MIN_BOX_AREA_RATIO = 0.005
MAX_TRACK_AGE = 10
OBJECT_DETECT_EVERY_N_FRAMES = 8

BUFFER_WINDOW_FRAMES = 30
FPS = 25
FRAME_SIZE = (320, 320)

# =========================
# MODELS (LOAD ONCE)
# =========================
person_model = YOLO("face_clip/models/yolo11m.pt")
object_model = YOLO("face_clip/models/yolo11m.pt")
face_model   = YOLO("face_clip/models/yolov8n-face-lindevs.pt")

tracker = DeepSort(max_age=MAX_TRACK_AGE, n_init=2, max_iou_distance=0.7)

# =========================
# PIPELINE
# =========================
def process_video(video_path: str, target_clip_duration_sec: int) -> str:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    output_dir = Path("face_clip/videos/clips")
    output_dir.mkdir(parents=True, exist_ok=True)

    clip_writer = ClipWriter(output_dir, fps=FPS, frame_size=FRAME_SIZE)
    scene_buffer = SceneBuffer(window_size_frames=BUFFER_WINDOW_FRAMES)

    max_frames = target_clip_duration_sec * FPS
    written_frames = 0
    frame_idx = 0
    cached_object_boxes = []

    while written_frames < max_frames:
        ret, frame = cap.read()
        if not ret:
            break

        frame_idx += 1
        H, W, _ = frame.shape
        FRAME_AREA = H * W

        detections = []
        face_boxes, person_boxes = [], []

        # PERSON
        for box in person_model(frame, conf=PERSON_CONF)[0].boxes:
            if person_model.names[int(box.cls[0])] != "person":
                continue
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            if (x2 - x1) * (y2 - y1) < FRAME_AREA * MIN_BOX_AREA_RATIO:
                continue
            person_boxes.append((x1, y1, x2, y2))
            detections.append(([x1, y1, x2 - x1, y2 - y1], float(box.conf[0]), "person"))

        # OBJECT (SKIPPED FRAMES)
        if frame_idx % OBJECT_DETECT_EVERY_N_FRAMES == 0:
            cached_object_boxes = []
            for box in object_model(frame, conf=OBJECT_CONF)[0].boxes:
                cls = object_model.names[int(box.cls[0])]
                if cls == "person":
                    continue
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                if (x2 - x1) * (y2 - y1) < FRAME_AREA * MIN_BOX_AREA_RATIO:
                    continue
                cached_object_boxes.append((x1, y1, x2, y2))
                detections.append(([x1, y1, x2 - x1, y2 - y1], float(box.conf[0]), cls))

        tracker.update_tracks(detections, frame=frame)

        # FACE
        for box in face_model(frame, conf=FACE_CONF)[0].boxes:
            face_boxes.append(tuple(map(int, box.xyxy[0])))

        # SCENE
        score = score_scene(face_boxes, person_boxes)
        scene_buffer.add(score, frame_idx)
        avg_score = scene_buffer.average_score()

        focus_box, focus_label = select_focus(
            face_boxes,
            person_boxes,
            cached_object_boxes,
            frame.shape
        )
        clip_writer.write(frame, focus_box, focus_label)
        written_frames += 1

    cap.release()
    clip_writer.close()
    return str(clip_writer.output_path)