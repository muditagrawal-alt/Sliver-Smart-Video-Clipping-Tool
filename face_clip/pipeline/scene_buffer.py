class SceneBuffer:
    def __init__(self, fps, min_scene_sec=1.0):
        self.fps = fps
        self.min_frames = int(min_scene_sec * fps)
        self.reset()

    def reset(self):
        self.start = None
        self.length = 0
        self.score_sum = 0
        self.motion_sum = 0  # track motion for scene understanding

    def update(self, frame_idx, score, motion=0):
        """
        Update the buffer with a new frame.
        motion: float, optional motion value for this frame
        """
        if self.start is None:
            self.start = frame_idx

        self.length += 1
        self.score_sum += score
        self.motion_sum += motion

    def is_scene_complete(self):
        return self.length >= self.min_frames

    def has_data(self):
        return self.length > 0

    def flush(self):
        """
        Return a scene dict including average score and average motion.
        """
        scene = {
            "start": self.start,
            "length": self.length,
            "score": self.score_sum / max(1, self.length),
            "avg_motion": self.motion_sum / max(1, self.length)
        }
        self.reset()
        return scene