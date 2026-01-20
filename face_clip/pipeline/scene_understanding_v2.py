# pipeline/scene_understanding_v2.py

import cv2
from typing import List, Dict

def compute_motion(prev_frame, curr_frame):
    """
    Compute motion magnitude using optical flow (Farneback method)
    Returns a normalized motion score for the frame.
    """
    prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
    curr_gray = cv2.cvtColor(curr_frame, cv2.COLOR_BGR2GRAY)
    
    flow = cv2.calcOpticalFlowFarneback(
        prev_gray, curr_gray, None,
        pyr_scale=0.5, levels=3, winsize=15,
        iterations=3, poly_n=5, poly_sigma=1.2, flags=0
    )
    mag, _ = cv2.cartToPolar(flow[...,0], flow[...,1])
    return mag.mean()  # average motion magnitude

def select_scenes_v2(
    scenes: List[Dict],
    target_frames: int,
    score_threshold: float = 1.0
) -> List[Dict]:
    """
    Select scenes using combined scoring:
    - Original scene score (faces/people)
    - Motion magnitude
    - Dominant entity logic
    """
    # 1️⃣ Boost hero presence
    for s in scenes:
        if s.get("dominant_entity") == "hero":
            s["score"] *= 1.5
    
    # 2️⃣ Normalize motion scores if available
    max_motion = max((s.get("motion", 0) for s in scenes), default=1)
    for s in scenes:
        s["motion_score"] = (s.get("motion", 0) / max_motion) * 1.0
        s["combined_score"] = s["score"] + s["motion_score"]
    
    # 3️⃣ Filter by score threshold
    high_score_scenes = [s for s in scenes if s["combined_score"] >= score_threshold]
    if not high_score_scenes:
        high_score_scenes = sorted(scenes, key=lambda s: s["combined_score"], reverse=True)
    
    # 4️⃣ Sort by combined_score
    high_score_scenes.sort(key=lambda s: s["combined_score"], reverse=True)
    
    # 5️⃣ Select scenes until target_frames
    selected_frames = []
    used_frames = 0
    for s in high_score_scenes:
        if used_frames >= target_frames:
            break
        take_len = min(s["length"], target_frames - used_frames)
        selected_frames.append({"start": s["start"], "length": take_len})
        used_frames += take_len
    
    # 6️⃣ Fallback padding with remaining scenes
    if used_frames < target_frames:
        remaining_frames = target_frames - used_frames
        additional_scenes = [s for s in scenes if s not in high_score_scenes]
        additional_scenes.sort(key=lambda s: s["combined_score"], reverse=True)
        for s in additional_scenes:
            if remaining_frames <= 0:
                break
            take_len = min(s["length"], remaining_frames)
            selected_frames.append({"start": s["start"], "length": take_len})
            remaining_frames -= take_len
    
    # 7️⃣ Sort by start index for temporal continuity
    selected_frames.sort(key=lambda s: s["start"])
    return selected_frames