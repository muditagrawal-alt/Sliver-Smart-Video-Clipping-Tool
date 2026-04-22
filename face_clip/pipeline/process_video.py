import cv2
from pathlib import Path
from typing import Callable, Optional

from ultralytics import YOLO

from .audio_utils import (
    concat_audio,
    cut_audio_segments,
    extract_audio,
    mux_audio_video,
)
from .clip_writer import ClipWriter
from .scene_buffer import SceneBuffer
from .scene_scoring import score_scene
from .scene_understanding import select_scenes

# =========================
# CONFIG
# =========================
MIN_SCENE_SEC = 1.2
PERSON_CONF = 0.45
FACE_CONF = 0.6
MIN_BOX_AREA_RATIO = 0.005
SCORE_THRESHOLD = 2.5

# =========================
# MODELS (LOADED ONCE)
# =========================
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = PACKAGE_ROOT / "models"
DEFAULT_OUTPUT_DIR = PACKAGE_ROOT / "videos" / "clips"

person_model = YOLO((MODELS_DIR / "yolo11m.pt").as_posix())
face_model = YOLO((MODELS_DIR / "yolov8n-face-lindevs.pt").as_posix())


ProgressCallback = Optional[Callable[[int, str], None]]


def _emit_progress(progress_callback: ProgressCallback, percent: int, message: str):
    if progress_callback is None:
        return
    progress_callback(max(0, min(100, int(percent))), message)


def process_video(
    video_path: str,
    target_clip_duration_sec: int,
    output_dir: Optional[str] = None,
    progress_callback: ProgressCallback = None,
) -> str:
    _emit_progress(progress_callback, 2, "Opening source video.")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError("Cannot open video")

    input_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frame_size = (width, height)
    total_input_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    analysis_update_interval = max(1, int(input_fps))

    output_dir = Path(output_dir) if output_dir else DEFAULT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    scene_buffer = SceneBuffer(fps=input_fps, min_scene_sec=MIN_SCENE_SEC)
    scenes = []
    frame_idx = 0
    prev_frame_gray = None

    _emit_progress(progress_callback, 5, "Analyzing scenes and motion.")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame_idx += 1
        height_frame, width_frame, _ = frame.shape
        frame_area = height_frame * width_frame

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

        frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if prev_frame_gray is not None:
            motion = cv2.absdiff(frame_gray, prev_frame_gray).mean() / 255.0
        else:
            motion = 0.0
        prev_frame_gray = frame_gray

        scene_buffer.update(frame_idx, score, motion=motion)

        if scene_buffer.is_scene_complete():
            scene = scene_buffer.flush()
            scene["dominant_entity"] = "hero" if len(face_boxes) > 0 else "side"
            scenes.append(scene)

        if total_input_frames and (frame_idx == 1 or frame_idx % analysis_update_interval == 0):
            analysis_percent = 5 + int((frame_idx / total_input_frames) * 45)
            _emit_progress(progress_callback, analysis_percent, "Analyzing scenes and motion.")

    if scene_buffer.has_data():
        scene = scene_buffer.flush()
        scene["dominant_entity"] = "hero" if len(face_boxes) > 0 else "side"
        scenes.append(scene)

    cap.release()

    if not scenes:
        raise RuntimeError("No scenes detected")

    _emit_progress(progress_callback, 55, "Selecting the strongest summary moments.")

    target_frames = int(target_clip_duration_sec * input_fps)
    selected_frames = select_scenes(
        scenes,
        target_frames=target_frames,
        score_threshold=SCORE_THRESHOLD,
    )
    if not selected_frames:
        raise RuntimeError("No scenes selected")

    _emit_progress(progress_callback, 60, "Rendering summary video.")

    cap = cv2.VideoCapture(video_path)
    temp_video = output_dir / "clip_video_only.mp4"

    clip_writer = ClipWriter(
        output_path=str(temp_video),
        fps=input_fps,
        frame_size=frame_size,
    )

    frame_idx = 0
    current_scene_idx = 0
    written_output_frames = 0
    total_selected_frames = max(1, sum(int(scene["length"]) for scene in selected_frames))
    render_update_interval = max(1, int(input_fps))

    while True:
        ret, frame = cap.read()
        if not ret or current_scene_idx >= len(selected_frames):
            break

        frame_idx += 1
        scene = selected_frames[current_scene_idx]
        start = scene["start"]
        end = scene["start"] + scene["length"]

        if frame_idx < start:
            continue
        if frame_idx >= end:
            current_scene_idx += 1
            continue

        clip_writer.write(frame)
        written_output_frames += 1

        if written_output_frames == 1 or written_output_frames % render_update_interval == 0:
            render_percent = 60 + int((written_output_frames / total_selected_frames) * 24)
            _emit_progress(progress_callback, render_percent, "Rendering summary video.")

    cap.release()
    clip_writer.close()

    _emit_progress(progress_callback, 86, "Extracting source audio.")

    temp_audio = output_dir / "original_audio.aac"
    extract_audio(video_path, temp_audio)

    _emit_progress(progress_callback, 90, "Cutting audio segments.")

    audio_segments = cut_audio_segments(
        audio_path=str(temp_audio),
        segments=selected_frames,
        fps=input_fps,
        output_dir=output_dir / "audio_segments",
    )

    _emit_progress(progress_callback, 95, "Joining soundtrack.")

    final_audio = output_dir / "final_audio.m4a"
    concat_audio(audio_segments, final_audio)

    _emit_progress(progress_callback, 98, "Muxing final summary video.")

    final_output = output_dir / "clip.mp4"
    mux_audio_video(
        video_path=str(temp_video),
        audio_path=str(final_audio),
        output_path=str(final_output),
    )

    _emit_progress(progress_callback, 100, "Summary ready.")
    return str(final_output)
