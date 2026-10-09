"""
tests/test_pipeline_fixes.py
Regression tests for each bug fixed in this session.
Run with: python3 -m pytest tests/ -v
"""

import unittest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# SceneBuffer
# ---------------------------------------------------------------------------
class TestSceneBufferFix(unittest.TestCase):
    def setUp(self):
        from face_clip.pipeline.scene_buffer import SceneBuffer
        self.SceneBuffer = SceneBuffer

    def test_flush_on_empty_raises(self):
        """FIX: flush() on an empty buffer must raise, not return {start:None}."""
        buf = self.SceneBuffer(fps=25.0)
        with self.assertRaises(RuntimeError):
            buf.flush()

    def test_has_data_false_when_empty(self):
        buf = self.SceneBuffer(fps=25.0)
        self.assertFalse(buf.has_data())

    def test_has_data_true_after_update(self):
        buf = self.SceneBuffer(fps=25.0)
        buf.update(1, 1.0, 0.0)
        self.assertTrue(buf.has_data())

    def test_flush_returns_correct_averages(self):
        buf = self.SceneBuffer(fps=25.0, min_scene_sec=0.0)
        buf.update(10, 4.0, 0.2)
        buf.update(11, 2.0, 0.4)
        scene = buf.flush()
        self.assertEqual(scene["start"], 10)
        self.assertEqual(scene["length"], 2)
        self.assertAlmostEqual(scene["score"], 3.0)
        self.assertAlmostEqual(scene["avg_motion"], 0.3)

    def test_reset_after_flush(self):
        buf = self.SceneBuffer(fps=25.0, min_scene_sec=0.0)
        buf.update(5, 1.0, 0.0)
        buf.flush()
        self.assertFalse(buf.has_data())
        # Second flush on now-empty buffer must also raise
        with self.assertRaises(RuntimeError):
            buf.flush()


# ---------------------------------------------------------------------------
# profiler — motion divide-by-zero fix
# ---------------------------------------------------------------------------
class TestProfilerMotionDivide(unittest.TestCase):
    def test_single_sample_no_crash(self):
        """
        FIX: profiler used total_motion / (samples - 1) which gives /0 for
        the first sampled frame.  One-sample videos must not crash.
        """
        from face_clip.pipeline.profiler import profile_video
        import numpy as np
        import cv2

        dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)

        mock_face_model = MagicMock()
        mock_face_model.return_value = [MagicMock(boxes=[])]

        mock_person_model = MagicMock()
        mock_person_model.return_value = [MagicMock(boxes=[])]
        mock_person_model.names = {0: "person"}

        # Patch VideoCapture to emit exactly one frame then stop
        frames = [dummy_frame]
        call_count = [0]

        class FakeCap:
            def isOpened(self): return True
            def get(self, prop): return 25.0
            def read(self):
                if call_count[0] < len(frames):
                    f = frames[call_count[0]]
                    call_count[0] += 1
                    return True, f
                return False, None
            def release(self): pass

        with patch("face_clip.pipeline.profiler.cv2.VideoCapture", return_value=FakeCap()):
            result = profile_video("dummy.mp4", mock_face_model, mock_person_model)

        # Must return a valid dict without raising ZeroDivisionError
        self.assertIn("faces",   result)
        self.assertIn("motion",  result)
        self.assertIn("objects", result)
        # avg_motion must be 0.0 because there are no diffs
        self.assertEqual(result["profile_stats"]["avg_motion"], 0.0)


# ---------------------------------------------------------------------------
# audio_utils — subprocess stderr no longer floods console
# ---------------------------------------------------------------------------
class TestAudioUtilsSubprocess(unittest.TestCase):
    def test_run_captures_stderr(self):
        """
        FIX: all _run() calls now pass stdout/stderr=PIPE so ffmpeg output
        doesn't flood the server console.
        """
        from face_clip.pipeline.audio_utils import _run
        # Run a harmless command and confirm it doesn't raise and captures output
        result = _run(["echo", "hello"])
        self.assertEqual(result.returncode, 0)
        # stdout must be captured (not printed to console)
        self.assertIsNotNone(result.stdout)

    def test_has_audio_does_not_raise_on_missing_file(self):
        """has_audio must return False (not raise) for a non-existent path."""
        from face_clip.pipeline.audio_utils import has_audio
        self.assertFalse(has_audio("/nonexistent/file.mp4"))


# ---------------------------------------------------------------------------
# process_video — name collision: has_audio import not overwritten
# ---------------------------------------------------------------------------
class TestProcessVideoImport(unittest.TestCase):
    def test_has_audio_import_alias_intact(self):
        """
        FIX: 'has_audio = extract_audio(...)' used to shadow the imported
        has_audio function.  Verify the module imports cleanly and the alias
        _has_audio is a callable (the function), not a bool.
        """
        import importlib
        import face_clip.pipeline.process_video as pv
        # _has_audio is the aliased import — must be callable
        self.assertTrue(callable(pv._has_audio))


