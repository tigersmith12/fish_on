"""Fish HUD notifier. Windows live capture; portable --test screenshot mode."""
from __future__ import annotations

import argparse
import ctypes
from dataclasses import dataclass
import logging
from pathlib import Path
import sys
import threading
import time

BASE = Path(__file__).resolve().parent
LOG = logging.getLogger("fish_on")


def enable_dpi_awareness():
    # Run BEFORE importing capture/UI packages. All coordinates are physical pixels.
    if sys.platform != "win32":
        return
    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        ctypes.windll.user32.SetProcessDPIAware()


@dataclass
class Match:
    score: float
    box: tuple[int, int, int, int]  # relative to captured search region
    template: str


def roi_pixels(width, height, fractions):
    x1, y1, x2, y2 = fractions
    return (int(width * x1), int(height * y1),
            min(width, int(width * x2)), min(height, int(height * y2)))


class Detector:
    def __init__(self, folder):
        import cv2
        self.cv2 = cv2
        self.originals = []
        for name, native_width in [("match_item_1366x768.png", 1366),
                                   ("match_item_1600x900.png", 1600),
                                   ("match_item_1920x1080.png", 1920)]:
            path = folder / name
            if path.exists():
                image = cv2.imread(str(path), cv2.IMREAD_COLOR)
                if image is not None and image.std() > 1:
                    self.originals.append((name, native_width, image))
        if not self.originals:
            path = folder / "match_item.png"
            image = cv2.imread(str(path), cv2.IMREAD_COLOR) if path.exists() else None
            if image is None or image.std() <= 1:
                raise ValueError(f"No usable fish templates in {folder}")
            self.originals.append((path.name, 1366, image))
        self.cached_width = None
        self.templates = []

    def prepare(self, client_width):
        if self.cached_width == client_width:
            return
        self.templates = []
        for name, native_width, image in self.originals:
            h, w = image.shape[:2]
            sizes = set()
            # Include original HUD size as well as proportional UI scaling.
            for factor in (1.0, client_width / native_width):
                for adjustment in (0.9, 1.0, 1.1):
                    size = (max(8, round(w * factor * adjustment)),
                            max(8, round(h * factor * adjustment)))
                    if size in sizes:
                        continue
                    sizes.add(size)
                    template = self.cv2.resize(image, size, interpolation=(
                        self.cv2.INTER_AREA if size[0] < w else self.cv2.INTER_LINEAR))
                    self.templates.append((name, template))
        self.cached_width = client_width

    def find(self, region, client_width):
        self.prepare(client_width)
        best = Match(-1.0, (0, 0, 0, 0), "none")
        height, width = region.shape[:2]
        for name, template in self.templates:
            h, w = template.shape[:2]
            if h > height or w > width:
                continue
            result = self.cv2.matchTemplate(region, template, self.cv2.TM_CCOEFF_NORMED)
            _, score, _, (x, y) = self.cv2.minMaxLoc(result)
            if score > best.score:
                best = Match(float(score), (x, y, x + w, y + h), name)
        return best


