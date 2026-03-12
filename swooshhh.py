"""
Swooshhh – Slide windows off-screen and back on edge hover.
Uses Windows APIs only; minimal local config for start-minimized preference.
"""

import argparse
import ctypes
import math
import os
import sys
import threading
import time
from ctypes import wintypes
from collections import namedtuple

import win32api
import win32con
import win32gui
import win32process
from PIL import Image, ImageDraw
import pystray

byref = ctypes.byref
user32 = ctypes.windll.user32
WM_HOTKEY = 0x0312
WM_APP = 0x8000
SW_HIDE = 0
SW_SHOWNA = 8
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
HWND_TOPMOST = 0xFFFFFFFF
WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
GWL_EXSTYLE = -20
CS_HREDRAW = 0x0002
CS_VREDRAW = 0x0001

EDGE_LEFT = "left"
EDGE_RIGHT = "right"
EDGE_TOP = "top"
EDGE_BOTTOM = "bottom"
EDGES = (EDGE_LEFT, EDGE_RIGHT, EDGE_TOP, EDGE_BOTTOM)
PEEK_PX = 4
TRIGGER_ZONE_PX = 14
ANIMATION_MS = 200
POLL_INTERVAL = 0.035
INDICATOR_COLOR = (0x4A, 0x90, 0xD9)
INDICATOR_SIZE = 44
INDICATOR_THICKNESS = 6
HELP_TEXT = """Pin a window to an edge (Left / Right / Top / Bottom), then slide it off-screen.

• Hotkeys: Ctrl+Alt+Arrow — pin and hide in one step.
• Reveal: Hover the screen edge. A blue dot shows where a window is hidden.
• Slide back: Move the mouse off the window.
• One window per edge (max 4). Use the tray menu for Hide / Show."""

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
    flags = flags or win32con.SWP_NOACTIVATE
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


def _rects_intersect(left1, top1, right1, bottom1, left2, top2, right2, bottom2):
    return not (right1 < left2 or left1 > right2 or bottom1 < top2 or top1 > bottom2)


# Native Windows / shell window class names to exclude from the window list
_NATIVE_WINDOWS_CLASSES = frozenset({
    "Shell_TrayWnd",
    "Shell_SecondaryTrayWnd",
    "Progman",
    "WorkerW",
    "CabinetWClass",
    "ExploreWClass",
    "SearchWindow",
    "ApplicationFrameWindow",
    "Windows.UI.Core.CoreWindow",
})


def _monitor_rect_for_window(hwnd):
    """Return (left, top, right, bottom) for the monitor that contains the given window, or None to use primary."""
    try:
        MONITOR_DEFAULTTONEAREST = 2
        mon = win32api.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        info = win32api.GetMonitorInfo(mon)
        r = info["Monitor"]
        return (r[0], r[1], r[2], r[3])
    except Exception:
        return None


def get_open_windows(exclude_hwnd=None):
    """Return list of (display_title, hwnd) for visible, non-minimized top-level windows on the same monitor as the app. Excludes tray/tool windows, native Windows shell windows, and Swooshhh's own windows."""
    result = []
    title_count = {}
    if exclude_hwnd:
        rect = _monitor_rect_for_window(exclude_hwnd)
    else:
        rect = None
    if rect is None:
        sw, sh = get_primary_screen_size()
        main_left, main_top, main_right, main_bottom = 0, 0, sw, sh
    else:
        main_left, main_top, main_right, main_bottom = rect

    def enum_cb(hwnd, _):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            if win32gui.IsIconic(hwnd):
                return True
            if win32gui.GetParent(hwnd):
                return True
            if exclude_hwnd and hwnd == exclude_hwnd:
                return True
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid == os.getpid():
                    return True
            except Exception:
                pass
            try:
                if win32gui.GetClassName(hwnd) in _NATIVE_WINDOWS_CLASSES:
                    return True
            except Exception:
                pass
            try:
                ex_style = win32gui.GetWindowLong(hwnd, GWL_EXSTYLE)
                if ex_style & WS_EX_TOOLWINDOW:
                    return True
            except Exception:
                pass
            rect = win32gui.GetWindowRect(hwnd)
            if not _rects_intersect(rect[0], rect[1], rect[2], rect[3], main_left, main_top, main_right, main_bottom):
                return True
            title = (win32gui.GetWindowText(hwnd) or "").strip()
            if not title:
                return True
            key = title
            title_count[key] = title_count.get(key, 0) + 1
            if title_count[key] > 1:
                display = f"{title} [{title_count[key]}]"
            else:
                display = title
            result.append((display, hwnd))
        except Exception:
            pass
        return True

    win32gui.EnumWindows(enum_cb, None)
    return result


