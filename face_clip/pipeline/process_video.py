import cv2
from pathlib import Path
from typing import Callable, Optional

from ultralytics import YOLO

from .audio_utils import (
    concat_audio,
    cut_audio_segments,
    extract_audio,
    has_audio as _has_audio,   # FIX: alias to avoid name collision with local variable
    mux_audio_video,
)
from .clip_writer import ClipWriter
from .scene_buffer import SceneBuffer
from .scene_scoring import score_scene
from .scene_understanding import select_scenes
from .smart_models import set_smart_prompt, get_smart_score
from .profiler import profile_video

# =========================
# CONFIG
# =========================
MIN_SCENE_SEC = 1.2
PERSON_CONF = 0.45
FACE_CONF = 0.6
MIN_BOX_AREA_RATIO = 0.005
SCORE_THRESHOLD = 2.5

# =========================
# MODELS (LOADED ONCE AT IMPORT TIME)
# =========================
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = PACKAGE_ROOT / "models"
DEFAULT_OUTPUT_DIR = PACKAGE_ROOT / "videos" / "clips"


def _init_models():
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    face_path = MODELS_DIR / "yolov8n-face-lindevs.pt"
    if not face_path.exists():
        url = "https://github.com/lindevs/yolov8-face/releases/download/1.0.0/yolov8n-face-lindevs.pt"
        try:
            import urllib.request
            urllib.request.urlretrieve(url, str(face_path))
        except Exception:
            pass

    person_path = MODELS_DIR / "yolo11m.pt"
    p_model = YOLO(person_path.as_posix() if person_path.exists() else "yolo11m.pt")
    f_model = YOLO(face_path.as_posix() if face_path.exists() else "yolov8n.pt")
    return p_model, f_model


person_model, face_model = _init_models()


ProgressCallback = Optional[Callable[[int, str], None]]


def _emit_progress(progress_callback: ProgressCallback, percent: int, message: str) -> None:
    if progress_callback is None:
        return
    progress_callback(max(0, min(100, int(percent))), message)


def process_video(
    video_path: str,
    target_clip_duration_sec: int,
    output_dir: Optional[str] = None,
    progress_callback: ProgressCallback = None,
    prompt: Optional[str] = None,
) -> str:
    _emit_progress(progress_callback, 2, "Opening source video.")

    set_smart_prompt(prompt if prompt else "")

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
    scenes: list = []
    frame_idx = 0
    prev_frame_gray = None

    # Track whether the current scene has seen any faces — used for dominant_entity
    # on the partial last scene.  Reset whenever the buffer is flushed.
    scene_has_face = False

    _emit_progress(progress_callback, 3, "Profiling video content.")
    dynamic_weights = profile_video(video_path, face_model, person_model)

    # Decide once whether CLIP scoring is active for this job.
    use_clip = bool(prompt and prompt.strip())

    _emit_progress(progress_callback, 5, "Analyzing scenes and motion.")

    # Pass 1: Scene detection and analysis (0-indexed frame numbering)
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame_area = frame.shape[0] * frame.shape[1]

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

            # CLIP zero-shot semantic score if prompt provided
            smart_score = get_smart_score(frame) if use_clip else 0.0
            score = score_scene(face_boxes, person_boxes, smart_score, dynamic_weights)

            frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if prev_frame_gray is not None:
                motion = cv2.absdiff(frame_gray, prev_frame_gray).mean() / 255.0
            else:
                motion = 0.0
            prev_frame_gray = frame_gray

            if face_boxes:
                scene_has_face = True

            scene_buffer.update(frame_idx, score, motion=motion)

            if scene_buffer.is_scene_complete():
                scene = scene_buffer.flush()
                scene["dominant_entity"] = "hero" if scene_has_face else "side"
                scene["avg_motion"] = (
                    float(scene.get("avg_motion", 0.0)) * dynamic_weights.get("motion", 1.0)
                )
                scenes.append(scene)
                scene_has_face = False

            if total_input_frames and (frame_idx == 0 or frame_idx % analysis_update_interval == 0):
                analysis_percent = 5 + int(((frame_idx + 1) / total_input_frames) * 45)
                _emit_progress(progress_callback, analysis_percent, "Analyzing scenes and motion.")

            frame_idx += 1

        # Flush any remaining partial scene
        if scene_buffer.has_data():
            scene = scene_buffer.flush()
            scene["dominant_entity"] = "hero" if scene_has_face else "side"
            scene["avg_motion"] = (
                float(scene.get("avg_motion", 0.0)) * dynamic_weights.get("motion", 1.0)
            )
            scenes.append(scene)

    finally:
        cap.release()

    if not scenes:
        raise RuntimeError("No scenes detected")

    _emit_progress(progress_callback, 55, "Selecting the strongest summary moments.")

    total_valid_frames = sum(int(s.get("length", 0)) for s in scenes)
    target_frames = min(int(target_clip_duration_sec * input_fps), total_valid_frames)

    selected_frames = select_scenes(
        scenes,
        target_frames=target_frames,
        score_threshold=SCORE_THRESHOLD,
    )
    if not selected_frames:
        raise RuntimeError("No scenes selected")

    _emit_progress(progress_callback, 60, "Rendering summary video.")

    cap2 = cv2.VideoCapture(video_path)
    temp_video = output_dir / "clip_video_only.mp4"

    clip_writer = ClipWriter(
        output_path=str(temp_video),
        fps=input_fps,
        frame_size=frame_size,
    )

    try:
        frame_idx = 0
        current_scene_idx = 0
        written_output_frames = 0
        total_selected_frames = max(1, sum(int(s["length"]) for s in selected_frames))
        render_update_interval = max(1, int(input_fps))

        while True:
            ret, frame = cap2.read()
            if not ret or current_scene_idx >= len(selected_frames):
                break

            # Advance current_scene_idx until we find the scene covering frame_idx or reach the end
            while current_scene_idx < len(selected_frames):
                curr = selected_frames[current_scene_idx]
                if frame_idx < curr["start"] + curr["length"]:
                    break
                current_scene_idx += 1

            if current_scene_idx >= len(selected_frames):
                break

            scene = selected_frames[current_scene_idx]
            if frame_idx >= scene["start"]:
                clip_writer.write(frame)
                written_output_frames += 1

                if written_output_frames == 1 or written_output_frames % render_update_interval == 0:
                    render_percent = 60 + int((written_output_frames / total_selected_frames) * 24)
                    _emit_progress(progress_callback, render_percent, "Rendering summary video.")

            frame_idx += 1
    finally:
        cap2.release()
        clip_writer.close()

    _emit_progress(progress_callback, 86, "Extracting source audio.")

    temp_audio = output_dir / "original_audio.aac"
    audio_present = extract_audio(video_path, str(temp_audio))

    if not audio_present:
        _emit_progress(progress_callback, 100, "Summary ready. (No audio detected)")
        final_output = output_dir / "clip.mp4"
        mux_audio_video(
            video_path=str(temp_video),
            audio_path=None,
            output_path=str(final_output),
        )
        return str(final_output)

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