def annotate(image, match, search_box, threshold):
    import cv2
    output = image.copy()
    left, top, right, bottom = search_box
    cv2.rectangle(output, (left, top), (right - 1, bottom - 1), (255, 200, 0), 2)
    x1, y1, x2, y2 = match.box
    color = (0, 230, 0) if match.score >= threshold else (0, 0, 255)
    cv2.rectangle(output, (left + x1, top + y1), (left + x2 - 1, top + y2 - 1), color, 2)
    label = f"Fish score {match.score:.3f} | threshold {threshold:.2f}"
    cv2.putText(output, label, (max(4, left), max(22, top - 10)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
    return output


class CaptureUnavailable(Exception):
    pass


def client_crop_box(client_size, window_rect, client_origin, fractions, mode):
    """Translate a client-relative search box into PrintWindow bitmap pixels."""
    width, height = client_size
    left, top, right, bottom = roi_pixels(width, height, fractions)
    if mode == "window":
        dx = client_origin[0] - window_rect[0]
        dy = client_origin[1] - window_rect[1]
        left, right = left + dx, right + dx
        top, bottom = top + dy, bottom + dy
    return left, top, right, bottom


class WindowCapture:
    """Reusable top-down GDI bitmap populated by PrintWindow, not desktop pixels."""
    def __init__(self, title, mode="window"):
        from ctypes import wintypes as wt
        self.title, self.mode, self.wt = title, mode, wt
        self.hwnd = None
        self.dc = self.bitmap = self.old_bitmap = None
        self.pixels = None
        self.size = None
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG),
                        ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                        ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                        ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                        ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                        ("biClrImportant", wt.DWORD)]

        class BITMAPINFO(ctypes.Structure):
            _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 1)]

        self.BitmapInfo = BITMAPINFO
        self.BitmapHeader = BITMAPINFOHEADER
        # Explicit pointer-sized signatures are required on 64-bit Windows.
        bindings = [
            (self.user32, "FindWindowW", [wt.LPCWSTR, wt.LPCWSTR], wt.HWND),
            (self.user32, "GetClientRect", [wt.HWND, ctypes.POINTER(wt.RECT)], wt.BOOL),
            (self.user32, "GetWindowRect", [wt.HWND, ctypes.POINTER(wt.RECT)], wt.BOOL),
            (self.user32, "ClientToScreen", [wt.HWND, ctypes.POINTER(wt.POINT)], wt.BOOL),
            (self.user32, "GetWindowDC", [wt.HWND], wt.HDC),
            (self.user32, "ReleaseDC", [wt.HWND, wt.HDC], ctypes.c_int),
            (self.user32, "PrintWindow", [wt.HWND, wt.HDC, wt.UINT], wt.BOOL),
            (self.gdi32, "CreateCompatibleDC", [wt.HDC], wt.HDC),
            (self.gdi32, "CreateDIBSection", [wt.HDC, ctypes.POINTER(BITMAPINFO),
                wt.UINT, ctypes.POINTER(ctypes.c_void_p), wt.HANDLE, wt.DWORD], wt.HANDLE),
            (self.gdi32, "SelectObject", [wt.HDC, wt.HANDLE], wt.HANDLE),
            (self.gdi32, "DeleteObject", [wt.HANDLE], wt.BOOL),
            (self.gdi32, "DeleteDC", [wt.HDC], wt.BOOL),
            (self.gdi32, "GdiFlush", [], wt.BOOL),
        ]
        for lib, name, argtypes, restype in bindings:
            function = getattr(lib, name)
            function.argtypes, function.restype = argtypes, restype
        for name in ("IsWindow", "IsIconic", "IsWindowVisible"):
            function = getattr(self.user32, name)
            function.argtypes, function.restype = [wt.HWND], wt.BOOL

    def _allocate(self, width, height):
        import numpy as np
        if self.size == (width, height):
            return
        self.close()
        source = self.user32.GetWindowDC(self.hwnd)
        if not source:
            raise CaptureUnavailable("Cannot acquire game window DC")
        try:
            self.dc = self.gdi32.CreateCompatibleDC(source)
            if not self.dc:
                raise CaptureUnavailable("Cannot allocate capture DC")
            info = self.BitmapInfo()
            info.bmiHeader.biSize = ctypes.sizeof(self.BitmapHeader)
            info.bmiHeader.biWidth = width
            info.bmiHeader.biHeight = -height  # Top-down rows, no vertical flip needed.
            info.bmiHeader.biPlanes = 1
            info.bmiHeader.biBitCount = 32
            info.bmiHeader.biCompression = 0  # BI_RGB
            bits = ctypes.c_void_p()
            self.bitmap = self.gdi32.CreateDIBSection(source, ctypes.byref(info), 0,
                                                    ctypes.byref(bits), None, 0)
            if not self.bitmap or not bits.value:
                raise CaptureUnavailable("Cannot allocate capture bitmap")
            self.old_bitmap = self.gdi32.SelectObject(self.dc, self.bitmap)
            if not self.old_bitmap or self.old_bitmap == ctypes.c_void_p(-1).value:
                self.old_bitmap = None
                raise CaptureUnavailable("Cannot select capture bitmap")
            self.buffer = (ctypes.c_ubyte * (width * height * 4)).from_address(bits.value)
            self.pixels = np.ctypeslib.as_array(self.buffer).reshape(height, width, 4)
            self.size = (width, height)
        except Exception:
            self.close()
            raise
        finally:
            self.user32.ReleaseDC(self.hwnd, source)

    def grab(self, fractions):
        import numpy as np
        u = self.user32
        if not self.hwnd or not u.IsWindow(self.hwnd):
            self.close()
            self.hwnd = u.FindWindowW(None, self.title)
        if not self.hwnd:
            raise CaptureUnavailable(f'Window "{self.title}" not found')
        if u.IsIconic(self.hwnd) or not u.IsWindowVisible(self.hwnd):
            raise CaptureUnavailable("Game is minimized or hidden; leave it restored (covered is OK)")
        client, window, origin = self.wt.RECT(), self.wt.RECT(), self.wt.POINT(0, 0)
        if (not u.GetClientRect(self.hwnd, ctypes.byref(client)) or
                not u.GetWindowRect(self.hwnd, ctypes.byref(window)) or
                not u.ClientToScreen(self.hwnd, ctypes.byref(origin))):
            raise CaptureUnavailable("Cannot read game window/client geometry")
        width, height = client.right - client.left, client.bottom - client.top
        window_box = (window.left, window.top, window.right, window.bottom)
        capture_width, capture_height = ((window.right - window.left, window.bottom - window.top)
                                         if self.mode == "window" else (width, height))
        if min(width, height, capture_width, capture_height) < 100:
            raise CaptureUnavailable("Game window/client too small")
        self._allocate(capture_width, capture_height)
        # Clear first so an incomplete render cannot reuse our previous frame.
        self.pixels.fill(0)
        # 2 matches the old script; 3 adds PW_CLIENTONLY for optional client mode.
        flags = 2 if self.mode == "window" else 3
        if not u.PrintWindow(self.hwnd, self.dc, flags):
            raise CaptureUnavailable(f"PrintWindow failed (flags={flags}); try the other --printwindow-mode")
        self.gdi32.GdiFlush()
        box = client_crop_box((width, height), window_box, (origin.x, origin.y), fractions, self.mode)
        left, top, right, bottom = box
        if not (0 <= left < right <= capture_width and 0 <= top < bottom <= capture_height):
            raise CaptureUnavailable("Client crop is outside capture bitmap; try --printwindow-mode client")
        # Only the search region is copied into BGR; the full bitmap stays in memory.
        region = np.ascontiguousarray(self.pixels[top:bottom, left:right, :3])
        if int(region.max()) < 3:
            raise CaptureUnavailable("PrintWindow returned a black HUD; try the other mode or borderless/windowed game")
        return region, width

    def close(self):
        self.pixels = None
        self.buffer = None
        if self.dc and self.old_bitmap:
            self.gdi32.SelectObject(self.dc, self.old_bitmap)
        if self.bitmap:
            self.gdi32.DeleteObject(self.bitmap)
        if self.dc:
            self.gdi32.DeleteDC(self.dc)
        self.dc = self.bitmap = self.old_bitmap = None
        self.size = None

