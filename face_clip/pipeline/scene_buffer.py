class SceneBuffer:
    """
    Accumulates frames into scenes of at least `min_scene_sec` duration.

    FIX: flush() now guards against being called on an empty buffer
         (start=None) which would produce {"start": None, ...} and crash
         downstream int() conversions.
    """

    def __init__(self, fps: float, min_scene_sec: float = 1.0) -> None:
        self.fps = fps
        self.min_frames = max(1, int(min_scene_sec * fps))
        self._reset()

    def _reset(self) -> None:
        self.start: int | None = None
        self.length: int = 0
        self.score_sum: float = 0.0
        self.motion_sum: float = 0.0

    def update(self, frame_idx: int, score: float, motion: float = 0.0) -> None:
        if self.start is None:
            self.start = frame_idx
        self.length     += 1
        self.score_sum  += score
        self.motion_sum += motion

    def is_scene_complete(self) -> bool:
        return self.length >= self.min_frames

    def has_data(self) -> bool:
        return self.length > 0

    def flush(self) -> dict:
        """
        Return a scene dict and reset the buffer.

        FIX: raises RuntimeError instead of silently returning
             {"start": None, ...} when called on an empty buffer.
        """
        if self.start is None:
            raise RuntimeError("SceneBuffer.flush() called on an empty buffer")

        scene = {
            "start":      self.start,
            "length":     self.length,
            "score":      self.score_sum / self.length,
            "avg_motion": self.motion_sum / self.length,
        }
        self._reset()
        return scene

    def __repr__(self) -> str:
        return (
            f"SceneBuffer(start={self.start}, length={self.length}, "
            f"score_avg={self.score_sum / max(1, self.length):.3f})"
        )
