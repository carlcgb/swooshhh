"""
Swooshhh - Slide windows off-screen and back on edge hover.

Usage:
  python swooshhh.py              # Tray only
  python swooshhh.py --gui      # GUI + tray
  python swooshhh.py --gui --start-minimized
  python swooshhh.py --edge right

Run .exe: starts minimized to tray (GUI available from tray). Build: pip install pyinstaller && build_exe.bat

Security: No network, no disk writes, no eval/exec. Uses only Win32 APIs.
"""

import argparse
import atexit
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
from PIL import Image, ImageDraw
import pystray

byref = ctypes.byref
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
WM_HOTKEY = 0x0312
WH_MOUSE_LL = 14
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_TIMER = 0x0113
WM_DESTROY = 0x0002
GA_ROOT = 2
WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
LWA_ALPHA = 0x2
CS_HREDRAW = 0x0002
CS_VREDRAW = 0x0001

# DefWindowProcW: pointer-sized args on 64-bit (avoid OverflowError in WndProc)
_DefWindowProcW = user32.DefWindowProcW
_DefWindowProcW.argtypes = (ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p)
_DefWindowProcW.restype = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long

# CallNextHookEx: same (hook handle + lParam can be 64-bit)
_CallNextHookEx = user32.CallNextHookEx
_CallNextHookEx.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
_CallNextHookEx.restype = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long

# Mouse hook state: [slider_ref] for callback; hook_handle set after install
_mouse_slider_ref = []
_mouse_hook_handle = None
_mouse_drag_hwnd = None
_hotkey_thread_id = None  # set in run_hotkey_thread so hook can PostThreadMessage
WM_APP_HIDE_TO_EDGE = 0x8001  # custom: wParam=hwnd, lParam=edge_index 0-3

# --- Config ---
EDGE_LEFT = "left"
EDGE_RIGHT = "right"
EDGE_TOP = "top"
EDGE_BOTTOM = "bottom"
EDGES = (EDGE_LEFT, EDGE_RIGHT, EDGE_TOP, EDGE_BOTTOM)
PEEK_PX = 4
TRIGGER_ZONE_PX = 14
ANIMATION_MS = 200
POLL_INTERVAL = 0.035
# If revealed window is dragged this many px away from docked position, unpin (leave window where it is)
DRAG_UNPIN_THRESHOLD_PX = 10
# Right-click title bar + drag to edge: cursor within this many px of screen edge on release
DRAG_EDGE_ZONE_PX = 50
# Hotkeys: Ctrl+Alt+Arrow = hide focused window to that edge (one window per edge, 4 max)
MOD_HOTKEY = win32con.MOD_ALT | win32con.MOD_CONTROL
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28

# Edge indicator: subtle strip on the side where a window is hidden
INDICATOR_STRIP_PX = 4
INDICATOR_ALPHA = 130
INDICATOR_COLOR_RGB = (90, 140, 190)  # soft blue-gray
INDICATOR_UPDATE_MS = 350

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


def get_virtual_screen_rect():
    """Bounding rect of all monitors (left, top, right, bottom). Use so hidden windows stay off every monitor."""
    vleft = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
    vtop = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
    vwidth = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
    vheight = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
    return (vleft, vtop, vleft + vwidth, vtop + vheight)


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


def get_root_window(hwnd):
    """Return the root (top-level) window for the given hwnd."""
    if not hwnd:
        return None
    try:
        root = user32.GetAncestor(hwnd, GA_ROOT)
        return root if root else hwnd
    except Exception:
        return hwnd


def _edge_from_cursor(x, y, vleft, vtop, vright, vbottom):
    """Return edge name if (x,y) is in the drag-to-edge zone (virtual screen), else None."""
    if x < vleft + DRAG_EDGE_ZONE_PX:
        return EDGE_LEFT
    if x > vright - DRAG_EDGE_ZONE_PX:
        return EDGE_RIGHT
    if y < vtop + DRAG_EDGE_ZONE_PX:
        return EDGE_TOP
    if y > vbottom - DRAG_EDGE_ZONE_PX:
        return EDGE_BOTTOM
    return None


def _interp_rect(r0, r1, t):
    """Linear interpolate from r0 to r1; t in [0,1]. Returns SavedRect."""
    return SavedRect(
        int(r0.left + (r1.left - r0.left) * t),
        int(r0.top + (r1.top - r0.top) * t),
        int(r0.right + (r1.right - r0.right) * t),
        int(r0.bottom + (r1.bottom - r0.bottom) * t),
    )