class Alert:
    def __init__(self, sound):
        self.sound = None
        self.pygame = None
        if sound.is_file():
            try:
                import pygame
                pygame.mixer.init()
                self.pygame = pygame
                self.sound = pygame.mixer.Sound(str(sound))
            except Exception as error:
                LOG.warning("Sound unavailable (%s); using Windows beep", error)
        else:
            LOG.info("No WAV supplied; using Windows notification beep")

    def play(self):
        if self.sound is not None:
            self.sound.play()  # Non-blocking: detector keeps running.
        else:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONASTERISK)

    def close(self):
        if self.pygame is not None:
            self.pygame.mixer.quit()


class Presence:
    """Debounce both transitions and use hysteresis to avoid repeat alerts."""
    def __init__(self, threshold, clear_threshold, on_frames=2, off_frames=3):
        self.threshold, self.clear_threshold = threshold, clear_threshold
        self.on_frames, self.off_frames = on_frames, off_frames
        self.active = False
        self.reset_counts()

    def reset_counts(self):
        self.hits = self.misses = 0

    def update(self, score):
        self.hits = self.hits + 1 if score >= self.threshold else 0
        self.misses = self.misses + 1 if score < self.clear_threshold else 0
        if not self.active and self.hits >= self.on_frames:
            self.active = True
            self.reset_counts()
            return "appeared"
        if self.active and self.misses >= self.off_frames:
            self.active = False
            self.reset_counts()
            return "disappeared"
        return None