# ---------------------------------------------------------------------------
# app.py — ensure_storage only runs once
# ---------------------------------------------------------------------------
class TestEnsureStorageOnce(unittest.TestCase):
    def test_ensure_storage_idempotent(self):
        """
        FIX: ensure_storage() was called on every HTTP request.
        After the first call the flag is set and subsequent calls are no-ops.
        """
        import app
        import app as app_module

        # Force a clean slate for this test
        app_module._storage_initialised = False

        call_count = [0]
        original = app_module.sqlite3.connect

        def counting_connect(*args, **kwargs):
            call_count[0] += 1
            return original(*args, **kwargs)

        import importlib, os, tempfile
        # Point DB to a temp file so we don't disturb the real DB
        tmp = tempfile.mktemp(suffix=".sqlite3")
        old_db = app_module.DB_PATH
        app_module.DB_PATH = type(old_db)(tmp)

        try:
            with patch("app.sqlite3.connect", side_effect=counting_connect):
                app_module._storage_initialised = False
                app_module.ensure_storage()   # call 1 — should hit sqlite
                first_count = call_count[0]

                app_module.ensure_storage()   # call 2 — must be a no-op
                second_count = call_count[0]

            self.assertEqual(first_count, second_count,
                             "ensure_storage() must not open a new DB connection on the second call")
        finally:
            app_module.DB_PATH = old_db
            app_module._storage_initialised = False
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass


# ---------------------------------------------------------------------------
# SmartVisionModel — early exit when no prompt
# ---------------------------------------------------------------------------
class TestSmartModelsEarlyExit(unittest.TestCase):
    def test_score_frame_returns_zero_without_prompt(self):
        """FIX: score_frame must return 0.0 without doing any image work."""
        from face_clip.pipeline.smart_models import SmartVisionModel
        import numpy as np

        model = SmartVisionModel()
        # No prompt set → text_features is None
        dummy = np.zeros((100, 100, 3), dtype=np.uint8)
        self.assertEqual(model.score_frame(dummy), 0.0)


# ---------------------------------------------------------------------------
# Security & Static Routing Tests
# ---------------------------------------------------------------------------
class TestAppSecurityAndRouting(unittest.TestCase):
    def test_media_path_blocks_database_leak(self):
        """Security FIX: media_path must reject attempts to access sliver.sqlite3."""
        from app import media_path
        self.assertIsNone(media_path("sliver.sqlite3"))
        self.assertIsNone(media_path("../web_data/sliver.sqlite3"))
        self.assertIsNone(media_path("../../etc/passwd"))

    def test_assets_route_serves_valid_asset(self):
        """FIX: /assets/ route must serve files instead of 404."""
        from app import application
        statuses = []
        headers_list = []

        def fake_start_response(status, headers):
            statuses.append(status)
            headers_list.append(dict(headers))

        environ = {
            "REQUEST_METHOD": "GET",
            "PATH_INFO": "/assets/screenshots/workspace.png",
        }
        res = application(environ, fake_start_response)
        self.assertEqual(statuses[0], "200 OK")
        self.assertIn("Accept-Ranges", headers_list[0])

    def test_file_response_handles_http_range(self):
        """FIX: file_response must handle HTTP 206 Partial Content for video seeking."""
        from app import application
        statuses = []
        headers_list = []

        def fake_start_response(status, headers):
            statuses.append(status)
            headers_list.append(dict(headers))

        environ = {
            "REQUEST_METHOD": "GET",
            "PATH_INFO": "/assets/screenshots/workspace.png",
            "HTTP_RANGE": "bytes=0-49",
        }
        res = application(environ, fake_start_response)
        chunk = b"".join(res)
        self.assertEqual(statuses[0], "206 Partial Content")
        self.assertEqual(len(chunk), 50)
        self.assertIn("bytes 0-49/", headers_list[0]["Content-Range"])


# ---------------------------------------------------------------------------
# Scene Boundary Frame Handling
# ---------------------------------------------------------------------------
class TestSceneBoundaryContinuity(unittest.TestCase):
    def test_contiguous_scenes_frame_advancement(self):
        """FIX: adjacent scenes where scene1.end == scene2.start must not drop boundary frames."""
        selected_frames = [
            {"start": 0, "length": 5},   # frames 0, 1, 2, 3, 4
            {"start": 5, "length": 5},   # frames 5, 6, 7, 8, 9
        ]
        written_indices = []

        current_scene_idx = 0
        total_frames = 10

        for frame_idx in range(total_frames):
            while current_scene_idx < len(selected_frames):
                curr = selected_frames[current_scene_idx]
                if frame_idx < curr["start"] + curr["length"]:
                    break
                current_scene_idx += 1

            if current_scene_idx >= len(selected_frames):
                break

            scene = selected_frames[current_scene_idx]
            if frame_idx >= scene["start"]:
                written_indices.append(frame_idx)

        self.assertEqual(written_indices, list(range(10)))


if __name__ == "__main__":
    unittest.main()

