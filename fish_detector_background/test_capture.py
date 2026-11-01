"""Geometry and mocked capture checks, portable without a Windows desktop.
These test Python control flow, not real GDI/game rendering.
"""
import ctypes
from ctypes import wintypes
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
import numpy as np
from fish_on import WindowCapture, CaptureUnavailable, client_crop_box

ROI = (.22, .87, .43, .98)


class GeometryTests(unittest.TestCase):
    def test_full_window_includes_client_border_offset(self):
        self.assertEqual(client_crop_box((1366, 768), (100, 200, 1482, 1007),
                                        (108, 231), ROI, "window"),
                         (308, 699, 595, 783))

    def test_client_only_ignores_border_offset(self):
        self.assertEqual(client_crop_box((1366, 768), (100, 200, 1482, 1007),
                                        (108, 231), ROI, "client"),
                         (300, 668, 587, 752))

    def test_negative_monitor_coordinates(self):
        self.assertEqual(client_crop_box((1366, 768), (-1600, -100, -218, 707),
                                        (-1592, -69), ROI, "window"),
                         (308, 699, 595, 783))


class MockedCaptureTests(unittest.TestCase):
    def make_capture(self, mode="window", minimized=False, black=False, result=True):
        capture = WindowCapture.__new__(WindowCapture)
        capture.title, capture.mode, capture.wt = "game", mode, wintypes
        capture.hwnd = 123
        capture.dc = 456
        capture.pixels = None
        def get_client(hwnd, pointer):
            rect = pointer._obj
            rect.left, rect.top, rect.right, rect.bottom = 0, 0, 1366, 768
            return True
        def get_window(hwnd, pointer):
            rect = pointer._obj
            rect.left, rect.top, rect.right, rect.bottom = 100, 200, 1482, 1007
            return True
        def get_origin(hwnd, pointer):
            pointer._obj.x, pointer._obj.y = 108, 231
            return True
        def allocate(width, height):
            capture.pixels = np.full((height, width, 4), 255, dtype=np.uint8)
        def print_window(hwnd, dc, flags):
            # Every call must clear the reused buffer before rendering.
            self.assertEqual(capture.pixels.max(), 0)
            if not black:
                capture.pixels[:, :, :3] = (20, 30, 40)
            return result
        capture.user32 = SimpleNamespace(
            IsWindow=Mock(return_value=True), IsIconic=Mock(return_value=minimized),
            IsWindowVisible=Mock(return_value=True),
            GetClientRect=Mock(side_effect=get_client), GetWindowRect=Mock(side_effect=get_window),
            ClientToScreen=Mock(side_effect=get_origin), PrintWindow=Mock(side_effect=print_window))
        # No GetForegroundWindow exists on the mock: capture must never require focus.
        capture.gdi32 = SimpleNamespace(GdiFlush=Mock())
        capture._allocate = Mock(side_effect=allocate)
        return capture

    def test_window_mode_renders_without_foreground_check(self):
        capture = self.make_capture()
        image, width = capture.grab(ROI)
        self.assertEqual(width, 1366)
        self.assertEqual(image.shape, (84, 287, 3))
        self.assertTrue(np.all(image == np.array([20, 30, 40])))
        capture._allocate.assert_called_once_with(1382, 807)
        capture.user32.PrintWindow.assert_called_once_with(123, 456, 2)
        self.assertTrue(image.flags.c_contiguous)
        self.assertFalse(np.shares_memory(image, capture.pixels))

    def test_client_mode_uses_client_size_and_flags(self):
        capture = self.make_capture(mode="client")
        capture.grab(ROI)
        capture._allocate.assert_called_once_with(1366, 768)
        capture.user32.PrintWindow.assert_called_once_with(123, 456, 3)

    def test_minimized_skipped(self):
        capture = self.make_capture(minimized=True)
        with self.assertRaises(CaptureUnavailable):
            capture.grab(ROI)
        capture.user32.PrintWindow.assert_not_called()

    def test_black_frame_rejected(self):
        with self.assertRaisesRegex(CaptureUnavailable, "black HUD"):
            self.make_capture(black=True).grab(ROI)

    def test_failed_printwindow_rejected(self):
        with self.assertRaisesRegex(CaptureUnavailable, "PrintWindow failed"):
            self.make_capture(result=False).grab(ROI)


if __name__ == "__main__":
    unittest.main()
