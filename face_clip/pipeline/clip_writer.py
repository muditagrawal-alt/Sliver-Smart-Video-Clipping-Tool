import cv2
from pathlib import Path

class ClipWriter:
    def __init__(self, output_path: str, fps: float, frame_size: tuple):
        # Store output path (needed by process_video)
        self.output_path = output_path

        # Ensure output directory exists
        output_dir = Path(output_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)

        self.frame_size = frame_size
        self.fps = fps

        # mp4v is stable on macOS + browsers
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")

        self.writer = cv2.VideoWriter(
            output_path,
            fourcc,
            fps,
            frame_size,
        )

        if not self.writer.isOpened():
            raise RuntimeError(f"Failed to initialize VideoWriter: {output_path}")

    def write(self, frame):
        # ✅ DO NOT resize
        # Assume frame already matches input resolution
        self.writer.write(frame)

    def close(self):
        self.writer.release()