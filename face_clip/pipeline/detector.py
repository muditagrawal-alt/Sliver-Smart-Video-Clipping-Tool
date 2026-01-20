from ultralytics import YOLO


class Detector:
    def __init__(self, face_model_path: str, object_model_path: str, device="cpu"):
        self.face_model = YOLO(face_model_path)
        self.object_model = YOLO(object_model_path)

        # Force device (cpu / mps / cuda)
        self.face_model.to(device)
        self.object_model.to(device)

    def detect_faces(self, frame):
        """
        Returns Ultralytics Results object
        """
        return self.face_model(frame, verbose=False)[0]

    def detect_objects(self, frame):
        """
        Returns Ultralytics Results object
        """
        return self.object_model(frame, verbose=False)[0]