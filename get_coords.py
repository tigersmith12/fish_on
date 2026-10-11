import os
import tkinter as tk
from PIL import ImageGrab
from ctypes import windll

# Force Windows to use true physical pixels instead of DPI-scaled virtual pixels
try:
    windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        windll.user32.SetProcessDPIAware()
    except Exception:
        pass

class RegionSelector:
    def __init__(self):
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0.3)
        self.root.attributes("-fullscreen", True)
        self.root.config(cursor="cross")
        
        self.canvas = tk.Canvas(self.root, cursor="cross", bg="grey")
        self.canvas.pack(fill="both", expand=True)
        
        self.canvas.bind("<ButtonPress-1>", self.on_button_press)
        self.canvas.bind("<B1-Motion>", self.on_move_press)
        self.canvas.bind("<ButtonRelease-1>", self.on_button_release)
        
        self.start_x = None
        self.start_y = None
        self.rect = None

    def on_button_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        self.rect = self.canvas.create_rectangle(self.start_x, self.start_y, 1, 1, outline='red', width=2)

    def on_move_press(self, event):
        cur_x, cur_y = event.x, event.y
        self.canvas.coords(self.rect, self.start_x, self.start_y, cur_x, cur_y)

    def on_button_release(self, event):
        end_x, end_y = event.x, event.y
        
        left = min(self.start_x, end_x)
        top = min(self.start_y, end_y)
        right = max(self.start_x, end_x)
        bottom = max(self.start_y, end_y)
        
        # Hide the selection window so it isn't captured in the screenshot
        self.root.withdraw()
        self.root.update()
        
        try:
            # Ensure the pictures directory exists
            os.makedirs("pictures", exist_ok=True)
            save_path = os.path.join("pictures", "match_item.png")
            
            # Capture the screen region and save it directly
            screenshot = ImageGrab.grab(bbox=(left, top, right, bottom))
            screenshot.save(save_path)
            print(f"\nSuccessfully saved reference image: {save_path}")
        except Exception as e:
            print(f"Error saving image: {e}")
        
        print("=" * 40)
        print(f"CROP_RECT = ({left}, {top}, {right}, {bottom})")
        print("=" * 40 + "\n")
        
        self.root.destroy()

    def run(self):
        print("Click and drag over the target area on your screen...")
        self.root.mainloop()

if __name__ == "__main__":
    RegionSelector().run()