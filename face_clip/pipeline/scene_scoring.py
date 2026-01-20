# pipeline/scene_scoring.py

def score_scene(face_boxes, person_boxes):
    """
    Simple heuristic score:
    - Faces matter more than people
    """
    score = 0.0

    score += len(face_boxes) * 2.0
    score += len(person_boxes) * 1.0

    return score