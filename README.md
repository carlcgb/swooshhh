# Swooshhh

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![EXE](https://img.shields.io/badge/EXE-Portable-00C853?style=for-the-badge&logo=windows&logoColor=white)](https://github.com/carlcgb/swooshhh/releases)
[![Window Manager](https://img.shields.io/badge/Window_Manager-Edge%20Peek-7C4DFF?style=for-the-badge)](https://github.com/carlcgb/swooshhh)

**Swooshhh** is a Windows tray utility that hides windows off-screen and slides them back when you hover at the screen edge (one window per edge, four total).

---

## Download

**[Releases](https://github.com/carlcgb/swooshhh/releases)** — download **swooshhh.exe**. No install, no Python. Run it anywhere.

- **Windows 10/11 (64-bit).** If the app won’t start (rare), install [VC++ Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe).

## What it does

- **Ctrl+Alt+Arrow** — hide the focused window to that edge (left / right / top / bottom).
- **Right-click title bar + drag to edge** — right-click any window, drag toward the screen edge, release; that window is hidden to that edge.
- **One window per edge** — up to four windows at once.
- **Edge hover** — move the mouse to the edge to slide the window back; move off the window to slide it away.
- **Multi-monitor** — hidden windows stay off all monitors; edge zones use the full virtual screen.
- **Edge indicators** — a subtle strip on each edge shows where a window is hidden.
- **GUI** — Pin/Unpin, Hide/Show, choose edge. Tray icon optional. **swooshhh.exe** starts minimized to tray.

## Run from source

```bash
pip install -r requirements.txt
py swooshhh.py --gui
```

- **run.cmd** — start with GUI.  
- **run_gui.bat** / **run_tray.bat** — GUI or tray only.

## Build .exe

```bash
pip install pyinstaller
build_exe.bat
```

Output: **dist\swooshhh.exe**.

## How to publish a release

1. Push your code to **github.com/carlcgb/swooshhh**.
2. Open the repo → **Releases** → **Create a new release**.
3. Choose a tag (e.g. `v1.0.0` — create the tag if it doesn’t exist), add a title/notes, click **Publish release**.
4. The GitHub Action builds **swooshhh.exe** and attaches it to the release. Download it from **Assets** on the release page.

## Hotkeys & mouse

| Shortcut | Action |
|----------|--------|
| Ctrl+Alt+Left | Hide to left edge |
| Ctrl+Alt+Right | Hide to right edge |
| Ctrl+Alt+Up | Hide to top edge |
| Ctrl+Alt+Down | Hide to bottom edge |

**Mouse:** Right-click a window, drag toward a screen edge, release within ~50 px of the edge.

## Config

In **swooshhh.py**: `PEEK_PX`, `TRIGGER_ZONE_PX`, `DRAG_EDGE_ZONE_PX`, `ANIMATION_MS`.

## Security & privacy

- **No network** — does not connect to the internet.
- **No config files** — nothing written to disk.
- **Local only** — Win32 APIs only; no eval/exec.
- **Open source** — review [swooshhh.py](swooshhh.py).

## Repo

| File | Purpose |
|------|---------|
| `swooshhh.py` | Main app |
| `requirements.txt` | Python deps |
| `build_exe.bat` | Build exe |
| `run.cmd`, `run_gui.bat`, `run_tray.bat`, `install.bat` | Launchers |
| `.github/workflows/release.yml` | CI: build exe on release |

**Multi-monitor supported.** Exe built with `--windowed` (no console).
