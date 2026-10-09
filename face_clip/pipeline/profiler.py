import cv2
from typing import Dict

_DEFAULT_WEIGHTS: Dict[str, float] = {
    "faces": 1.0,
    "objects": 1.0,
    "motion": 1.0,
    "text_match": 1.0,
}


def profile_video(
    video_path: str,
    face_model,
    person_model,
    sample_fps: float = 1.0,
) -> Dict[str, float]:
    """
    Quick single-pass over the first ~60 sampled frames to determine the
    video's dominant 'vibe' (Action / Dialogue / Scenery) and return
    dynamic scoring weights for the main analysis pass.

    FIX: cap is now always released via try/finally.
    FIX: avg_motion denominator uses the number of diffs (samples - 1),
         but is guarded properly so a single-sample video doesn't divide by zero.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return dict(_DEFAULT_WEIGHTS)

    input_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_interval = max(1, int(input_fps / sample_fps))

    frame_idx = 0
    prev_gray = None

    total_motion = 0.0
    motion_diffs = 0       # FIX: count actual diffs, not samples
    total_faces = 0
    total_persons = 0
    samples = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % frame_interval == 0:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

                if prev_gray is not None:
                    total_motion += cv2.absdiff(gray, prev_gray).mean() / 255.0
                    motion_diffs += 1          # FIX: track diffs separately
                prev_gray = gray

                faces = face_model(frame, conf=0.5, verbose=False)[0].boxes
                persons = person_model(frame, conf=0.4, verbose=False)[0].boxes

                total_faces += len(faces)
                total_persons += sum(
                    1 for box in persons
                    if person_model.names[int(box.cls[0])] == "person"
                )

                samples += 1

            frame_idx += 1

            if samples >= 60:
                break
    finally:
        cap.release()  # FIX: always release

    if samples == 0:
        return dict(_DEFAULT_WEIGHTS)

    # FIX: divide motion by actual number of diffs (may be 0 for 1-sample videos)
    avg_motion  = total_motion / motion_diffs if motion_diffs > 0 else 0.0
    avg_faces   = total_faces  / samples
    avg_persons = total_persons / samples

    # Default weights
    w_faces      = 2.0
    w_objects    = 1.0
    w_motion     = 1.0
    w_text_match = 3.0

    if avg_motion > 0.05:
        # High motion → Action vibe
        w_motion  = 3.0
        w_faces   = 1.0
        w_objects = 2.0
    elif avg_faces > 0.5:
        # Lots of faces, low motion → Dialogue vibe
        w_faces  = 3.0
        w_motion = 0.5
    elif avg_persons == 0 and avg_faces == 0:
        # No people → Scenery / Abstract
        w_faces   = 0.0
        w_objects = 3.0
        w_motion  = 1.5

    return {
        "faces":      w_faces,
        "objects":    w_objects,
        "motion":     w_motion,
        "text_match": w_text_match,
        "profile_stats": {
            "avg_motion":  avg_motion,
            "avg_faces":   avg_faces,
            "avg_persons": avg_persons,
        },
    }
