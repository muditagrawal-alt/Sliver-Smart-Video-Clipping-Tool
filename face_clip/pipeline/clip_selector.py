# pipeline/clip_selector.py

START_THRESHOLD = 2.5
END_THRESHOLD = 1.0
MIN_CLIP_FRAMES = 20


def should_start_clip(avg_score, active):
    return (not active) and avg_score >= START_THRESHOLD


def should_end_clip(avg_score, active, clip_length):
    if not active:
        return False
    if clip_length < MIN_CLIP_FRAMES:
        return False
    return avg_score <= END_THRESHOLD