def _interp_rect(r0, r1, t):
    """Linear interpolate from r0 to r1; t in [0,1]. Returns SavedRect."""
    return SavedRect(
        int(r0.left + (r1.left - r0.left) * t),
        int(r0.top + (r1.top - r0.top) * t),
        int(r0.right + (r1.right - r0.right) * t),
        int(r0.bottom + (r1.bottom - r0.bottom) * t),
    )


def _docked_rect_centered(edge, width, height, sw, sh):
    """Rect when window is shown, attached to the screen edge and centered on that edge."""
    mid_y = (sh - height) // 2
    mid_x = (sw - width) // 2
    if edge == EDGE_LEFT:
        return SavedRect(0, mid_y, width, mid_y + height)
    elif edge == EDGE_RIGHT:
        return SavedRect(sw - width, mid_y, sw, mid_y + height)
    elif edge == EDGE_TOP:
        return SavedRect(mid_x, 0, mid_x + width, height)
    else:  # EDGE_BOTTOM
        return SavedRect(mid_x, sh - height, mid_x + width, sh)


def _hidden_rect_centered(edge, width, height, sw, sh):
    """Hidden rect with the peek strip centered on the screen edge."""
    mid_y = (sh - height) // 2
    mid_x = (sw - width) // 2
    if edge == EDGE_LEFT:
        return SavedRect(-width + PEEK_PX, mid_y, PEEK_PX, mid_y + height)
    elif edge == EDGE_RIGHT:
        return SavedRect(sw - PEEK_PX, mid_y, sw - PEEK_PX + width, mid_y + height)
    elif edge == EDGE_TOP:
        return SavedRect(mid_x, -height + PEEK_PX, mid_x + width, PEEK_PX)
    else:  # EDGE_BOTTOM
        return SavedRect(mid_x, sh - PEEK_PX, mid_x + width, sh - PEEK_PX + height)


_HOTKEY_IDS = {1: EDGE_LEFT, 2: EDGE_RIGHT, 3: EDGE_TOP, 4: EDGE_BOTTOM}
_indicator_hwnds = [None] * 4


