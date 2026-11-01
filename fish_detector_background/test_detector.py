"""Run with: python -m unittest -v"""
import unittest
import numpy as np
from fish_on import BASE, Detector, Presence, roi_pixels


class DetectorTests(unittest.TestCase):
    def test_relative_roi(self):
        self.assertEqual(roi_pixels(1366, 768, (.22, .87, .43, .98)), (300, 668, 587, 752))

    def test_exact_template_at_different_positions(self):
        detector = Detector(BASE / "pictures")
        name, _, template = detector.originals[0]
        h, w = template.shape[:2]
        for x, y in [(10, 10), (120, 40)]:
            region = np.full((85, 290, 3), 40, dtype=np.uint8)
            region[y:y+h, x:x+w] = template
            match = detector.find(region, 1366)
            self.assertGreater(match.score, .99)
            self.assertEqual(match.box, (x, y, x+w, y+h))

    def test_empty_region_not_detected(self):
        detector = Detector(BASE / "pictures")
        match = detector.find(np.full((85, 290, 3), 40, dtype=np.uint8), 1366)
        self.assertLess(match.score, .80)

    def test_too_small_region_does_not_crash(self):
        detector = Detector(BASE / "pictures")
        self.assertEqual(detector.find(np.zeros((4, 4, 3), dtype=np.uint8), 1366).score, -1)

    def test_debounce_and_hysteresis(self):
        state = Presence(.8, .65)
        self.assertIsNone(state.update(.9))
        self.assertIsNone(state.update(.6))  # One-frame false detection rejected.
        self.assertIsNone(state.update(.9))
        self.assertEqual(state.update(.9), "appeared")
        for score in [.9, .95, .7, .6, .7]:
            self.assertIsNone(state.update(score))  # No repeat alert; one miss is insufficient.
        self.assertIsNone(state.update(.5))
        self.assertIsNone(state.update(.5))
        self.assertEqual(state.update(.5), "disappeared")
        self.assertIsNone(state.update(.9))
        self.assertEqual(state.update(.9), "appeared")


if __name__ == "__main__":
    unittest.main()
