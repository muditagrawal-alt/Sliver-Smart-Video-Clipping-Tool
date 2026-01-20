from deep_sort_realtime.deepsort_tracker import DeepSort


class Tracker:
    def __init__(
        self,
        max_age=30,
        n_init=3,
        max_iou_distance=0.7,
    ):
        self.tracker = DeepSort(
            max_age=max_age,
            n_init=n_init,
            max_iou_distance=max_iou_distance,
        )

    def update(self, detections, frame):
        """
        detections: list of [x1, y1, x2, y2, confidence, class_id]
        frame: original frame (required by DeepSORT)
        """
        tracks = self.tracker.update_tracks(detections, frame=frame)
        return tracks