def _create_edge_indicators(slider):
    global _indicator_hwnds
    try:
        sw, sh = get_primary_screen_size()
        half = INDICATOR_SIZE // 2
        t = INDICATOR_THICKNESS
        s = INDICATOR_SIZE
        positions = [
            (0, sh // 2 - half, t, s),
            (sw - t, sh // 2 - half, t, s),
            (sw // 2 - half, 0, s, t),
            (sw // 2 - half, sh - t, s, t),
        ]
        rgb = INDICATOR_COLOR
        color_ref = win32api.RGB(rgb[0], rgb[1], rgb[2])
        brush = win32gui.CreateSolidBrush(color_ref)

        def manager_wndproc(hwnd, msg, wParam, lParam):
            if msg == WM_APP + 1:
                idx = wParam & 0xFFFF
                show = lParam & 0xFFFF
                if 0 <= idx < 4 and _indicator_hwnds[idx] and win32gui.IsWindow(_indicator_hwnds[idx]):
                    ind_hwnd = _indicator_hwnds[idx]
                    win32gui.ShowWindow(ind_hwnd, win32con.SW_SHOWNA if show else win32con.SW_HIDE)
                    if show:
                        win32gui.SetWindowPos(
                            ind_hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE
                        )
                return 0
            return win32gui.DefWindowProc(hwnd, msg, wParam, lParam)

        def indicator_wndproc(hwnd, msg, wParam, lParam):
            if msg == win32con.WM_PAINT:
                try:
                    dc, ps = win32gui.BeginPaint(hwnd)
                    r = win32gui.GetClientRect(hwnd)
                    win32gui.FillRect(dc, r, brush)
                    win32gui.EndPaint(hwnd, ps)
                except Exception:
                    pass
                return 0
            return win32gui.DefWindowProc(hwnd, msg, wParam, lParam)

        hinst = win32api.GetModuleHandle(None)

        wc_mgr = win32gui.WNDCLASS()
        wc_mgr.style = win32con.CS_HREDRAW | win32con.CS_VREDRAW
        wc_mgr.lpfnWndProc = manager_wndproc
        wc_mgr.hInstance = hinst
        wc_mgr.lpszClassName = "SwooshhhIndicatorMgr"
        win32gui.RegisterClass(wc_mgr)

        manager_hwnd = win32gui.CreateWindowEx(
            0, "SwooshhhIndicatorMgr", None, 0, 0, 0, 0, 0, None, None, hinst, None
        )
        if not manager_hwnd:
            return
        slider._indicator_manager_hwnd = manager_hwnd

        wc_ind = win32gui.WNDCLASS()
        wc_ind.style = win32con.CS_HREDRAW | win32con.CS_VREDRAW
        wc_ind.lpfnWndProc = indicator_wndproc
        wc_ind.hInstance = hinst
        wc_ind.hbrBackground = brush
        wc_ind.lpszClassName = "SwooshhhIndicator"
        win32gui.RegisterClass(wc_ind)

        for i, (x, y, w, h) in enumerate(positions):
            hwnd = win32gui.CreateWindowEx(
                win32con.WS_EX_TOPMOST | win32con.WS_EX_TOOLWINDOW,
                "SwooshhhIndicator",
                None,
                win32con.WS_POPUP,
                x, y, w, h,
                None, None, hinst, None
            )
            if hwnd:
                _indicator_hwnds[i] = hwnd
                win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
        return manager_hwnd
    except Exception:
        pass


def run_hotkey_thread(slider):
    _create_edge_indicators(slider)
    for hid, edge in _HOTKEY_IDS.items():
        vk = {EDGE_LEFT: VK_LEFT, EDGE_RIGHT: VK_RIGHT, EDGE_TOP: VK_UP, EDGE_BOTTOM: VK_DOWN}[edge]
        if not user32.RegisterHotKey(None, hid, MOD_HOTKEY, vk):
            pass
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
        self.edge = EDGE_LEFT
        self._slots = {
            e: {"hwnd": None, "saved_rect": None, "hidden": False, "_polls": 0}
            for e in EDGES
        }
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def _has_any_window(self):
        return any(self._slots[e]["hwnd"] for e in EDGES)

    def pin_current(self, exclude_hwnds=None, hwnd=None):
        hwnd = hwnd if (hwnd and is_window_valid(hwnd)) else get_foreground_hwnd()
        if not hwnd or not is_window_valid(hwnd):
            return False
        if exclude_hwnds and hwnd in exclude_hwnds:
            return False
        edge = self.edge
        with self._lock:
            self._remove_hwnd_from_other_edges(hwnd, None)
            self._clear_slot(edge)
            self._slots[edge]["hwnd"] = hwnd
            self._slots[edge]["saved_rect"] = get_window_rect(hwnd)
            self._slots[edge]["hidden"] = False
            self._slots[edge]["_polls"] = 0
            self._ensure_worker()
            self._indicator_show(edge, True)
        return True

    def _clear_slot(self, edge):
        s = self._slots[edge]
        if s["hwnd"] and s["saved_rect"] and s["hidden"]:
            set_window_rect(s["hwnd"], s["saved_rect"])
            self._indicator_show(edge, False)
        s["hwnd"] = None
        s["saved_rect"] = None
        s["hidden"] = False
        s["_polls"] = 0

    def _remove_hwnd_from_other_edges(self, hwnd, except_edge):
        for e in EDGES:
            if e != except_edge and self._slots[e]["hwnd"] == hwnd:
                self._clear_slot(e)
                break

    def unpin(self):
        with self._lock:
            self._clear_slot(self.edge)
            has_any = self._has_any_window()
        if not has_any:
            self._stop_worker()

    def unpin_all(self):
        with self._lock:
            for e in EDGES:
                self._clear_slot(e)
        self._stop_worker()

    def set_edge(self, edge):
        with self._lock:
            self.edge = edge

    def pin_and_hide_to_edge(self, edge):
        hwnd = get_foreground_hwnd()
        if not hwnd or not is_window_valid(hwnd):
            return False
        with self._lock:
            self._remove_hwnd_from_other_edges(hwnd, edge)
            self._clear_slot(edge)
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
                        in_range = cursor[0] < 4 or (saved.top <= cursor[1] <= saved.bottom)
                        target_hidden = _hidden_rect_centered(edge, width, height, sw, sh)
                        visible_rect = _docked_rect_centered(edge, width, height, sw, sh)
                    elif edge == EDGE_RIGHT:
                        at_edge = cursor[0] > sw - TRIGGER_ZONE_PX
                        in_range = cursor[0] > sw - 4 or (saved.top <= cursor[1] <= saved.bottom)
                        target_hidden = _hidden_rect_centered(edge, width, height, sw, sh)
                        visible_rect = _docked_rect_centered(edge, width, height, sw, sh)
                    elif edge == EDGE_TOP:
                        at_edge = cursor[1] < TRIGGER_ZONE_PX
                        in_range = cursor[1] < 4 or (saved.left <= cursor[0] <= saved.right)
                        target_hidden = _hidden_rect_centered(edge, width, height, sw, sh)
                        visible_rect = _docked_rect_centered(edge, width, height, sw, sh)
                    else:
                        at_edge = cursor[1] > sh - TRIGGER_ZONE_PX
                        in_range = cursor[1] > sh - 4 or (saved.left <= cursor[0] <= saved.right)
                        target_hidden = _hidden_rect_centered(edge, width, height, sw, sh)
                        visible_rect = _docked_rect_centered(edge, width, height, sw, sh)

                    cursor_over_window = (
                        rect.left <= cursor[0] <= rect.right and rect.top <= cursor[1] <= rect.bottom
                    )

                    if hidden:
                        if at_edge and in_range:
                            win32gui.SetWindowPos(
                                hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE
                            )
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
                            win32gui.SetWindowPos(
                                hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE
                            )
                    else:
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
                                win32gui.SetWindowPos(
                                    hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
                                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE
                                )
                                self._indicator_show(edge, True)
                except Exception:
                    pass

            self._stop.wait(POLL_INTERVAL)

    def _hide_to_edge(self, edge):
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
        hidden_rect = _hidden_rect_centered(edge, width, height, sw, sh)
        set_window_rect(hwnd, hidden_rect)
        win32gui.SetWindowPos(
            hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE
        )
        with self._lock:
            self._slots[edge]["saved_rect"] = saved
            self._slots[edge]["hidden"] = True
        self._indicator_show(edge, True)

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
        docked = _docked_rect_centered(self.edge, width, height, sw, sh)
        set_window_rect(hwnd, docked)
        win32gui.SetWindowPos(
            hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE
        )
        with self._lock:
            self._slots[self.edge]["hidden"] = False

    def get_status(self):
        with self._lock:
            hwnd = self._slots[self.edge]["hwnd"]
            hidden = self._slots[self.edge]["hidden"]
        if not hwnd:
            return None, self.edge, False
        return get_window_title(hwnd), self.edge, hidden

    def get_status_all(self):
        with self._lock:
            out = []
            for e in EDGES:
                hwnd = self._slots[e]["hwnd"]
                if hwnd:
                    out.append((e, get_window_title(hwnd), self._slots[e]["hidden"]))
        return out

    def _indicator_show(self, edge, show):
        try:
            manager = getattr(self, "_indicator_manager_hwnd", None)
            if manager and user32.IsWindow(manager):
                idx = EDGES.index(edge)
                user32.SendMessageW(manager, WM_APP + 1, idx, 1 if show else 0)
        except Exception:
            pass


def make_tray_icon(slider):
    def on_unpin_all(icon, item):
        slider.unpin_all()
        icon.notify("Unpinned all.", "Swooshhh")

    def on_help(icon, item):
        root = getattr(icon, "_gui_root", None)
        if root and root.winfo_exists():
            from tkinter import messagebox
            root.after(0, lambda: messagebox.showinfo("Swooshhh – Help", HELP_TEXT))
        else:
            MB_OK = 0x0
            MB_ICONINFORMATION = 0x40
            MB_SETFOREGROUND = 0x10000
            ctypes.windll.user32.MessageBoxW(
                None, HELP_TEXT, "Swooshhh – Help", MB_OK | MB_ICONINFORMATION | MB_SETFOREGROUND
            )

    def on_show_gui(icon, item):
        root = getattr(icon, "_gui_root", None)
        if root and root.winfo_exists():
            root.after(0, lambda: (root.deiconify(), root.lift(), root.focus_force()))
        else:
            icon.notify("Start with GUI (run.cmd or run.cmd gui) to open the control window.", "Swooshhh")

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
        pystray.MenuItem("Unpin all", on_unpin_all),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Help", on_help),
        pystray.MenuItem("Show GUI", on_show_gui),
        pystray.MenuItem("Exit", on_exit),
    )

    icon = pystray.Icon(
        "swooshhh", img, "Swooshhh (Ctrl+Alt+Arrow = hide to edge)", menu
    )
    return icon


def _start_minimized_path():
    base = os.environ.get("APPDATA", os.path.expanduser("~"))
    return os.path.join(base, "Swooshhh", "start_minimized.txt")


def _load_start_minimized():
    try:
        p = _start_minimized_path()
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as f:
                return (f.read().strip() or "0") == "1"
    except Exception:
        pass
    return False


def _save_start_minimized(value):
    try:
        p = _start_minimized_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write("1" if value else "0")
    except Exception:
        pass


def run_gui(slider, start_minimized=False):
    import tkinter as tk
    from tkinter import ttk, messagebox

    root = tk.Tk()
    root.title("Swooshhh")
    root.minsize(320, 220)
    root.resizable(True, True)

    main = ttk.Frame(root, padding=12)
    main.pack(fill=tk.BOTH, expand=True)

    status_text = tk.StringVar(value="Focus a window, then pin it to an edge (or use Ctrl+Alt+Arrow).")
    status = ttk.Label(main, textvariable=status_text, wraplength=300)
    status.pack(anchor=tk.W, pady=(0, 10))

    def update_status():
        all_slots = slider.get_status_all()
        title, edge, hidden = slider.get_status()
        if not all_slots:
            status_text.set("Focus a window, then pin it to an edge (or use Ctrl+Alt+Arrow).")
        else:
            edge_name = edge.capitalize()
            if title:
                short = title[: 32] + "…" if len(title) > 32 else title
                status_text.set(f"{edge_name} edge: {short} · {'hidden' if hidden else 'visible'}")
            else:
                status_text.set(f"{edge_name} edge · {'hidden' if hidden else 'visible'}")
        root.after(800, update_status)

    windows_list = []

    def refresh_windows():
        nonlocal windows_list
        try:
            gui_hwnd = root.winfo_id()
            windows_list = get_open_windows(exclude_hwnd=gui_hwnd)
        except Exception:
            windows_list = []
        display_values = [t for t, _ in windows_list]
        window_combo["values"] = display_values
        if display_values and window_combo.current() < 0:
            window_combo.current(0)

    def get_selected_hwnd():
        idx = window_combo.current()
        if 0 <= idx < len(windows_list):
            return windows_list[idx][1]
        return None

    def pin_to_edge(edge):
        slider.set_edge(edge)
        hwnd = get_selected_hwnd()
        try:
            exclude = [root.winfo_id()]
        except Exception:
            exclude = None
        if not slider.pin_current(exclude_hwnds=exclude, hwnd=hwnd):
            status_text.set("Select a window from the list, then click Pin to edge.")
        update_status()

    pin_f = ttk.LabelFrame(main, text="Pin window to edge", padding=12)
    pin_f.pack(fill=tk.X, pady=6)
    row0 = ttk.Frame(pin_f)
    row0.pack(fill=tk.X, pady=(0, 8))
    ttk.Label(row0, text="Window:").pack(side=tk.LEFT, padx=(0, 6))
    window_combo = ttk.Combobox(row0, state="readonly", width=32)
    window_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
    ttk.Button(row0, text="Refresh", command=refresh_windows).pack(side=tk.LEFT)
    pin_inner = ttk.Frame(pin_f)
    pin_inner.pack(anchor=tk.CENTER)
    pad = 8
    ttk.Button(pin_inner, text="Pin top edge", command=lambda: pin_to_edge(EDGE_TOP)).grid(row=0, column=1, padx=pad, pady=(0, pad))
    ttk.Button(pin_inner, text="Pin left edge", command=lambda: pin_to_edge(EDGE_LEFT)).grid(row=1, column=0, padx=(0, pad), pady=pad)
    ttk.Button(pin_inner, text="Pin right edge", command=lambda: pin_to_edge(EDGE_RIGHT)).grid(row=1, column=2, padx=(pad, 0), pady=pad)
    ttk.Button(pin_inner, text="Pin bottom edge", command=lambda: pin_to_edge(EDGE_BOTTOM)).grid(row=2, column=1, padx=pad, pady=(pad, 0))
    pin_inner.grid_columnconfigure(1, minsize=100)
    pin_inner.grid_rowconfigure(1, minsize=36)
    root.after(300, refresh_windows)

    unpin_f = ttk.Frame(main)
    unpin_f.pack(fill=tk.X, pady=4)
    ttk.Button(unpin_f, text="Unpin all", command=lambda: (slider.unpin_all(), update_status())).pack(anchor=tk.CENTER)

    start_minimized_var = tk.BooleanVar(value=_load_start_minimized())

    def on_start_minimized_changed():
        _save_start_minimized(start_minimized_var.get())

    ttk.Checkbutton(
        main, text="Start minimized (next launch)", variable=start_minimized_var, command=on_start_minimized_changed
    ).pack(anchor=tk.W, pady=(6, 0))

    def show_help():
        messagebox.showinfo("Swooshhh – Help", HELP_TEXT)

    def minimize_to_tray():
        root.withdraw()

    bottom_f = ttk.Frame(main)
    bottom_f.pack(anchor=tk.CENTER, pady=8)
    ttk.Button(bottom_f, text="Help", command=show_help).pack(side=tk.LEFT, padx=4)
    ttk.Button(bottom_f, text="Minimize to tray", command=minimize_to_tray).pack(side=tk.LEFT, padx=4)

    def on_closing():
        root.withdraw()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    update_status()

    def center_and_show():
        root.update_idletasks()
        w = root.winfo_width()
        h = root.winfo_height()
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        root.geometry(f"+{x}+{y}")
        root.deiconify()

    if start_minimized:
        root.withdraw()
    else:
        root.withdraw()
        root.after(100, center_and_show)

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
    if getattr(sys, "frozen", False) and not args.gui and "--gui" not in sys.argv:
        args.gui = True

    slider = WindowSlider()
    slider.set_edge(args.edge)

    hotkey_thread = threading.Thread(target=run_hotkey_thread, args=(slider,), daemon=True)
    hotkey_thread.start()

    if args.gui:
        start_min = args.start_minimized or _load_start_minimized()
        root = run_gui(slider, start_minimized=start_min)

    if args.no_tray:
        if not args.gui:
            print("Use --gui if you use --no-tray, so the app has a window.")
            sys.exit(1)
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
