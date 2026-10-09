# pipeline/scene_scoring.py
from typing import Dict

def score_scene(face_boxes, person_boxes, smart_score: float, weights: Dict[str, float]):
    """
    Dynamic score based on profile weights.
    """
    score = 0.0

    score += len(face_boxes) * weights.get("faces", 2.0)
    score += len(person_boxes) * weights.get("objects", 1.0)
    score += smart_score * weights.get("text_match", 3.0)

    return score