import math
from typing import Dict, List, Tuple

HERO_BOOST = 1.5
MOTION_WEIGHT = 1.0
CONTEXT_WEIGHTS = (1.0, 2.0, 3.0, 2.0, 1.0)
PRE_CONTEXT_SCENES = 1
POST_CONTEXT_SCENES = 1
MAX_EVENT_GAP_SCENES = 1
EPSILON = 1e-9


def _build_priority_scores(scenes: List[Dict]) -> List[float]:
    max_motion = max((float(scene.get("avg_motion", 0.0)) for scene in scenes), default=0.0)
    priority_scores = []

    for scene in scenes:
        score = float(scene.get("score", 0.0))
        if scene.get("dominant_entity") == "hero":
            score *= HERO_BOOST

        if max_motion > 0:
            motion_bonus = float(scene.get("avg_motion", 0.0)) / max_motion
            score += motion_bonus * MOTION_WEIGHT

        priority_scores.append(score)

    return priority_scores


def _build_context_scores(priority_scores: List[float]) -> List[float]:
    radius = len(CONTEXT_WEIGHTS) // 2
    context_scores = []

    for idx in range(len(priority_scores)):
        weighted_total = 0.0
        weight_total = 0.0

        for offset, weight in enumerate(CONTEXT_WEIGHTS):
            neighbor_idx = idx + offset - radius
            if 0 <= neighbor_idx < len(priority_scores):
                weighted_total += priority_scores[neighbor_idx] * weight
                weight_total += weight

        context_scores.append(weighted_total / weight_total if weight_total else 0.0)

    return context_scores


