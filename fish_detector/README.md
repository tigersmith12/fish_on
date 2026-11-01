# Fish On — corrected HUD detector

## Quick start (Windows)

1. Extract the entire ZIP. Keep `pictures` beside `fish_on.py`.
2. Install Python 3.10 or newer, if needed.
3. Open a terminal in the extracted folder and run:

```powershell
py -m pip install -r requirements.txt
py fish_on.py
```

The game window title must be `Russian Fishing 4`. A tray icon provides **Capture enabled**, **Save debug image**, and **Exit**. Toggle capture to pause/resume without terminating the worker.

For console-only use:

```powershell
py fish_on.py --no-tray
```

Press Ctrl+C to exit console mode. If your system uses `python` rather than `py`, substitute `python` in these commands.

## Sound

The original WAV was not attached. Without it, the script uses the Windows notification beep (which can be silent depending on system sound settings). To use your original sound, copy `stardew-fishing_EimR00g.wav` beside `fish_on.py`, or pass:

```powershell
py fish_on.py --sound "C:\Sounds\fish.wav"
```

Sound is initialized once and playback does not block detection.

## What was wrong

- The older script uses y=819–839, which is below the bottom of the supplied 1366×768 screenshot.
- The newer script uses x=360–389 at 1366×768. The matching fish icon is around x=447–476, y=711–740 using the supplied 29×29 template.
- The coordinate selector returns desktop/screen coordinates, but the detector crops a captured window. These are different coordinate systems unless their origins coincide.
- `GetClientRect` describes the client area, while the original `PrintWindow(..., 2)` requests a window rendering without explicitly requesting client-only capture. Borders/title bars can introduce another offset in windowed mode.
- Unknown resolutions silently fall back to the 1920×1080 crop.
- The original loop writes a PNG, reads images back, and resizes a crop every poll. SSIM compares aligned images; it does not locate an icon within a search region.
- The original `while capturing:` ends the worker on pause, so toggling back on cannot restart it.
- Blocking audio playback stops the old detector from sampling until the sound finishes.

## How this version works

- Makes the process DPI-aware before importing capture/UI libraries.
- Gets the actual client origin with `ClientToScreen`, so moving the window does not shift the search coordinates relative to the game.
- Uses MSS to capture only a small HUD region, directly into memory.
- Searches with normalized color template correlation, using the provided references at original and nearby/proportional sizes. Resized templates are cached until client width changes.
- Default search box: 22%–43% of client width and 87%–98% of client height. At 1366×768 it is `(300, 668, 587, 752)` (about 2.3% of the full image).
- Samples every 0.20 seconds. Requires two consecutive scores at or above 0.80 before alerting, then three consecutive scores below 0.65 to rearm. A continuously visible icon does not repeatedly trigger.
- Pausing or losing capture resets consecutive-frame counters but preserves the alert latch, avoiding an automatic repeat notification on return.
- Defaults to foreground-only capture and skips minimized/hidden windows.

**A correlation score is not a probability.** The 0.80/0.65 thresholds are starting points, not guaranteed settings for every background or HUD scale.

## Verify the capture region

A `live_debug.png` is saved after the first successful capture. It shows just the searched HUD region, the best match, and its score. The tray's **Save debug image** option requests another image on the next successful capture. There are no repeated screenshot writes in normal operation.

A blue outline marks the searched area; a green match is at/above threshold, a red one is below threshold. Below threshold, the displayed rectangle is only the best candidate, not a detection.

If your icon is outside the default search region, widen it temporarily:

```powershell
py fish_on.py --roi 0.15 0.80 0.70 1.0
```

These four numbers are left/top/right/bottom fractions of the **client area**, not desktop pixels. Then narrow the region to the fish indicator to avoid similar circular HUD icons. Do not copy an entire-desktop screenshot's coordinates directly into this option.

To change polling or matching thresholds:

```powershell
py fish_on.py --interval 0.25 --threshold 0.85 --clear-threshold 0.65
```

Start with defaults. Check both fish-present and fish-absent frames before lowering a threshold. If the HUD changes substantially, replace a reference image with a tight screenshot of the actual fish indicator. Background pixels in these references can affect correlation.

## Offline screenshot test

```powershell
py fish_on.py --test "C:\Screenshots\game.png" --output debug_match.png
```

The screenshot should contain **only the game client area**, as the uploaded screenshot does. No game, tray, or sound is required. A below-threshold result exits with code 1; a match exits with code 0. The screenshot test evaluates one frame, not the live two-frame debounce.

`detection_preview.png` is the annotated result for your uploaded 1366×768 screenshot:

- Score: **0.9306**
- Best match bounds: **(443, 710, 476, 742)**, right/bottom exclusive
- Best template: `match_item_1920x1080.png`, at its original 33×32 size
- The bounds differ slightly from the 29×29 reference's `(447, 711, 476, 740)` because the best-scoring reference has different padding. Both locate the same fish icon.

Five automated checks pass:

```powershell
py -m unittest -v
```

They cover ROI conversion, exact-template location changes, empty regions, undersized search regions, and debounce/rearm behavior. They are basic regression tests, not a representative gameplay accuracy test. Windows live capture, DPI/multi-monitor behavior, tray actions, and audio were not executable in the development environment and need checking on your PC. The supplied 1600×900 and 1920×1080 references are included, but screenshots at those resolutions were not provided for validation.

## Capture limitations

MSS reads visible screen pixels; it cannot see through another window. Keep the HUD unobstructed. Borderless/windowed mode is recommended if exclusive fullscreen returns black or stale frames. A nonfocused game is skipped by default. `--allow-background` relaxes that focus check, but does not make capture work behind other windows or when minimized. Notifications/overlays covering the HUD can still interfere even with the foreground check enabled.

The detector does not press keys or interact with the game; it only analyzes the visible HUD and plays a notification. The original scripts in your uploads have not been modified.
