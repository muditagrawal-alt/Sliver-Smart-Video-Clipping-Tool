import unittest

from face_clip.pipeline.scene_understanding import select_scenes


def make_scene(start, score, length=10, dominant_entity="side", avg_motion=0.0):
    return {
        "start": start,
        "length": length,
        "score": score,
        "dominant_entity": dominant_entity,
        "avg_motion": avg_motion,
    }


class SelectScenesTests(unittest.TestCase):
    def test_select_scenes_keeps_multiple_separate_highlights_with_context(self):
        scenes = [
            make_scene(0, 0.0),
            make_scene(10, 4.0),
            make_scene(20, 0.0),
            make_scene(30, 0.0),
            make_scene(40, 0.0),
            make_scene(50, 0.0),
            make_scene(60, 4.0, dominant_entity="hero"),
            make_scene(70, 0.0),
        ]

        selected = select_scenes(scenes, target_frames=60, score_threshold=2.5)

        self.assertEqual(
            selected,
            [
                {"start": 0, "length": 30},
                {"start": 50, "length": 30},
            ],
        )

    def test_select_scenes_returns_full_video_when_target_is_longer(self):
        scenes = [
            make_scene(0, 1.0),
            make_scene(10, 2.0),
            make_scene(20, 1.5),
        ]

        selected = select_scenes(scenes, target_frames=50, score_threshold=2.5)

        self.assertEqual(selected, [{"start": 0, "length": 30}])

    def test_select_scenes_fills_remaining_budget_without_reusing_segments(self):
        scenes = [
            make_scene(0, 0.0),
            make_scene(10, 4.0),
            make_scene(20, 0.0),
            make_scene(30, 0.5),
            make_scene(40, 0.5),
            make_scene(50, 0.5),
            make_scene(60, 0.5),
            make_scene(70, 0.0),
            make_scene(80, 4.0),
            make_scene(90, 0.0),
        ]

        selected = select_scenes(scenes, target_frames=80, score_threshold=2.5)

        self.assertEqual(sum(segment["length"] for segment in selected), 80)
        self.assertTrue(all(segment["length"] > 0 for segment in selected))


if __name__ == "__main__":
    unittest.main()
