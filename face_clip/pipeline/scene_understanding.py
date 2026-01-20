# pipeline/scene_understanding.py

from typing import List, Dict

def select_scenes(
    scenes: List[Dict],
    target_frames: int,
    score_threshold: float = 1.0
) -> List[Dict]:
    """
    Select frames for the final clip based on scene scores, thresholds,
    and dominant entity logic.

    Args:
        scenes: List of scenes with 'start', 'length', 'score', 'dominant_entity' keys.
        target_frames: Total number of frames needed for the final clip.
        score_threshold: Minimum score for a scene to be considered.

    Returns:
        selected_frames: List of dicts with 'start' and 'length' for each chosen scene.
    """

    # -------------------------
    # 1️⃣ Filter scenes by threshold
    # -------------------------
    high_score_scenes = [s for s in scenes if s["score"] >= score_threshold]
    if not high_score_scenes:
        # fallback to top scenes if none pass threshold
        high_score_scenes = sorted(scenes, key=lambda s: s["score"], reverse=True)

    # -------------------------
    # 2️⃣ Prioritize dominant entity
    # -------------------------
    # If hero appears, boost its score
    for s in high_score_scenes:
        if s.get("dominant_entity") == "hero":
            s["score"] *= 1.5  # boost hero scenes

    # -------------------------
    # 3️⃣ Sort by score (descending)
    # -------------------------
    high_score_scenes.sort(key=lambda s: s["score"], reverse=True)

    # -------------------------
    # 4️⃣ Select scenes until target_frames is met
    # -------------------------
    selected_frames = []
    used_frames = 0

    for scene in high_score_scenes:
        if used_frames >= target_frames:
            break

        remaining = target_frames - used_frames
        take_len = min(scene["length"], remaining)

        selected_frames.append({
            "start": scene["start"],
            "length": take_len
        })
        used_frames += take_len

    # -------------------------
    # 5️⃣ Fallback: if still not enough frames, pad with next best scenes
    # -------------------------
    if used_frames < target_frames:
        remaining_frames = target_frames - used_frames
        additional_scenes = [s for s in scenes if s not in high_score_scenes]
        additional_scenes.sort(key=lambda s: s["score"], reverse=True)

        for scene in additional_scenes:
            if remaining_frames <= 0:
                break
            take_len = min(scene["length"], remaining_frames)
            selected_frames.append({
                "start": scene["start"],
                "length": take_len
            })
            remaining_frames -= take_len

    # -------------------------
    # 6️⃣ Sort final frames by start index to maintain temporal order
    # -------------------------
    selected_frames.sort(key=lambda s: s["start"])

    return selected_frames