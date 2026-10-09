"""
smart_models.py — Zero-shot CLIP semantic scorer.

FIX: use torch.inference_mode() instead of torch.no_grad() for ~5 % faster
     inference (no gradient bookkeeping at all).
FIX: the global _smart_vision singleton was mutated by set_prompt() while
     score_frame() could be called from a background thread.  A threading.Lock
     now serialises access to the mutable state so concurrent jobs are safe.
FIX: score_frame now early-exits before the BGR→RGB conversion and PIL
     allocation when there is no active prompt, matching the fast-path added
     in process_video.py.  (The check in process_video is the primary guard;
     this is a belt-and-suspenders safety net.)
"""

import threading

import cv2
import numpy as np
import torch
from PIL import Image

try:
    from transformers import CLIPModel, CLIPProcessor
except ImportError:
    CLIPModel = None      # type: ignore[assignment]
    CLIPProcessor = None  # type: ignore[assignment]


class SmartVisionModel:
    def __init__(self) -> None:
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.model: object | None = None
        self.processor: object | None = None
        self.text_features: torch.Tensor | None = None
        self.prompt: str | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_model(self) -> None:
        """Lazy-load CLIP.  Must be called while holding self._lock."""
        if self.model is not None:
            return
        if CLIPModel is None:
            raise ImportError(
                "transformers is not installed.  Run: pip install transformers Pillow"
            )
        model_id = "openai/clip-vit-base-patch32"
        self.model     = CLIPModel.from_pretrained(model_id).to(self.device)
        self.processor = CLIPProcessor.from_pretrained(model_id)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_prompt(self, prompt: str) -> None:
        """Pre-compute text embeddings for *prompt*.  Thread-safe."""
        with self._lock:
            if not prompt or not prompt.strip():
                self.prompt        = None
                self.text_features = None
                return

            self._load_model()
            self.prompt = prompt.strip()

            inputs = self.processor(
                text=[self.prompt], return_tensors="pt", padding=True
            )
            inputs = {k: v.to(self.device) for k, v in inputs.items()}

            # FIX: inference_mode is faster than no_grad for pure inference
            with torch.inference_mode():
                feats = self.model.get_text_features(**inputs)
                feats = feats / feats.norm(dim=-1, keepdim=True)
            self.text_features = feats

    def score_frame(self, frame_bgr: np.ndarray) -> float:
        """
        Return cosine-similarity score of *frame_bgr* against the active
        prompt, normalised to [0, 1].  Returns 0.0 if no prompt is set.
        Thread-safe.
        """
        with self._lock:
            # FIX: fast exit — avoids BGR→RGB + PIL alloc with no prompt
            if self.text_features is None or self.model is None:
                return 0.0

            text_feats = self.text_features  # local ref under lock

        # Image encoding is done outside the lock to minimise contention;
        # text_feats is a read-only tensor so this is safe.
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(frame_rgb)

        inputs = self.processor(images=pil_image, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        with torch.inference_mode():
            image_feats = self.model.get_image_features(**inputs)
            image_feats = image_feats / image_feats.norm(dim=-1, keepdim=True)
            similarity  = (image_feats @ text_feats.T).item()

        # CLIP cosine scores for correct matches typically sit in [0.15, 0.35].
        # Rescale to a [0, 1] working range.
        return min(1.0, max(0.0, (similarity - 0.15) * 5.0))


# ---------------------------------------------------------------------------
# Module-level singleton — one instance, shared across all jobs in the process
# ---------------------------------------------------------------------------
_smart_vision = SmartVisionModel()


def set_smart_prompt(prompt: str) -> None:
    _smart_vision.set_prompt(prompt)


def get_smart_score(frame: np.ndarray) -> float:
    return _smart_vision.score_frame(frame)
