"""
Swooshhh - Slide windows off-screen and back on edge hover.

Usage:
  python swooshhh.py              # Tray only
  python swooshhh.py --gui       # GUI window + tray
  python swooshhh.py --gui --start-minimized
  python swooshhh.py --edge right

Build .exe: pip install pyinstaller && build_exe.bat
"""

import argparse
import ctypes
import math
import sys
import threading
import time
from ctypes import wintypes
from collections import namedtuple

import win32api
import win32con
import win32gui
from PIL import Image, ImageDraw
import pystray

byref = ctypes.byref
user32 = ctypes.windll.user32
WM_HOTKEY = 0x0312

# --- Config ---
EDGE_LEFT = "left"
EDGE_RIGHT = "right"
EDGE_TOP = "top"
EDGE_BOTTOM = "bottom"
EDGES = (EDGE_LEFT, EDGE_RIGHT, EDGE_TOP, EDGE_BOTTOM)
PEEK_PX = 4
TRIGGER_ZONE_PX = 14
LEAVE_ZONE_PX = 60
ANIMATION_MS = 200
POLL_INTERVAL = 0.035
# Hotkeys: Ctrl+Alt+Arrow = hide focused window to that edge (one window per edge, 4 max)
MOD_HOTKEY = win32con.MOD_ALT | win32con.MOD_CONTROL
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28

SavedRect = namedtuple("SavedRect", "left top right bottom")


def get_foreground_hwnd():
    return win32gui.GetForegroundWindow()


def get_window_rect(hwnd):
    try:
        r = win32gui.GetWindowRect(hwnd)
        return SavedRect(*r)
    except Exception:
        return None


def set_window_rect(hwnd, rect, flags=0):
    if rect is None:
        return
    flags = flags or win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE
    win32gui.SetWindowPos(
        hwnd,
        win32con.HWND_TOP,
        rect.left,
        rect.top,
        rect.right - rect.left,
        rect.bottom - rect.top,
        flags,
    )


def get_cursor_pos():
    try:
        return win32api.GetCursorPos()
    except Exception:
        return (0, 0)


def get_primary_screen_size():
    w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
    h = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
    return w, h


def is_window_valid(hwnd):
    if not hwnd:
        return False
    try:
        return win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd)
    except Exception:
        return False


def get_window_title(hwnd):
    if not hwnd:
        return ""
    try:
        return (win32gui.GetWindowText(hwnd) or "").strip() or "(no title)"
    except Exception:
        return ""


def _interp_rect(r0, r1, t):
    """Linear interpolate from r0 to r1; t in [0,1]. Returns SavedRect."""
    return SavedRect(
        int(r0.left + (r1.left - r0.left) * t),
        int(r0.top + (r1.top - r0.top) * t),
        int(r0.right + (r1.right - r0.right) * t),
        int(r0.bottom + (r1.bottom - r0.bottom) * t),
    )


def _docked_rect(edge, saved, width, height, sw, sh):
    """Rect when window is shown but stays attached to the screen edge (not restored to center)."""
    if edge == EDGE_LEFT:
        return SavedRect(0, saved.top, width, saved.bottom)
    elif edge == EDGE_RIGHT:
        return SavedRect(sw - width, saved.top, sw, saved.bottom)
    elif edge == EDGE_TOP:
        return SavedRect(saved.left, 0, saved.left + width, height)
    else:  # EDGE_BOTTOM
        return SavedRect(saved.left, sh - height, saved.left + width, sh)


# Hotkey ids: one per edge (one window per edge, 4 total)
_HOTKEY_IDS = {1: EDGE_LEFT, 2: EDGE_RIGHT, 3: EDGE_TOP, 4: EDGE_BOTTOM}


def run_hotkey_thread(slider):
    """Run a message loop in this thread; Ctrl+Alt+Arrow hides focused window to that edge."""
    for hid, edge in _HOTKEY_IDS.items():
        vk = {EDGE_LEFT: VK_LEFT, EDGE_RIGHT: VK_RIGHT, EDGE_TOP: VK_UP, EDGE_BOTTOM: VK_DOWN}[edge]
        if not user32.RegisterHotKey(None, hid, MOD_HOTKEY, vk):
            pass  # non-fatal if one fails
    try:
        msg = wintypes.MSG()
        while user32.GetMessageA(byref(msg), None, 0, 0) != 0:
            if msg.message == WM_HOTKEY:
                edge = _HOTKEY_IDS.get(msg.wParam)
                if edge:
                    slider.pin_and_hide_to_edge(edge)
            user32.TranslateMessage(byref(msg))
            user32.DispatchMessageA(byref(msg))
    finally:
        for hid in _HOTKEY_IDS:
            user32.UnregisterHotKey(None, hid)