def worker(args, detector, stop, enabled, debug):
    capture = alert = None
    presence = Presence(args.threshold, args.clear_threshold)
    last_log = 0.0
    try:
        capture = WindowCapture(args.title, args.printwindow_mode)
        alert = Alert(args.sound)
        LOG.info("Capture: PrintWindow (%s mode), covered/unfocused window allowed", args.printwindow_mode)
        while not stop.is_set():
            start = time.monotonic()
            if not enabled.is_set():
                presence.reset_counts()
                stop.wait(0.1)
                continue
            try:
                region, width = capture.grab(args.roi)
                match = detector.find(region, width)
                transition = presence.update(match.score)
                if transition == "appeared":
                    LOG.info("Fish detected: score %.3f, region-local box %s", match.score, match.box)
                    alert.play()
                elif transition == "disappeared":
                    LOG.info("Fish disappeared; alert rearmed")
                if debug.is_set():
                    h, w = region.shape[:2]
                    path = BASE / "live_debug.png"
                    if not detector.cv2.imwrite(str(path), annotate(region, match, (0, 0, w, h), args.threshold)):
                        raise OSError(f"Could not save {path}")
                    LOG.info("Saved %s (search region only)", path)
                    debug.clear()
                if time.monotonic() - last_log >= 5:
                    LOG.info("Score %.3f | fish present: %s", match.score, presence.active)
                    last_log = time.monotonic()
            except Exception as error:
                presence.reset_counts()
                if time.monotonic() - last_log >= 5:
                    LOG.warning("%s", error)
                    last_log = time.monotonic()
            stop.wait(max(0.01, args.interval - (time.monotonic() - start)))
    except Exception:
        LOG.exception("Detector stopped; check dependencies and capture setup")
        stop.set()
    finally:
        if capture is not None:
            capture.close()
        if alert is not None:
            alert.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", type=Path, help="Analyze a saved screenshot; no Windows/audio/tray needed")
    parser.add_argument("--output", type=Path, default=BASE / "debug_match.png")
    parser.add_argument("--templates", type=Path, default=BASE / "pictures")
    parser.add_argument("--title", default="Russian Fishing 4", help="Exact game window title")
    parser.add_argument("--sound", type=Path, default=BASE / "stardew-fishing_EimR00g.wav")
    parser.add_argument("--roi", nargs=4, type=float, default=(0.22, 0.87, 0.43, 0.98),
                        metavar=("LEFT", "TOP", "RIGHT", "BOTTOM"), help="Client-relative fractions (0..1)")
    parser.add_argument("--threshold", type=float, default=0.80)
    parser.add_argument("--clear-threshold", type=float, default=0.65)
    parser.add_argument("--interval", type=float, default=0.20)
    parser.add_argument("--printwindow-mode", choices=("window", "client"), default="window",
                        help="window: old PrintWindow flags=2 with client-offset crop (default); client: flags=3")
    parser.add_argument("--allow-background", action="store_true",
                        help="Compatibility flag; background capture is now enabled by default")
    parser.add_argument("--no-tray", action="store_true", help="Console only; Ctrl+C exits")
    args = parser.parse_args()
    x1, y1, x2, y2 = args.roi
    if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
        parser.error("ROI must have 0 <= left < right <= 1 and 0 <= top < bottom <= 1")
    if not (0 <= args.clear_threshold < args.threshold <= 1) or args.interval <= 0:
        parser.error("Require 0 <= clear-threshold < threshold <= 1 and interval > 0")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s", datefmt="%H:%M:%S")
    enable_dpi_awareness()
    detector = Detector(args.templates)
    if args.test:
        image = detector.cv2.imread(str(args.test), detector.cv2.IMREAD_COLOR)
        if image is None:
            parser.error(f"Cannot read screenshot {args.test}")
        height, width = image.shape[:2]
        box = roi_pixels(width, height, args.roi)
        left, top, right, bottom = box
        match = detector.find(image[top:bottom, left:right], width)
        absolute = tuple(v + (left if i % 2 == 0 else top) for i, v in enumerate(match.box))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if not detector.cv2.imwrite(str(args.output), annotate(image, match, box, args.threshold)):
            parser.error(f"Cannot write {args.output}")
        print(f"Screenshot: {width}x{height}\nSearch box: {box}\nScore: {match.score:.4f}")
        print(f"Match box: {absolute}\nTemplate: {match.template}\nDebug image: {args.output}")
        print("Single-frame result:", "MATCH" if match.score >= args.threshold else "NO MATCH")
        return 0 if match.score >= args.threshold else 1
    if sys.platform != "win32":
        parser.error("Live capture requires Windows; use --test for screenshots")
    stop, enabled, debug = threading.Event(), threading.Event(), threading.Event()
    enabled.set()
    debug.set()  # Save one initial ROI to help confirm positioning.
    tray = None
    if not args.no_tray:
        from PIL import Image
        import pystray

        def toggle(icon, menu_item):
            if enabled.is_set():
                enabled.clear()
            else:
                enabled.set()
            icon.update_menu()

        def quit_app(icon, menu_item):
            stop.set()
            icon.stop()

        icon_image = Image.open(args.templates / detector.originals[0][0]).convert("RGBA")
        tray = pystray.Icon("fish_on", icon_image, "Fish On", menu=pystray.Menu(
            pystray.MenuItem("Capture enabled", toggle, checked=lambda _: enabled.is_set()),
            pystray.MenuItem("Save debug image", lambda icon, item: debug.set()),
            pystray.MenuItem("Exit", quit_app)))
    thread = threading.Thread(target=worker, args=(args, detector, stop, enabled, debug), daemon=True)
    thread.start()
    try:
        if tray is not None:
            # Stop tray automatically if the worker cannot initialize.
            def watch():
                stop.wait()
                tray.stop()
            def setup(icon):
                icon.visible = True
                threading.Thread(target=watch, daemon=True).start()
            tray.run(setup=setup)
        else:
            while not stop.wait(0.5):
                pass
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        if tray is not None:
            tray.stop()
        thread.join(timeout=3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