def _pick_seed_indices(
    priority_scores: List[float],
    target_frames: int,
    average_scene_length: float,
    score_threshold: float,
) -> List[int]:
    threshold_seeds = [idx for idx, score in enumerate(priority_scores) if score >= score_threshold]
    if threshold_seeds:
        return threshold_seeds

    if not priority_scores:
        return []

    if max(priority_scores) - min(priority_scores) <= EPSILON:
        event_span = max(1, int(round(average_scene_length * (PRE_CONTEXT_SCENES + POST_CONTEXT_SCENES + 1))))
        desired_events = max(1, min(len(priority_scores), math.ceil(target_frames / event_span)))
        if desired_events == 1:
            return [len(priority_scores) // 2]

        seeds = []
        last_index = len(priority_scores) - 1
        for event_idx in range(desired_events):
            pos = round(event_idx * last_index / (desired_events - 1))
            seeds.append(pos)
        return sorted(set(seeds))

    event_span = max(1, int(round(average_scene_length * (PRE_CONTEXT_SCENES + POST_CONTEXT_SCENES + 1))))
    desired_events = max(1, min(len(priority_scores), math.ceil(target_frames / event_span)))
    suppression_radius = PRE_CONTEXT_SCENES + POST_CONTEXT_SCENES + MAX_EVENT_GAP_SCENES + 1

    ranked_indices = sorted(range(len(priority_scores)), key=lambda idx: (-priority_scores[idx], idx))
    seeds = []

    for idx in ranked_indices:
        if any(abs(idx - existing) <= suppression_radius for existing in seeds):
            continue
        seeds.append(idx)
        if len(seeds) >= desired_events:
            break

    if not seeds:
        seeds.append(ranked_indices[0])

    return sorted(seeds)


def _merge_seed_windows(seed_indices: List[int], scene_count: int) -> List[Tuple[int, int]]:
    if not seed_indices:
        return []

    windows = []
    for idx in sorted(seed_indices):
        start_idx = max(0, idx - PRE_CONTEXT_SCENES)
        end_idx = min(scene_count - 1, idx + POST_CONTEXT_SCENES)
        windows.append((start_idx, end_idx))

    merged = [list(windows[0])]
    for start_idx, end_idx in windows[1:]:
        previous_end = merged[-1][1]
        if start_idx <= previous_end + MAX_EVENT_GAP_SCENES + 1:
            merged[-1][1] = max(previous_end, end_idx)
        else:
            merged.append([start_idx, end_idx])

    return [(start_idx, end_idx) for start_idx, end_idx in merged]


def _event_segment(
    scenes: List[Dict],
    start_idx: int,
    end_idx: int,
) -> Dict[str, int]:
    start_frame = int(scenes[start_idx]["start"])
    end_frame = int(scenes[end_idx]["start"]) + int(scenes[end_idx]["length"])
    return {"start": start_frame, "length": max(0, end_frame - start_frame)}


def _best_subsegment(
    scenes: List[Dict],
    context_scores: List[float],
    start_idx: int,
    end_idx: int,
    target_frames: int,
) -> Dict[str, int]:
    if target_frames <= 0:
        return {"start": int(scenes[start_idx]["start"]), "length": 0}

    event_lengths = [int(scenes[idx]["length"]) for idx in range(start_idx, end_idx + 1)]
    total_frames = sum(event_lengths)
    if total_frames <= target_frames:
        return _event_segment(scenes, start_idx, end_idx)

    event_scores = [context_scores[idx] for idx in range(start_idx, end_idx + 1)]
    best_start = int(scenes[start_idx]["start"])
    best_value = float("-inf")

    right = 0
    full_window_frames = 0
    full_window_value = 0.0

    for left, scene_length in enumerate(event_lengths):
        while right < len(event_lengths) and full_window_frames + event_lengths[right] <= target_frames:
            full_window_frames += event_lengths[right]
            full_window_value += event_scores[right] * event_lengths[right]
            right += 1

        candidate_value = full_window_value
        if right < len(event_lengths) and full_window_frames < target_frames:
            candidate_value += event_scores[right] * (target_frames - full_window_frames)

        candidate_start = int(scenes[start_idx + left]["start"])
        if (
            candidate_value > best_value + EPSILON
            or (
                abs(candidate_value - best_value) <= EPSILON
                and candidate_start < best_start
            )
        ):
            best_start = candidate_start
            best_value = candidate_value

        if right == left:
            right += 1
            continue

        full_window_frames -= scene_length
        full_window_value -= event_scores[left] * scene_length

    return {"start": best_start, "length": int(target_frames)}


def _merge_selected_segments(segments: List[Dict]) -> List[Dict]:
    if not segments:
        return []

    ordered_segments = sorted(segments, key=lambda segment: segment["start"])
    merged = [ordered_segments[0].copy()]

    for segment in ordered_segments[1:]:
        previous = merged[-1]
        previous_end = previous["start"] + previous["length"]
        segment_end = segment["start"] + segment["length"]

        if segment["start"] <= previous_end:
            previous["length"] = max(previous_end, segment_end) - previous["start"]
        else:
            merged.append(segment.copy())

    return merged


def _invert_ranges(ranges: List[Tuple[int, int]], scene_count: int) -> List[Tuple[int, int]]:
    if scene_count <= 0:
        return []

    if not ranges:
        return [(0, scene_count - 1)]

    uncovered = []
    cursor = 0

    for start_idx, end_idx in sorted(ranges):
        if cursor < start_idx:
            uncovered.append((cursor, start_idx - 1))
        cursor = max(cursor, end_idx + 1)

    if cursor < scene_count:
        uncovered.append((cursor, scene_count - 1))

    return uncovered


def select_scenes(
    scenes: List[Dict],
    target_frames: int,
    score_threshold: float = 1.0,
) -> List[Dict]:
    """
    Build a summary from multiple key moments while preserving local context.

    Instead of stitching together isolated high-score buckets, this selector:
    1. finds strong moments,
    2. expands them into short contextual events,
    3. merges nearby events,
    4. and picks the best events until the requested duration is filled.
    """

    if not scenes or target_frames <= 0:
        return []

    ordered_scenes = sorted((dict(scene) for scene in scenes), key=lambda scene: scene["start"])
    average_scene_length = sum(int(scene["length"]) for scene in ordered_scenes) / len(ordered_scenes)
    priority_scores = _build_priority_scores(ordered_scenes)
    context_scores = _build_context_scores(priority_scores)
    seed_indices = _pick_seed_indices(
        priority_scores,
        target_frames=target_frames,
        average_scene_length=average_scene_length,
        score_threshold=score_threshold,
    )
    candidate_events = _merge_seed_windows(seed_indices, scene_count=len(ordered_scenes))

    if not candidate_events:
        return [_best_subsegment(ordered_scenes, context_scores, 0, len(ordered_scenes) - 1, target_frames)]

    ranked_events = []
    for start_idx, end_idx in candidate_events:
        event = _event_segment(ordered_scenes, start_idx, end_idx)
        event_value = sum(
            context_scores[idx] * int(ordered_scenes[idx]["length"])
            for idx in range(start_idx, end_idx + 1)
        )
        peak_value = max(priority_scores[start_idx:end_idx + 1])
        ranked_events.append(
            {
                "start_idx": start_idx,
                "end_idx": end_idx,
                "start": event["start"],
                "length": event["length"],
                "value": event_value,
                "peak": peak_value,
            }
        )

    ranked_events.sort(key=lambda event: (-event["value"], -event["peak"], event["start"]))

    selected_segments = []
    remaining_frames = int(target_frames)
    used_event_ranges = []

    for event in ranked_events:
        if remaining_frames <= 0:
            break

        take_frames = min(event["length"], remaining_frames)
        if take_frames == event["length"]:
            used_event_ranges.append((event["start_idx"], event["end_idx"]))

        selected_segments.append(
            _best_subsegment(
                ordered_scenes,
                context_scores,
                event["start_idx"],
                event["end_idx"],
                take_frames,
            )
        )
        remaining_frames -= take_frames

    if remaining_frames > 0:
        uncovered_ranges = _invert_ranges(used_event_ranges, scene_count=len(ordered_scenes))
        ranked_uncovered_ranges = []

        for start_idx, end_idx in uncovered_ranges:
            segment = _event_segment(ordered_scenes, start_idx, end_idx)
            range_value = sum(
                context_scores[idx] * int(ordered_scenes[idx]["length"])
                for idx in range(start_idx, end_idx + 1)
            )
            ranked_uncovered_ranges.append(
                {
                    "start_idx": start_idx,
                    "end_idx": end_idx,
                    "start": segment["start"],
                    "length": segment["length"],
                    "value": range_value,
                }
            )

        ranked_uncovered_ranges.sort(key=lambda item: (-item["value"], item["start"]))

        for available_range in ranked_uncovered_ranges:
            if remaining_frames <= 0:
                break

            take_frames = min(available_range["length"], remaining_frames)
            selected_segments.append(
                _best_subsegment(
                    ordered_scenes,
                    context_scores,
                    available_range["start_idx"],
                    available_range["end_idx"],
                    take_frames,
                )
            )
            remaining_frames -= take_frames

    return _merge_selected_segments(selected_segments)