def _docked_rect(edge, saved, width, height, vleft, vtop, vright, vbottom):
    """Rect when window is shown but stays attached to the screen edge. Uses virtual screen for multi-monitor."""
    if edge == EDGE_LEFT:
        return SavedRect(vleft, saved.top, vleft + width, saved.bottom)
    elif edge == EDGE_RIGHT:
        return SavedRect(vright - width, saved.top, vright, saved.bottom)
    elif edge == EDGE_TOP:
        return SavedRect(saved.left, vtop, saved.right, vtop + height)
    else:  # EDGE_BOTTOM
        return SavedRect(saved.left, vbottom - height, saved.right, vbottom)


# Hotkey ids: one per edge (one window per edge, 4 total)
_HOTKEY_IDS = {1: EDGE_LEFT, 2: EDGE_RIGHT, 3: EDGE_TOP, 4: EDGE_BOTTOM}


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


def _low_level_mouse_proc(nCode, wParam, lParam):
    """Right-click on window + drag to screen edge = hide that window to that edge. Must return quickly."""
    global _mouse_drag_hwnd, _mouse_hook_handle
    if nCode >= 0 and lParam:
        try:
            info = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            x, y = info.pt.x, info.pt.y
            if wParam == WM_RBUTTONDOWN:
                hwnd = user32.WindowFromPoint(wintypes.POINT(x, y))
                root = get_root_window(hwnd)
                _mouse_drag_hwnd = root if (root and is_window_valid(root)) else None
            elif wParam == WM_RBUTTONUP:
                if _mouse_drag_hwnd is not None and _hotkey_thread_id is not None and _mouse_slider_ref:
                    try:
                        vleft, vtop, vright, vbottom = get_virtual_screen_rect()
                        edge = _edge_from_cursor(x, y, vleft, vtop, vright, vbottom)
                        if edge and is_window_valid(_mouse_drag_hwnd):
                            edge_index = EDGES.index(edge)
                            user32.PostThreadMessageW(
                                _hotkey_thread_id, WM_APP_HIDE_TO_EDGE,
                                _mouse_drag_hwnd, edge_index
                            )
                    except Exception:
                        pass
                _mouse_drag_hwnd = None
        except Exception:
            pass
    return _CallNextHookEx(_mouse_hook_handle, nCode, wParam, lParam)


