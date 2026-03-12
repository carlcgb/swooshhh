# Swooshhh

Windows tray utility: hide windows off-screen and slide them back when you hover at the screen edge.

- **One window per edge (4 total)** – Left, right, top, bottom.
- **Hotkeys** – Ctrl+Alt+Arrow pins and hides the focused window to that edge.
- **GUI** – Pin to edge (screen layout), Unpin all, Start minimized (next launch), Help, Minimize to tray.
- **Tray** – Pin edges, Unpin all, Help, Show GUI, Exit. Reveal by hovering the edge; slide back when the mouse leaves the window.

## Download

**[swooshhh.exe](https://github.com/carlcgb/swooshhh/releases)** – Single file. Windows 10/11 (64-bit).  
If it won’t start, install [VC++ Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe).

## Run from source

```cmd
run.cmd install
run.cmd
```

| Command | Action |
|--------|--------|
| `run.cmd` | Start with GUI (default) |
| `run.cmd gui` | Same |
| `run.cmd tray` | Tray only |
| `run.cmd install` | Install dependencies |
| `run.cmd build` | Build dist\swooshhh.exe |

## Hotkeys

| Shortcut | Action |
|----------|--------|
| Ctrl+Alt+Left | Pin and hide to left edge |
| Ctrl+Alt+Right | Pin and hide to right edge |
| Ctrl+Alt+Up | Pin and hide to top edge |
| Ctrl+Alt+Down | Pin and hide to bottom edge |

Hover the edge to reveal; move the mouse off the window to slide it back.

## Config

In **swooshhh.py**: `PEEK_PX`, `TRIGGER_ZONE_PX`, `ANIMATION_MS`, `POLL_INTERVAL`.  
Start-minimized preference is stored under `%APPDATA%\Swooshhh\`.

## Publishing a release

1. `run.cmd build` → **dist\swooshhh.exe**
2. GitHub **Releases** → Create release → attach the exe.

## Security & privacy

No network. Minimal local file: start-minimized preference in app data. Otherwise Windows APIs only; open source.
