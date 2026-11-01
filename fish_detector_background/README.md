# Fish On — PrintWindow background-capture edition

This edition restores the original capture method so the game can be covered by another window or unfocused, while keeping template matching, corrected search coordinates, pause/resume, and nonblocking audio.

## Install and run (Windows, Python 3.10+)

Extract the entire ZIP. Keep the `pictures` folder beside `fish_on.py`. Open a terminal in the extracted folder:

```powershell
py -m pip install -r requirements.txt
py fish_on.py
```

Stop the earlier copy of the detector first so you do not receive duplicate notifications. No `--allow-background` option is needed; background capture is enabled by default. That flag is still accepted for compatibility, but does nothing.

The exact window title defaults to `Russian Fishing 4`. Override if needed:

```powershell
py fish_on.py --title "Russian Fishing 4"
```

The tray menu has **Capture enabled** (pause/resume), **Save debug image**, and **Exit**. For console-only operation:

```powershell
py fish_on.py --no-tray
```

Press Ctrl+C to exit console mode. Use `python` instead of `py` if that is how Python is installed on your PC.

## What changed from the MSS edition

- **Restored `PrintWindow`** instead of taking a screenshot of the visible desktop.
- **Removed the foreground-only restriction.** Covering the game or switching focus does not deliberately stop capture.
- The default uses **flags=2**, matching the original script's PrintWindow call.
- Allocates a full-window bitmap using `GetWindowRect`. Translates the client search box into that bitmap using `ClientToScreen(0, 0)` minus the window's top-left. This accounts for borders/title bars rather than confusing desktop, window, and client coordinates.
- Reuses a top-down 32-bit GDI bitmap until window dimensions change. Only the HUD region is copied into OpenCV. No PNG encode/decode on every poll.
- Clears the reused bitmap before each render, rejects failed calls and almost-black HUD captures, and cleans up GDI resources when resizing or stopping.
- Native calls use pointer-sized handle signatures for 64-bit Windows. No pywin32 or MSS dependency is needed; capture uses Python's ctypes.

**Tradeoff:** PrintWindow renders a full window before the small HUD region is analyzed. This is more work than MSS's visible-region capture, but preserves the original ability to capture an obscured game when the game supports it. PrintWindow is synchronous; an unresponsive target may delay capture/shutdown.

## Confirm the covered-window behavior

1. Start the game and leave it restored (not minimized).
2. Run the detector. Check `live_debug.png` beside the script to confirm that the actual fish HUD is being searched.
3. Cover the game with another application and leave the game running.
4. Use the tray's **Save debug image** option. It requests another image on the next successful capture. Check that the image contains the game HUD, not the covering application's pixels.
5. Watch console scores with the fish icon both present and absent. The detector alerts on a new confirmed appearance, not repeatedly while an icon remains visible.

The default uses a full-window render with a corrected client offset. If this game/Windows setup produces a shifted, blank, or incorrect region, try explicit client-only rendering:

```powershell
py fish_on.py --printwindow-mode client
```

This uses flags=3 (`PW_RENDERFULLCONTENT | PW_CLIENTONLY`), a client-sized bitmap, and no border offset. The two modes are explicit rather than silently falling back to desktop capture, which would break covered-window operation again.

### Limitations

The code no longer requires the game to be unobstructed or focused, but **real background rendering still depends on the game and Windows**. A successful PrintWindow return does not guarantee that the game supplied a current frame. Some games pause or stop updating in the background. Uniform black HUD captures are rejected; frozen but otherwise valid images cannot be reliably identified as stale from pixels alone.

Minimized/hidden windows are deliberately skipped because their rendering is unreliable. Leave the game restored; covering it with another window is fine to try. If exclusive fullscreen produces black/stale frames, try borderless or windowed mode. Match the game's privilege level if capture fails due to permissions; do not elevate unnecessarily.

## Detection and tuning

The search box is expressed as fractions of the **client area**, not desktop coordinates:

- Left/right: 0.22 to 0.43 of client width
- Top/bottom: 0.87 to 0.98 of client height
- At 1366×768: `(300, 668, 587, 752)` before any full-window border offset

Supplied references are loaded once; nearby and proportional scales are cached until client width changes. Default polling is 0.20 seconds (or slower if rendering takes longer). Two consecutive scores >=0.80 trigger an alert. Three consecutive scores <0.65 rearm it. Capture failures and pauses clear consecutive-frame counters but preserve the alert latch to avoid repeat notifications on return.

To widen the search box temporarily:

```powershell
py fish_on.py --roi 0.15 0.80 0.70 1.0
```

Then narrow it around the fish indicator to avoid other similar circular icons. To change timing/thresholds:

```powershell
py fish_on.py --interval 0.25 --threshold 0.85 --clear-threshold 0.65
```

Scores are correlation values, not probabilities. Defaults are starting points. Check fish-present and fish-absent scenes before lowering thresholds. `live_debug.png` shows the search region and best candidate: green is above threshold, red is below. A below-threshold rectangle is not a detection.

## Sound

The original WAV was not attached. Without it the script uses the Windows notification beep, which may be silent depending on system sound settings. Copy `stardew-fishing_EimR00g.wav` beside `fish_on.py`, or use:

```powershell
py fish_on.py --sound "C:\Sounds\fish.wav"
```

Sound is initialized once and playback does not block detection.

## Tests and validation

Analyze a saved screenshot of **only the game client area**:

```powershell
py fish_on.py --test "C:\Screenshots\game.png" --output debug_match.png
```

This does not require Windows or a running game. It is a single-frame test, not the live two-frame debounce. Exit code is 0 for a match and 1 below threshold.

The supplied 1366×768 screenshot still produces:

- Best score: **0.9306**
- Match bounds: **(443, 710, 476, 742)**, right/bottom exclusive
- Best reference: `match_item_1920x1080.png`, at its original 33×32 size

`detection_preview.png` shows that result. Differing reference padding explains the slight offset from the 29×29 template's `(447, 711, 476, 740)` match. Both locate the same fish icon.

Run regression checks:

```powershell
py -m unittest -v
```

The suite includes detection/debounce checks, border-offset and negative-monitor-coordinate calculations, and mocked capture checks for background operation, window/client flags, black/failure handling, and minimized-window skipping. **Mocks do not validate native Windows/GDI behavior.** Windows live capture, tray/audio, and real covered-window game rendering could not be executed in the development environment; confirm them on your PC. Screenshots at 1600×900 and 1920×1080 were not provided for validation.

The original uploaded scripts and the earlier MSS edition are unchanged. This notifier analyzes pixels and plays audio; it does not send input to the game.