def run_hotkey_thread(slider):
    """Run a message loop; hotkeys + right-click-drag-to-edge hide windows."""
    global _mouse_hook_handle, _mouse_slider_ref, _hotkey_thread_id
    _mouse_slider_ref.append(slider)
    kernel32 = ctypes.windll.kernel32
    _hotkey_thread_id = kernel32.GetCurrentThreadId()

    LRESULT = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
    MouseProc = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    mouse_cb = MouseProc(_low_level_mouse_proc)
    for hid, edge in _HOTKEY_IDS.items():
        vk = {EDGE_LEFT: VK_LEFT, EDGE_RIGHT: VK_RIGHT, EDGE_TOP: VK_UP, EDGE_BOTTOM: VK_DOWN}[edge]
        if not user32.RegisterHotKey(None, hid, MOD_HOTKEY, vk):
            pass
    _mouse_hook_handle = user32.SetWindowsHookExW(WH_MOUSE_LL, mouse_cb, None, 0)
    try:
        msg = wintypes.MSG()
        while user32.GetMessageW(byref(msg), None, 0, 0) != 0:
            if msg.message == WM_HOTKEY:
                edge = _HOTKEY_IDS.get(msg.wParam)
                if edge:
                    slider.pin_and_hide_to_edge(edge)
            elif msg.message == WM_APP_HIDE_TO_EDGE:
                try:
                    hwnd = int(msg.wParam) if msg.wParam else None
                    edge_idx = int(msg.lParam) if msg.lParam is not None else -1
                    if hwnd and 0 <= edge_idx < len(EDGES):
                        slider.pin_hwnd_and_hide_to_edge(hwnd, EDGES[edge_idx])
                except Exception:
                    pass
            user32.TranslateMessage(byref(msg))
            user32.DispatchMessageW(byref(msg))
    finally:
        _hotkey_thread_id = None
        if _mouse_hook_handle:
            user32.UnhookWindowsHookEx(_mouse_hook_handle)
        for hid in _HOTKEY_IDS:
            user32.UnregisterHotKey(None, hid)
        _mouse_slider_ref.clear()


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

    def _clear_slot(self, edge, restore=True):
        """Clear the slot. If restore=True and window was hidden, move it back to saved_rect."""
        s = self._slots[edge]
        if restore and s["hwnd"] and s["saved_rect"] and s["hidden"]:
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
        if edge not in EDGES:
            return
        with self._lock:
            self.edge = edge

    def pin_and_hide_to_edge(self, edge):
        """Pin the focused window to this edge and hide it (one window per edge; replaces existing on that edge)."""
        hwnd = get_foreground_hwnd()
        if not hwnd or not is_window_valid(hwnd):
            return False
        return self.pin_hwnd_and_hide_to_edge(hwnd, edge)

    def pin_hwnd_and_hide_to_edge(self, hwnd, edge):
        """Pin the given window to this edge and hide it (used by mouse drag-to-edge)."""
        if edge not in EDGES or not hwnd or not is_window_valid(hwnd):
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
        while not self._stop.is_set():
            vleft, vtop, vright, vbottom = get_virtual_screen_rect()
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
                        at_edge = cursor[0] < vleft + TRIGGER_ZONE_PX
                        in_range = saved.top <= cursor[1] <= saved.bottom or cursor[0] < vleft + 4
                        target_hidden = SavedRect(vleft - width + PEEK_PX, saved.top, vleft + PEEK_PX, saved.bottom)
                        visible_rect = _docked_rect(edge, saved, width, height, vleft, vtop, vright, vbottom)
                    elif edge == EDGE_RIGHT:
                        at_edge = cursor[0] > vright - TRIGGER_ZONE_PX
                        in_range = saved.top <= cursor[1] <= saved.bottom or cursor[0] > vright - 4
                        target_hidden = SavedRect(vright - PEEK_PX, saved.top, vright - PEEK_PX + width, saved.bottom)
                        visible_rect = _docked_rect(edge, saved, width, height, vleft, vtop, vright, vbottom)
                    elif edge == EDGE_TOP:
                        at_edge = cursor[1] < vtop + TRIGGER_ZONE_PX
                        in_range = saved.left <= cursor[0] <= saved.right or cursor[1] < vtop + 4
                        target_hidden = SavedRect(saved.left, vtop - height + PEEK_PX, saved.right, vtop + PEEK_PX)
                        visible_rect = _docked_rect(edge, saved, width, height, vleft, vtop, vright, vbottom)
                    else:
                        at_edge = cursor[1] > vbottom - TRIGGER_ZONE_PX
                        in_range = saved.left <= cursor[0] <= saved.right or cursor[1] > vbottom - 4
                        target_hidden = SavedRect(saved.left, vbottom - PEEK_PX, saved.right, vbottom - PEEK_PX + height)
                        visible_rect = _docked_rect(edge, saved, width, height, vleft, vtop, vright, vbottom)

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
                        # If user dragged the window away from docked position, unpin (leave window where it is)
                        if (
                            abs(rect.left - visible_rect.left) > DRAG_UNPIN_THRESHOLD_PX
                            or abs(rect.top - visible_rect.top) > DRAG_UNPIN_THRESHOLD_PX
                            or abs(rect.right - visible_rect.right) > DRAG_UNPIN_THRESHOLD_PX
                            or abs(rect.bottom - visible_rect.bottom) > DRAG_UNPIN_THRESHOLD_PX
                        ):
                            with self._lock:
                                self._clear_slot(edge, restore=False)
                            continue
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
        vleft, vtop, vright, vbottom = get_virtual_screen_rect()
        if edge == EDGE_LEFT:
            hidden_rect = SavedRect(vleft - width + PEEK_PX, saved.top, vleft + PEEK_PX, saved.bottom)
        elif edge == EDGE_RIGHT:
            hidden_rect = SavedRect(vright - PEEK_PX, saved.top, vright - PEEK_PX + width, saved.bottom)
        elif edge == EDGE_TOP:
            hidden_rect = SavedRect(saved.left, vtop - height + PEEK_PX, saved.right, vtop + PEEK_PX)
        else:
            hidden_rect = SavedRect(saved.left, vbottom - PEEK_PX, saved.right, vbottom - PEEK_PX + height)
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
        vleft, vtop, vright, vbottom = get_virtual_screen_rect()
        docked = _docked_rect(self.edge, saved, width, height, vleft, vtop, vright, vbottom)
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

    def get_edges_with_hidden(self):
        """Return set of edge names that currently have a hidden window (for edge indicators)."""
        with self._lock:
            return {
                e for e in EDGES
                if self._slots[e]["hwnd"] and self._slots[e]["hidden"]
            }


