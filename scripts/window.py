import time
from typing import Optional, Tuple

import ctypes
import win32con
import win32gui


class POINT(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_long),
        ("y", ctypes.c_long),
    ]


def get_window_handle(window_title: str) -> Optional[int]:
    """
    Find window by title, preferring the largest/visible window.
    Uses DWM to get actual window bounds, not the cached/shadow bounds.
    """
    import ctypes
    import sys
    
    # Try FindWindow first (sometimes gets the right window)
    hwnd = win32gui.FindWindow(None, window_title)
    if hwnd:
        if win32gui.IsIconic(hwnd):
            return hwnd
        # Verify it's a reasonable window (not way off-screen)
        try:
            rect = win32gui.GetWindowRect(hwnd)
            left, top, right, bottom = rect
            width = right - left
            height = bottom - top
            # If window is too small or way off screen, it's probably not the right one
            if width > 100 and height > 100 and left > -1000 and top > -1000:
                return hwnd
        except Exception:
            pass
    
    # Find all windows matching the title and pick the best one
    wanted = window_title.strip().lower()
    best_hwnd = None
    best_score = 0
    
    def callback(hwnd, _):
        nonlocal best_hwnd, best_score
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title and wanted in title.strip().lower():
                if win32gui.IsIconic(hwnd):
                    best_hwnd = hwnd
                    best_score = max(best_score, 1)
                    return True
                try:
                    rect = win32gui.GetWindowRect(hwnd)
                    left, top, right, bottom = rect
                    area = (right - left) * (bottom - top)
                    # Prefer larger windows that are on-screen
                    if area > best_score and left > -1000 and top > -1000:
                        best_score = area
                        best_hwnd = hwnd
                except Exception:
                    pass
        return True
    
    win32gui.EnumWindows(callback, None)
    return best_hwnd


def find_window_by_partial_title(partial_title: str) -> Optional[str]:
    partial_title_lower = partial_title.lower()
    for window in list_windows():
        if partial_title_lower in window["title"].lower():
            return window["title"]
    return None


def get_window_rect(window_title: str) -> Optional[Tuple[int, int, int, int]]:
    hwnd = get_window_handle(window_title)
    if not hwnd:
        return None
    try:
        return win32gui.GetWindowRect(hwnd)
    except Exception:
        return None


def get_window_info(window_title: str) -> Optional[dict]:
    hwnd = get_window_handle(window_title)
    if not hwnd:
        return None
    try:
        client_rect = win32gui.GetClientRect(hwnd)
        origin = POINT(0, 0)
        if not ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(origin)):
            return None
    except Exception:
        return None

    _, _, width, height = client_rect
    return {
        "hwnd": hwnd,
        "title": win32gui.GetWindowText(hwnd),
        "left": origin.x,
        "top": origin.y,
        "width": width,
        "height": height,
    }


def activate_window(window_title: str) -> bool:
    hwnd = get_window_handle(window_title)
    if not hwnd:
        return False
    restored = False
    foreground = False
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            time.sleep(0.3)
            restored = True

        # Some games keep a 0x0 client rect immediately after SW_RESTORE.
        # SW_SHOWNORMAL gives Windows another explicit hint to rehydrate the surface.
        win32gui.ShowWindow(hwnd, win32con.SW_SHOWNORMAL)
        time.sleep(0.2)
        win32gui.BringWindowToTop(hwnd)
        try:
            win32gui.SetForegroundWindow(hwnd)
            foreground = True
        except Exception:
            foreground = False
    except Exception:
        return False

    try:
        client_rect = win32gui.GetClientRect(hwnd)
        _, _, width, height = client_rect
        return bool((foreground or restored) and width > 0 and height > 0)
    except Exception:
        return foreground or restored


def list_windows() -> list:
    windows = []

    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title:
                windows.append({"hwnd": hwnd, "title": title})
        return True

    try:
        win32gui.EnumWindows(callback, None)
    except Exception:
        return windows
    return windows
