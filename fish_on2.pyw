# fish_on.py
# Combines screenshot, image comparison, and sound playback with multi-resolution profiles.

import time
import os
import threading
from PIL import Image, ImageDraw
from pystray import MenuItem as item
import pystray
import cv2
from skimage.metrics import structural_similarity as ssim
import pygame
from ctypes import windll

# Force Windows to use true physical pixels instead of DPI-scaled virtual pixels
try:
    windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        windll.user32.SetProcessDPIAware()
    except Exception:
        pass

try:
    import win32gui
    import win32ui
    import win32con
except ImportError:
    print("---")
    print("IMPORTANT: This script requires the pywin32 library.")
    print("Please run the following command in your terminal:")
    print("pip install pywin32")
    print("---")
    exit()

# --- Configuration & Resolution Profiles ---
script_dir = os.path.dirname(os.path.abspath(__file__))
CROPPED_PATH = os.path.join(script_dir, 'pictures', 'cropped_region.png')
SOUND_PATH = os.path.join(script_dir, 'stardew-fishing_EimR00g.wav')
WINDOW_TITLE = "Russian Fishing 4"
ICON_PATH = os.path.join(script_dir, "pictures", "match_item_1920x1080.png") 

# Map each resolution to its specific crop box and corresponding reference image
RESOLUTION_PROFILES = {
    (1920, 1080): {
        "crop_rect": (635, 1022, 668, 1054),
        "match_image": os.path.join(script_dir, 'pictures', 'match_item_1920x1080.png')
    },
    (1600, 900): {
        "crop_rect": (477, 843, 505, 872),
        "match_image": os.path.join(script_dir, 'pictures', 'match_item_1600x900.png')
    },
    (1366, 768): {
        "crop_rect": (360, 711, 389, 740),
        "match_image": os.path.join(script_dir, 'pictures', 'match_item_1366x768.png')
    }
}

DEFAULT_RES = (1920, 1080)
SLEEP_INTERVAL = 0.5
MATCH_THRESHOLD = 0.45
DISAPPEAR_THRESHOLD = 0.25

# --- State ---
capturing = True
is_match_detected = False

# --- Functions ---

def take_screenshot_window():
    """
    Takes a screenshot of the game window, dynamically picks the crop rect 
    based on current resolution width/height, and saves it.
    """
    try:
        hwnd = win32gui.FindWindow(None, WINDOW_TITLE)
        if hwnd == 0:
            print(f'Window "{WINDOW_TITLE}" not found.')
            return False

        left, top, right, bot = win32gui.GetClientRect(hwnd)
        width = right - left
        height = bot - top

        current_res = (width, height)
        profile = RESOLUTION_PROFILES.get(current_res, RESOLUTION_PROFILES[DEFAULT_RES])
        crop_rect = profile["crop_rect"]

        hwndDC = win32gui.GetWindowDC(hwnd)
        mfcDC  = win32ui.CreateDCFromHandle(hwndDC)
        saveDC = mfcDC.CreateCompatibleDC()

        saveBitMap = win32ui.CreateBitmap()
        saveBitMap.CreateCompatibleBitmap(mfcDC, width, height)
        saveDC.SelectObject(saveBitMap)

        result = windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 2)

        bmpinfo = saveBitMap.GetInfo()
        bmpstr = saveBitMap.GetBitmapBits(True)

        im = Image.frombuffer(
            'RGB',
            (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
            bmpstr, 'raw', 'BGRX', 0, 1)

        win32gui.DeleteObject(saveBitMap.GetHandle())
        saveDC.DeleteDC()
        mfcDC.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwndDC)

        if result == 1:
            cropped_im = im.crop(crop_rect)
            cropped_im.save(CROPPED_PATH)
            return True
        else:
            print(f"Failed to capture window content for '{WINDOW_TITLE}'.")
            return False

    except win32ui.error as e:
        print(f"An error occurred with the win32 API: {e}")
        return False
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return False

def get_ssim_score(img1_path, img2_path):
    """Computes the SSIM score between two images."""
    try:
        img1 = cv2.imread(img1_path)
        img2 = cv2.imread(img2_path)

        if img1 is None or img2 is None:
            return 0.0

        gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)

        height, width = gray1.shape
        gray2 = cv2.resize(gray2, (width, height))

        score, diff = ssim(gray1, gray2, full=True)
        return score

    except Exception as e:
        return 0.0

def play_sound(sound_path):
    try:
        pygame.mixer.init()
        pygame.mixer.music.load(sound_path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.1)
    except pygame.error as e:
        print(f"Error playing sound: {e}")

def create_icon_image(icon_path=None):
    if icon_path and os.path.exists(icon_path):
        try:
            image = Image.open(icon_path)
            return image
        except Exception as e:
            print(f"Error loading icon from {icon_path}: {e}. Using default icon.")

    width = 64
    height = 64
    image = Image.new('RGB', (width, height), color = 'black')
    dc = ImageDraw.Draw(image)
    dc.rectangle([(width // 4, height // 4), (width * 3 // 4, height * 3 // 4)], fill='white')
    return image

def main_loop(icon):
    global capturing, is_match_detected
    while capturing:
        if capturing:
            # Determine active reference image based on current window resolution
            hwnd = win32gui.FindWindow(None, WINDOW_TITLE)
            if hwnd != 0:
                left, top, right, bot = win32gui.GetClientRect(hwnd)
                current_res = (right - left, bot - top)
                profile = RESOLUTION_PROFILES.get(current_res, RESOLUTION_PROFILES[DEFAULT_RES])
            else:
                profile = RESOLUTION_PROFILES[DEFAULT_RES]

            match_item_path = profile["match_image"]

            if take_screenshot_window():
                score = get_ssim_score(match_item_path, CROPPED_PATH)

                if not is_match_detected and score > MATCH_THRESHOLD:
                    is_match_detected = True
                    print(f"Match detected! (Score: {score:.2f})")
                    play_sound(SOUND_PATH)
                elif is_match_detected and score < DISAPPEAR_THRESHOLD:
                    is_match_detected = False
                    print(f"Match disappeared! (Score: {score:.2f})")

        time.sleep(SLEEP_INTERVAL)

def exit_action(icon, item):
    global capturing
    capturing = False
    icon.stop()

def toggle_capture(icon, item):
    global capturing
    capturing = not capturing

# --- Main Execution ---
if __name__ == "__main__":
    image = create_icon_image(ICON_PATH)

    menu = (
        item('Toggle Capture', toggle_capture, checked=lambda item: capturing),
        item('Exit', exit_action)
    )

    icon = pystray.Icon("fish_on_app", image, "Fish On App", menu)

    main_thread = threading.Thread(target=main_loop, args=(icon,))
    main_thread.start()

    icon.run()