# Edge indicator overlay state (used by indicator thread and its WndProc)
_indicator_state = {}

if ctypes.sizeof(ctypes.c_void_p) == 8:
    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, ctypes.c_void_p, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM)
else:
    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM)


def _indicator_wndproc(hwnd, msg, wParam, lParam):
    """Window procedure for timer host and strip windows; on WM_TIMER updates strip visibility."""
    if msg == WM_DESTROY:
        user32.PostQuitMessage(0)
        return 0
    if msg == WM_TIMER:
        state = _indicator_state
        slider = state.get("slider")
        hwnds = state.get("hwnds")
        timer_hwnd = state.get("timer_hwnd")
        if slider and hwnds and timer_hwnd and hwnd == timer_hwnd:
            try:
                edges = slider.get_edges_with_hidden()
                vleft, vtop, vright, vbottom = get_virtual_screen_rect()
                vw = vright - vleft
                vh = vbottom - vtop
                strip = INDICATOR_STRIP_PX
                for edge, wh in hwnds.items():
                    if edge == EDGE_LEFT:
                        x, y, w, ht = vleft, vtop, strip, vh
                    elif edge == EDGE_RIGHT:
                        x, y, w, ht = vright - strip, vtop, strip, vh
                    elif edge == EDGE_TOP:
                        x, y, w, ht = vleft, vtop, vw, strip
                    else:
                        x, y, w, ht = vleft, vbottom - strip, vw, strip
                    user32.MoveWindow(wh, int(x), int(y), int(w), int(ht), 0)
                    user32.ShowWindow(wh, SW_SHOWNOACTIVATE if edge in edges else SW_HIDE)
            except Exception:
                pass
        return 0
    return _DefWindowProcW(hwnd, msg, wParam, lParam)


