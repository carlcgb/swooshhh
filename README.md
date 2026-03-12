# Swooshhh

Windows tray app: hide windows off-screen and slide them back when you hover the screen edge.

- **One window per edge** — Left, right, top, bottom (4 total).
- **Hotkeys** — Ctrl+Alt+Arrow pins and hides the *focused* window to that edge.
- **GUI** — Window dropdown (Refresh) lists windows on the *same monitor*, visible and not minimized (system and Swooshhh excluded). Pin to edge, Unpin all, Start minimized, Help, Minimize to tray.
- **Tray** — Unpin all, Help, Show GUI, Exit. Hover the edge to reveal (blue dot shows where a window is hidden); move the mouse off the window to slide it back.

## Download

**[swooshhh.exe](https://github.com/carlcgb/swooshhh/releases)** — Single file. Windows 10/11 (64-bit).  
If it won’t start, install [VC++ Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe).

## Run from source

Requires Python 3 and: `pywin32`, `pystray`, `Pillow` (see `requirements.txt`).

```cmd
run.cmd install
run.cmd
```

| Command          | Action                              |
|------------------|-------------------------------------|
| `run.cmd`        | Start with GUI (opens in new window)|
| `run.cmd gui`    | Run with GUI (in foreground)        |
| `run.cmd tray`   | Tray only (no GUI)                  |
| `run.cmd install`| Install dependencies        |
| `run.cmd build`  | Build `dist\swooshhh.exe`   |

## Hotkeys

| Shortcut       | Action            |
|----------------|-------------------|
| Ctrl+Alt+Left  | Pin and hide left |
| Ctrl+Alt+Right | Pin and hide right|
| Ctrl+Alt+Up    | Pin and hide top  |
| Ctrl+Alt+Down  | Pin and hide bottom|

Hover the edge to reveal; move the mouse off the window to slide it back.

## Config

In **swooshhh.py**: `PEEK_PX`, `TRIGGER_ZONE_PX`, `ANIMATION_MS`, `POLL_INTERVAL`, `INDICATOR_COLOR`, `INDICATOR_SIZE`, `INDICATOR_THICKNESS`.  
Start-minimized: stored under `%APPDATA%\Swooshhh\`.

## Release

1. `run.cmd build` → **dist\swooshhh.exe**
2. Create a GitHub release and attach the exe.

## Privacy

No network. Only local file: start-minimized preference. Otherwise Windows APIs only; open source.
