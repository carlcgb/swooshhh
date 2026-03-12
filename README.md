# Swooshhh

Windows tray app: hide windows off-screen and slide them back when you hover the screen edge.

- **One window per edge** (left, right, top, bottom; 4 total).
- **Hotkeys** — Ctrl+Alt+Arrow pins and hides the focused window to that edge.
- **GUI** — Pick a window from the list (same monitor, visible only), pin to an edge, unpin all, start minimized, help.
- **Tray** — Unpin all, Help, Show GUI, Exit. Hover the edge to reveal; move the mouse off the window to slide it back.

## Download

**[swooshhh.exe](https://github.com/carlcgb/swooshhh/releases)** — Single file. Windows 10/11 (64-bit).  
If it won’t start, install [VC++ Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe).

## Run from source

```cmd
run.cmd install
run.cmd
```

| Command        | Action                    |
|----------------|---------------------------|
| `run.cmd`      | Start with GUI (default) |
| `run.cmd gui`  | Same                      |
| `run.cmd tray` | Tray only                 |
| `run.cmd install` | Install dependencies  |
| `run.cmd build`   | Build `dist\swooshhh.exe` |

## Hotkeys

| Shortcut           | Action              |
|--------------------|---------------------|
| Ctrl+Alt+Left      | Pin and hide left   |
| Ctrl+Alt+Right     | Pin and hide right  |
| Ctrl+Alt+Up        | Pin and hide top    |
| Ctrl+Alt+Down      | Pin and hide bottom |

Hover the edge to reveal; move the mouse off the window to slide it back.

## Config

Tunables in **swooshhh.py**: `PEEK_PX`, `TRIGGER_ZONE_PX`, `ANIMATION_MS`, `POLL_INTERVAL`.  
Start-minimized preference: `%APPDATA%\Swooshhh\`.

## Release

1. `run.cmd build` → **dist\swooshhh.exe**
2. Create a GitHub release and attach the exe.

## Privacy

No network. Only local file: start-minimized preference. Otherwise Windows APIs only; open source.
