# Swooshhh

**Swooshhh** is a small Windows tray utility that hides windows off-screen and slides them back when you hover at the screen edge—like edge-peek panels.

## What it does

- **One window per edge (4 total)** – One window on the left, right, top, and bottom at the same time.
- **Hotkeys**: **Ctrl+Alt+Left / Right / Up / Down** – hide the focused window to that edge.
- **Pin** the current window from the GUI/tray; **Hide** slides it off-screen; **edge hover** slides it back (docked to the edge).
- **Stay visible while hovering** – When the window is revealed, it stays open while the mouse is over it and slides back when the mouse leaves.
- **GUI** – Pin/Unpin, Hide/Show, Edge (Left/Right/Top/Bottom). Optional **tray icon**.
- **Standalone .exe** – Build locally or download from [Releases](https://github.com/YOUR_USERNAME/YOUR_REPO/releases).

## Download (Releases)

Get the latest **swooshhh.exe** from the [Releases](https://github.com/YOUR_USERNAME/YOUR_REPO/releases) page. No Python required—just run the .exe.

## Requirements

- Windows 10/11
- Python 3.8+ (only if running from source)

## Setup (from source)

```bash
cd path\to\window
pip install -r requirements.txt
```

## Run

- **`run.cmd`** – Start with GUI (double‑click).
- **`run_gui.bat`** / **`run_tray.bat`** – GUI or tray only.
- **Command line:** `py swooshhh.py` or `py swooshhh.py --gui`

### Build .exe locally

```bash
pip install pyinstaller
build_exe.bat
```

Output: **`dist\swooshhh.exe`**.

## Publishing a release (GitHub)

1. **Initialize git** (if not already):
   ```bash
   git init
   git add .
   git commit -m "Swooshhh initial"
   git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
   git push -u origin main
   ```

2. **Create a release** on GitHub:
   - Repo → **Releases** → **Create a new release**
   - Tag: e.g. `v1.0.0`
   - Publish the release.

3. The **Release** workflow runs automatically: it builds **swooshhh.exe** on Windows and attaches it to that release. After a few minutes, download **swooshhh.exe** from the release assets.

4. (Optional) To build and attach the .exe yourself instead of using the workflow: run `build_exe.bat`, then edit the release and upload `dist\swooshhh.exe`.

## Hotkeys

| Shortcut | Action |
|----------|--------|
| **Ctrl+Alt+Left** | Hide focused window to the **left** edge |
| **Ctrl+Alt+Right** | Hide to the **right** edge |
| **Ctrl+Alt+Up** | Hide to the **top** edge |
| **Ctrl+Alt+Down** | Hide to the **bottom** edge |

Hover at the edge to reveal; move the mouse off the window to slide it back.

## Config (in code)

In `swooshhh.py`: `PEEK_PX`, `TRIGGER_ZONE_PX`, `ANIMATION_MS`, etc.

## Notes

- Uses the primary monitor; multi-monitor is not fully handled.
- The .exe is built with `--windowed` (no console window).