def _run_edge_indicators(slider):
    """Run the edge indicator overlay in a dedicated thread (message loop + 4 strip windows)."""
    state = _indicator_state
    state["slider"] = slider

    class WNDCLASSEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_uint),
            ("style", ctypes.c_uint),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", ctypes.c_void_p),
            ("hIcon", ctypes.c_void_p),
            ("hCursor", ctypes.c_void_p),
            ("hbrBackground", ctypes.c_void_p),
            ("lpszMenuName", ctypes.c_void_p),
            ("lpszClassName", ctypes.c_wchar_p),
            ("hIconSm", ctypes.c_void_p),
        ]

    r, g, b = INDICATOR_COLOR_RGB
    rgb = r | (g << 8) | (b << 16)
    brush = gdi32.CreateSolidBrush(rgb)
    if not brush:
        return

    wndproc = WNDPROC(_indicator_wndproc)
    wc = WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
    wc.style = CS_HREDRAW | CS_VREDRAW
    wc.lpfnWndProc = wndproc
    wc.hbrBackground = brush
    wc.lpszClassName = "SwooshhhIndicator"
    wc.hInstance = ctypes.c_void_p(0)
    if user32.RegisterClassExW(byref(wc)) == 0:
        gdi32.DeleteObject(brush)
        return

    ex = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST
    vleft, vtop, vright, vbottom = get_virtual_screen_rect()
    vw = vright - vleft
    vh = vbottom - vtop
    strip = INDICATOR_STRIP_PX

    # Timer host (invisible, just to run SetTimer)
    timer_hwnd = user32.CreateWindowExW(
        ex, "SwooshhhIndicator", None, WS_POPUP,
        0, 0, 1, 1, None, None, None, None
    )
    if not timer_hwnd:
        gdi32.DeleteObject(brush)
        return
    state["timer_hwnd"] = timer_hwnd

    # SetLayeredWindowAttributes for alpha (used on strip windows)
    try:
        user32.SetLayeredWindowAttributes.argtypes = (wintypes.HWND, wintypes.COLORREF, ctypes.c_byte, ctypes.c_uint)
        user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
    except Exception:
        pass

    hwnds = {}
    # Left strip
    h = user32.CreateWindowExW(
        ex, "SwooshhhIndicator", None, WS_POPUP,
        int(vleft), int(vtop), strip, int(vh), None, None, None, None
    )
    if h:
        user32.SetLayeredWindowAttributes(h, 0, INDICATOR_ALPHA, LWA_ALPHA)
        hwnds[EDGE_LEFT] = h
    # Right strip
    h = user32.CreateWindowExW(
        ex, "SwooshhhIndicator", None, WS_POPUP,
        int(vright - strip), int(vtop), strip, int(vh), None, None, None, None
    )
    if h:
        user32.SetLayeredWindowAttributes(h, 0, INDICATOR_ALPHA, LWA_ALPHA)
        hwnds[EDGE_RIGHT] = h
    # Top strip
    h = user32.CreateWindowExW(
        ex, "SwooshhhIndicator", None, WS_POPUP,
        int(vleft), int(vtop), int(vw), strip, None, None, None, None
    )
    if h:
        user32.SetLayeredWindowAttributes(h, 0, INDICATOR_ALPHA, LWA_ALPHA)
        hwnds[EDGE_TOP] = h
    # Bottom strip
    h = user32.CreateWindowExW(
        ex, "SwooshhhIndicator", None, WS_POPUP,
        int(vleft), int(vbottom - strip), int(vw), strip, None, None, None, None
    )
    if h:
        user32.SetLayeredWindowAttributes(h, 0, INDICATOR_ALPHA, LWA_ALPHA)
        hwnds[EDGE_BOTTOM] = h

    state["hwnds"] = hwnds
    user32.SetTimer(timer_hwnd, 1, INDICATOR_UPDATE_MS, None)
    # First update so strips show/hide immediately
    try:
        edges = slider.get_edges_with_hidden()
        for edge, wh in hwnds.items():
            user32.ShowWindow(wh, SW_SHOWNOACTIVATE if edge in edges else SW_HIDE)
    except Exception:
        pass

    msg = wintypes.MSG()
    while user32.GetMessageW(byref(msg), None, 0, 0) != 0:
        user32.TranslateMessage(byref(msg))
        user32.DispatchMessageW(byref(msg))

    user32.KillTimer(timer_hwnd, 1)
    for wh in hwnds.values():
        user32.DestroyWindow(wh)
    user32.DestroyWindow(timer_hwnd)
    gdi32.DeleteObject(brush)
    state.clear()


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

    def show_hide_swooshhh(icon, item):
        root = getattr(icon, "_gui_root", None)
        if not root:
            return
        try:
            if root.winfo_viewable():
                root.withdraw()
            else:
                root.deiconify()
                root.lift()
                root.focus_force()
        except Exception:
            pass

    def show_hide_swooshhh_label(icon, item):
        root = getattr(icon, "_gui_root", None)
        if not root:
            return "Show Swooshhh"
        try:
            return "Hide Swooshhh" if root.winfo_viewable() else "Show Swooshhh"
        except Exception:
            return "Show Swooshhh"

    def on_exit(icon, item):
        slider.unpin_all()
        if getattr(icon, "_gui_root", None):
            try:
                icon._gui_root.quit()
            except Exception:
                pass
        icon.stop()

    # Tray icon: use logo PNG if available, else fallback to drawn icon
    img = None
    if getattr(sys, "frozen", False):
        logo_path = os.path.join(sys._MEIPASS, "swooshhh_logo.png")
    else:
        logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "swooshhh_logo.png")
    try:
        if os.path.isfile(logo_path):
            img = Image.open(logo_path).copy()
            img = img.convert("RGB")
            img = img.resize((64, 64), getattr(Image, "Resampling", Image).LANCZOS)
    except Exception:
        pass
    if img is None:
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
        pystray.MenuItem(show_hide_swooshhh_label, show_hide_swooshhh),
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

    # When run as .exe (PyInstaller), default to GUI but start minimized in tray
    if getattr(sys, "frozen", False):
        if not args.gui and "--gui" not in sys.argv:
            args.gui = True
        if "--start-minimized" not in sys.argv:
            args.start_minimized = True

    slider = WindowSlider()
    slider.set_edge(args.edge)
    atexit.register(slider.unpin_all)  # Restore any hidden windows when process exits

    hotkey_thread = threading.Thread(target=run_hotkey_thread, args=(slider,), daemon=True)
    hotkey_thread.start()

    indicator_thread = threading.Thread(target=_run_edge_indicators, args=(slider,), daemon=True)
    indicator_thread.start()

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