class WindowSlider:
    def __init__(self):
        self.edge = EDGE_LEFT  # selected edge for GUI (Pin/Unpin/Hide/Show)
        self._slots = {
            e: {"hwnd": None, "saved_rect": None, "hidden": False, "_polls": 0}
            for e in EDGES
        }
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def _has_any_window(self):
        return any(self._slots[e]["hwnd"] for e in EDGES)

    def pin_current(self):
        """Pin the focused window to the currently selected edge (replaces any window on that edge)."""
        hwnd = get_foreground_hwnd()
        if not hwnd or not is_window_valid(hwnd):
            return False
        edge = self.edge
        with self._lock:
            self._remove_hwnd_from_other_edges(hwnd, None)  # remove from any edge
            self._clear_slot(edge)  # restore previous window on this edge if any
            self._slots[edge]["hwnd"] = hwnd
            self._slots[edge]["saved_rect"] = get_window_rect(hwnd)
            self._slots[edge]["hidden"] = False
            self._slots[edge]["_polls"] = 0
            self._ensure_worker()
        return True

    def _clear_slot(self, edge):
        s = self._slots[edge]
        if s["hwnd"] and s["saved_rect"] and s["hidden"]:
            set_window_rect(s["hwnd"], s["saved_rect"])
        s["hwnd"] = None
        s["saved_rect"] = None
        s["hidden"] = False
        s["_polls"] = 0

    def _remove_hwnd_from_other_edges(self, hwnd, except_edge):
        """Clear this hwnd from any other edge (so one window can't be on two edges)."""
        for e in EDGES:
            if e != except_edge and self._slots[e]["hwnd"] == hwnd:
                self._clear_slot(e)
                break

    def unpin(self):
        """Unpin the window on the currently selected edge."""
        with self._lock:
            self._clear_slot(self.edge)
            has_any = self._has_any_window()
        if not has_any:
            self._stop_worker()

    def unpin_all(self):
        """Unpin all four edges and restore any hidden windows."""
        with self._lock:
            for e in EDGES:
                self._clear_slot(e)
        self._stop_worker()

    def set_edge(self, edge):
        with self._lock:
            self.edge = edge

    def pin_and_hide_to_edge(self, edge):
        """Pin the focused window to this edge and hide it (one window per edge; replaces existing on that edge)."""
        hwnd = get_foreground_hwnd()
        if not hwnd or not is_window_valid(hwnd):
            return False
        with self._lock:
            self._remove_hwnd_from_other_edges(hwnd, edge)  # remove from other edges
            self._clear_slot(edge)  # restore previous window on this edge
            self._slots[edge]["hwnd"] = hwnd
            self._slots[edge]["saved_rect"] = get_window_rect(hwnd)
            self._slots[edge]["hidden"] = False
            self._slots[edge]["_polls"] = 0
            self._ensure_worker()
        self._hide_to_edge(edge)
        return True

    def _ensure_worker(self):
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._worker, daemon=True)
            self._thread.start()

    def _start_worker(self):
        self._ensure_worker()

    def _stop_worker(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def _worker(self):
        steps = max(1, int(ANIMATION_MS / (POLL_INTERVAL * 1000)))
        sw, sh = get_primary_screen_size()
        while not self._stop.is_set():
            cursor = get_cursor_pos()
            for edge in EDGES:
                with self._lock:
                    hwnd = self._slots[edge]["hwnd"]
                    saved = self._slots[edge]["saved_rect"]
                    hidden = self._slots[edge]["hidden"]
                    polls = self._slots[edge]["_polls"]

                if not hwnd or not saved or not is_window_valid(hwnd):
                    continue

                try:
                    rect = get_window_rect(hwnd)
                    if not rect:
                        continue
                    width = rect.right - rect.left
                    height = rect.bottom - rect.top

                    if edge == EDGE_LEFT:
                        at_edge = cursor[0] < TRIGGER_ZONE_PX
                        in_range = saved.top <= cursor[1] <= saved.bottom or cursor[0] < 4
                        target_hidden = SavedRect(-width + PEEK_PX, saved.top, PEEK_PX, saved.bottom)
                        visible_rect = _docked_rect(edge, saved, width, height, sw, sh)
                    elif edge == EDGE_RIGHT:
                        at_edge = cursor[0] > sw - TRIGGER_ZONE_PX
                        in_range = saved.top <= cursor[1] <= saved.bottom or cursor[0] > sw - 4
                        target_hidden = SavedRect(sw - PEEK_PX, saved.top, sw - PEEK_PX + width, saved.bottom)
                        visible_rect = _docked_rect(edge, saved, width, height, sw, sh)
                    elif edge == EDGE_TOP:
                        at_edge = cursor[1] < TRIGGER_ZONE_PX
                        in_range = saved.left <= cursor[0] <= saved.right or cursor[1] < 4
                        target_hidden = SavedRect(saved.left, -height + PEEK_PX, saved.right, PEEK_PX)
                        visible_rect = _docked_rect(edge, saved, width, height, sw, sh)
                    else:
                        at_edge = cursor[1] > sh - TRIGGER_ZONE_PX
                        in_range = saved.left <= cursor[0] <= saved.right or cursor[1] > sh - 4
                        target_hidden = SavedRect(saved.left, sh - PEEK_PX, saved.right, sh - PEEK_PX + height)
                        visible_rect = _docked_rect(edge, saved, width, height, sw, sh)

                    # When visible: stay open while cursor is over the window; slide out when cursor leaves
                    cursor_over_window = (
                        rect.left <= cursor[0] <= rect.right and rect.top <= cursor[1] <= rect.bottom
                    )

                    if hidden:
                        if at_edge and in_range:
                            for i in range(1, steps + 1):
                                if self._stop.is_set():
                                    break
                                t = i / steps
                                t = 0.5 - 0.5 * math.cos(math.pi * t)
                                new_rect = _interp_rect(rect, visible_rect, t)
                                set_window_rect(hwnd, new_rect)
                                time.sleep(POLL_INTERVAL)
                            with self._lock:
                                self._slots[edge]["hidden"] = False
                        else:
                            pass
                    else:
                        # Visible: stay open while cursor is over window; slide out when cursor leaves
                        if cursor_over_window:
                            with self._lock:
                                self._slots[edge]["_polls"] = 0
                        else:
                            with self._lock:
                                self._slots[edge]["_polls"] = polls + 1
                                n = self._slots[edge]["_polls"]
                            if n >= 8:
                                for i in range(1, steps + 1):
                                    if self._stop.is_set():
                                        break
                                    t = i / steps
                                    t = 0.5 - 0.5 * math.cos(math.pi * t)
                                    new_rect = _interp_rect(rect, target_hidden, t)
                                    set_window_rect(hwnd, new_rect)
                                    time.sleep(POLL_INTERVAL)
                                with self._lock:
                                    self._slots[edge]["hidden"] = True
                                    self._slots[edge]["_polls"] = 0
                except Exception:
                    pass

            self._stop.wait(POLL_INTERVAL)

    def _hide_to_edge(self, edge):
        """Immediately move the window in slot[edge] off-screen (no animation)."""
        with self._lock:
            hwnd = self._slots[edge]["hwnd"]
            saved = self._slots[edge]["saved_rect"]
        if not hwnd or not saved or not is_window_valid(hwnd):
            return
        rect = get_window_rect(hwnd)
        if not rect:
            return
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        sw, sh = get_primary_screen_size()
        if edge == EDGE_LEFT:
            hidden_rect = SavedRect(-width + PEEK_PX, saved.top, PEEK_PX, saved.bottom)
        elif edge == EDGE_RIGHT:
            hidden_rect = SavedRect(sw - PEEK_PX, saved.top, sw - PEEK_PX + width, saved.bottom)
        elif edge == EDGE_TOP:
            hidden_rect = SavedRect(saved.left, -height + PEEK_PX, saved.right, PEEK_PX)
        else:
            hidden_rect = SavedRect(saved.left, sh - PEEK_PX, saved.right, sh - PEEK_PX + height)
        set_window_rect(hwnd, hidden_rect)
        with self._lock:
            self._slots[edge]["saved_rect"] = saved
            self._slots[edge]["hidden"] = True

    def hide_current(self):
        self._hide_to_edge(self.edge)

    def show_current(self):
        with self._lock:
            hwnd = self._slots[self.edge]["hwnd"]
            saved = self._slots[self.edge]["saved_rect"]
            hidden = self._slots[self.edge]["hidden"]
        if not hwnd or not saved or not hidden or not is_window_valid(hwnd):
            return
        rect = get_window_rect(hwnd)
        if not rect:
            return
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        sw, sh = get_primary_screen_size()
        docked = _docked_rect(self.edge, saved, width, height, sw, sh)
        set_window_rect(hwnd, docked)
        with self._lock:
            self._slots[self.edge]["hidden"] = False

    def get_status(self):
        """Return (pinned_title, edge, hidden) for the selected edge."""
        with self._lock:
            hwnd = self._slots[self.edge]["hwnd"]
            hidden = self._slots[self.edge]["hidden"]
        if not hwnd:
            return None, self.edge, False
        return get_window_title(hwnd), self.edge, hidden

    def get_status_all(self):
        """Return list of (edge, title, hidden) for all slots that have a window."""
        with self._lock:
            out = []
            for e in EDGES:
                hwnd = self._slots[e]["hwnd"]
                if hwnd:
                    out.append((e, get_window_title(hwnd), self._slots[e]["hidden"]))
        return out


def make_tray_icon(slider):
    def on_pin(icon, item):
        if slider.pin_current():
            icon.notify("Pinned current window. Use Hide to slide off-screen.", "Swooshhh")
        else:
            icon.notify("Focus a window first, then try again.", "Swooshhh")

    def on_unpin(icon, item):
        slider.unpin()
        icon.notify("Unpinned from selected edge.", "Swooshhh")

    def on_unpin_all(icon, item):
        slider.unpin_all()
        icon.notify("Unpinned all edges.", "Swooshhh")

    def on_hide(icon, item):
        slider.hide_current()

    def on_show(icon, item):
        slider.show_current()

    def on_exit(icon, item):
        slider.unpin_all()
        if getattr(icon, "_gui_root", None):
            try:
                icon._gui_root.quit()
            except Exception:
                pass
        icon.stop()

    img = Image.new("RGB", (64, 64), color=(45, 55, 72))
    draw = ImageDraw.Draw(img)
    draw.rectangle([8, 8, 56, 56], outline=(99, 179, 237), width=2)
    draw.rectangle([0, 24, 12, 40], fill=(99, 179, 237))
    del draw

    menu = pystray.Menu(
        pystray.MenuItem("Pin current window", on_pin),
        pystray.MenuItem("Unpin (selected edge)", on_unpin),
        pystray.MenuItem("Unpin all edges", on_unpin_all),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Hide (slide off-screen)", on_hide),
        pystray.MenuItem("Show (slide back)", on_show),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Edge: Left", lambda i, _: slider.set_edge(EDGE_LEFT)),
        pystray.MenuItem("Edge: Right", lambda i, _: slider.set_edge(EDGE_RIGHT)),
        pystray.MenuItem("Edge: Top", lambda i, _: slider.set_edge(EDGE_TOP)),
        pystray.MenuItem("Edge: Bottom", lambda i, _: slider.set_edge(EDGE_BOTTOM)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Exit", on_exit),
    )

    icon = pystray.Icon(
        "swooshhh", img, "Swooshhh (Ctrl+Alt+Arrow = hide to edge)", menu
    )
    return icon


def run_gui(slider, start_minimized=False):
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("Swooshhh")
    root.minsize(320, 220)
    root.resizable(True, True)

    main = ttk.Frame(root, padding=12)
    main.pack(fill=tk.BOTH, expand=True)

    status_text = tk.StringVar(value="No window pinned. Focus a window and click Pin.")
    status = ttk.Label(main, textvariable=status_text, wraplength=280)
    status.pack(anchor=tk.W, pady=(0, 10))

    def update_status():
        all_slots = slider.get_status_all()
        title, edge, hidden = slider.get_status()
        if not all_slots:
            status_text.set("No windows pinned. Focus a window and click Pin, or use Ctrl+Alt+Arrow.")
        else:
            lines = [f"Selected edge: {edge}"]
            if title:
                short = title[: 35] + "…" if len(title) > 35 else title
                lines.append(f"  → {short} · {'hidden' if hidden else 'visible'}")
            parts = []
            for e, t, h in all_slots:
                short = (t[: 12] + "…" if len(t) > 12 else t) or "?"
                parts.append(f"{e[0].upper()}:{short}({'H' if h else 'V'})")
            if parts:
                lines.append("  " + " | ".join(parts))
            status_text.set("\n".join(lines))
        root.after(800, update_status)

    bf = ttk.Frame(main)
    bf.pack(fill=tk.X, pady=4)
    ttk.Button(bf, text="Pin current window", command=lambda: (slider.pin_current(), update_status())).pack(side=tk.LEFT, padx=(0, 6))
    ttk.Button(bf, text="Unpin (this edge)", command=lambda: (slider.unpin(), update_status())).pack(side=tk.LEFT, padx=(0, 6))
    ttk.Button(bf, text="Unpin all", command=lambda: (slider.unpin_all(), update_status())).pack(side=tk.LEFT)

    bf2 = ttk.Frame(main)
    bf2.pack(fill=tk.X, pady=4)
    ttk.Button(bf2, text="Hide (slide off)", command=lambda: (slider.hide_current(), update_status())).pack(side=tk.LEFT, padx=(0, 6))
    ttk.Button(bf2, text="Show (slide back)", command=lambda: (slider.show_current(), update_status())).pack(side=tk.LEFT)

    edge_var = tk.StringVar(value=slider.edge)

    def set_edge(e):
        def f():
            slider.set_edge(e)
            edge_var.set(e)
        return f

    ef = ttk.LabelFrame(main, text="Edge (or use Ctrl+Alt+Arrow)", padding=8)
    ef.pack(fill=tk.X, pady=10)
    ttk.Radiobutton(ef, text="Left", variable=edge_var, value=EDGE_LEFT, command=set_edge(EDGE_LEFT)).pack(anchor=tk.W)
    ttk.Radiobutton(ef, text="Right", variable=edge_var, value=EDGE_RIGHT, command=set_edge(EDGE_RIGHT)).pack(anchor=tk.W)
    ttk.Radiobutton(ef, text="Top", variable=edge_var, value=EDGE_TOP, command=set_edge(EDGE_TOP)).pack(anchor=tk.W)
    ttk.Radiobutton(ef, text="Bottom", variable=edge_var, value=EDGE_BOTTOM, command=set_edge(EDGE_BOTTOM)).pack(anchor=tk.W)

    def minimize_to_tray():
        root.withdraw()

    ttk.Button(main, text="Minimize to tray", command=minimize_to_tray).pack(pady=8)

    def on_closing():
        root.withdraw()
        # Keep app running in tray; full quit via tray Exit

    root.protocol("WM_DELETE_WINDOW", on_closing)
    update_status()

    if start_minimized:
        root.withdraw()
    else:
        root.after(100, root.deiconify)

    return root


def main():
    parser = argparse.ArgumentParser(
        description="Swooshhh: slide windows off-screen and back on edge hover.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Show the GUI control window in addition to the tray icon.",
    )
    parser.add_argument(
        "--edge",
        choices=["left", "right", "top", "bottom"],
        default="left",
        help="Screen edge to hide the window against.",
    )
    parser.add_argument(
        "--start-minimized",
        action="store_true",
        help="Start with the GUI window minimized to tray (use with --gui).",
    )
    parser.add_argument(
        "--no-tray",
        action="store_true",
        help="Run without tray icon (GUI only; window must stay open).",
    )
    args = parser.parse_args()

    # When run as .exe (PyInstaller), default to showing GUI on double-click
    if getattr(sys, "frozen", False) and not args.gui and "--gui" not in sys.argv:
        args.gui = True

    slider = WindowSlider()
    slider.set_edge(args.edge)

    hotkey_thread = threading.Thread(target=run_hotkey_thread, args=(slider,), daemon=True)
    hotkey_thread.start()

    if args.gui:
        root = run_gui(slider, start_minimized=args.start_minimized)

    if args.no_tray:
        if not args.gui:
            print("Use --gui if you use --no-tray, so the app has a window.")
            sys.exit(1)
        # GUI only, no tray: run mainloop (tray thread not started)
        root.mainloop()
        return

    icon = make_tray_icon(slider)
    if args.gui:
        icon._gui_root = root
        threading.Thread(target=icon.run, daemon=True).start()
        root.mainloop()
    else:
        icon.run()


if __name__ == "__main__":
    main()
