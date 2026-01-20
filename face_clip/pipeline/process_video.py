import cv2
from pathlib import Path
from ultralytics import YOLO

from pipeline.scene_scoring import score_scene
from pipeline.scene_buffer import SceneBuffer
from pipeline.clip_writer import ClipWriter
from pipeline.scene_understanding import select_scenes
from pipeline.audio_utils import (
    extract_audio,
    cut_audio_segments,
    concat_audio,
    mux_audio_video
)

# =========================
# CONFIG
# =========================
MIN_SCENE_SEC = 1.2
PERSON_CONF = 0.45
FACE_CONF = 0.6
MIN_BOX_AREA_RATIO = 0.005
SCORE_THRESHOLD = 2.5  # min score to consider a scene meaningful

# =========================
# MODELS (LOADED ONCE)
# =========================
person_model = YOLO("face_clip/models/yolo11m.pt")
face_model = YOLO("face_clip/models/yolov8n-face-lindevs.pt")


def process_video(video_path: str, target_clip_duration_sec: int) -> str:
    # -------------------------
    # OPEN VIDEO
    # -------------------------
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError("Cannot open video")

    input_fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frame_size = (width, height)

    output_dir = Path("face_clip/videos/clips")
    output_dir.mkdir(parents=True, exist_ok=True)

    scene_buffer = SceneBuffer(fps=input_fps, min_scene_sec=MIN_SCENE_SEC)
    scenes = []
    frame_idx = 0
    prev_frame_gray = None

    # =========================
    # PASS 1: SCENE ANALYSIS + MOTION
    # =========================
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame_idx += 1
        H, W, _ = frame.shape
        frame_area = H * W

        # -----------------
        # OBJECT DETECTION
        # -----------------
        face_boxes = []
        person_boxes = []

        for box in person_model(frame, conf=PERSON_CONF, verbose=False)[0].boxes:
            if person_model.names[int(box.cls[0])] != "person":
                continue
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            if (x2 - x1) * (y2 - y1) < frame_area * MIN_BOX_AREA_RATIO:
                continue
            person_boxes.append((x1, y1, x2, y2))

        for box in face_model(frame, conf=FACE_CONF, verbose=False)[0].boxes:
            face_boxes.append(tuple(map(int, box.xyxy[0])))

        score = score_scene(face_boxes, person_boxes)

        # -----------------
        # MOTION ESTIMATION
        # -----------------
        frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if prev_frame_gray is not None:
            motion = cv2.absdiff(frame_gray, prev_frame_gray).mean() / 255.0
        else:
            motion = 0.0
        prev_frame_gray = frame_gray

        # -----------------
        # UPDATE SCENE BUFFER
        # -----------------
        scene_buffer.update(frame_idx, score, motion=motion)

        if scene_buffer.is_scene_complete():
            scene = scene_buffer.flush()
            # add placeholder dominant_entity info for now
            scene["dominant_entity"] = "hero" if len(face_boxes) > 0 else "side"
            scenes.append(scene)

    if scene_buffer.has_data():
        scene = scene_buffer.flush()
        scene["dominant_entity"] = "hero" if len(face_boxes) > 0 else "side"
        scenes.append(scene)

    cap.release()

    if not scenes:
        raise RuntimeError("No scenes detected")

    # =========================
    # SELECT SCENES USING SCENE UNDERSTANDING
    # =========================
    target_frames = int(target_clip_duration_sec * input_fps)
    selected_frames = select_scenes(
        scenes,
        target_frames=target_frames,
        score_threshold=SCORE_THRESHOLD
    )

    # =========================
    # PASS 2: WRITE VIDEO
    # =========================
    cap = cv2.VideoCapture(video_path)
    temp_video = output_dir / "clip_video_only.mp4"

    clip_writer = ClipWriter(
        output_path=str(temp_video),
        fps=input_fps,
        frame_size=frame_size
    )

    frame_idx = 0
    current_scene_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret or current_scene_idx >= len(selected_frames):
            break

        frame_idx += 1
        scene = selected_frames[current_scene_idx]
        start, end = scene["start"], scene["start"] + scene["length"]

        if frame_idx < start:
            continue
        if frame_idx >= end:
            current_scene_idx += 1
            continue

        clip_writer.write(frame)

    cap.release()
    clip_writer.close()

    # =========================
    # AUDIO PIPELINE
    # =========================
    temp_audio = output_dir / "original_audio.aac"
    extract_audio(video_path, temp_audio)

    audio_segments = cut_audio_segments(
        audio_path=str(temp_audio),
        segments=selected_frames,
        fps=input_fps,
        output_dir=output_dir / "audio_segments"
    )

    final_audio = output_dir / "final_audio.m4a"
    concat_audio(audio_segments, final_audio)

    final_output = output_dir / "clip.mp4"
    mux_audio_video(
        video_path=str(temp_video),
        audio_path=str(final_audio),
        output_path=str(final_output)
    )

    return str(final_output)