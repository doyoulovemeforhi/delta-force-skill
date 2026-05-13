import ctypes
import random
import time
from ctypes import wintypes
from typing import Optional, Tuple

import win32con
import win32gui

from scripts.screenshot import get_capture_rect, get_window_rect_dwm
from scripts.window import get_window_handle


# Set DPI awareness before any other win32 calls
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-Monitor DPI
except Exception:
    try:
        ctypes.windll.user32.SetProcessDpiAware()  # Legacy fallback
    except Exception:
        pass


user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
dwmapi = ctypes.windll.dwmapi


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long)
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", INPUTUNION)]


INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


def get_physical_screen_size() -> Tuple[int, int]:
    """Get the physical screen size using GetDeviceCaps (DPI aware)"""
    hdc = user32.GetDC(0)
    HORZRES = 8
    VERTRES = 10
    width = gdi32.GetDeviceCaps(hdc, HORZRES)
    height = gdi32.GetDeviceCaps(hdc, VERTRES)
    user32.ReleaseDC(0, hdc)
    return width, height


def _send_mouse(flags: int, x: int = 0, y: int = 0) -> None:
    inputs = (INPUT * 1)()
    inputs[0].type = INPUT_MOUSE
    inputs[0].mi.dx = x
    inputs[0].mi.dy = y
    inputs[0].mi.dwFlags = flags
    user32.SendInput(1, ctypes.byref(inputs), ctypes.sizeof(INPUT))


def _move_mouse(screen_x: int, screen_y: int) -> None:
    normalized_x, normalized_y = normalize_virtual_screen_coords(screen_x, screen_y)
    _send_mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, normalized_x, normalized_y)


def normalize_virtual_screen_coords(screen_x: int, screen_y: int) -> Tuple[int, int]:
    """Convert physical screen coordinates into SendInput absolute coords."""
    SM_XVIRTUALSCREEN = 76
    SM_YVIRTUALSCREEN = 77
    SM_CXVIRTUALSCREEN = 78
    SM_CYVIRTUALSCREEN = 79

    virtual_left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    virtual_top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    virtual_width = max(1, user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
    virtual_height = max(1, user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))

    normalized_x = int(round((screen_x - virtual_left) * 65535 / max(1, virtual_width - 1)))
    normalized_y = int(round((screen_y - virtual_top) * 65535 / max(1, virtual_height - 1)))
    return normalized_x, normalized_y


def _make_lparam(x: int, y: int) -> int:
    return (y << 16) | (x & 0xFFFF)


def get_client_rect(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    """Get client rect of window"""
    try:
        return win32gui.GetClientRect(hwnd)
    except Exception:
        return None


def get_capture_rect_enhanced(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    """
    Get actual capturable game area (client area on screen).
    Uses DwmGetWindowAttribute to get the real window position including DWM decorations.
    """
    return get_capture_rect(hwnd)


def wait_for_clickable_rect(hwnd: int, attempts: int = 10, delay: float = 0.12) -> Optional[Tuple[int, int, int, int]]:
    """Restore the window if needed and wait until its client area has a usable size."""
    for _ in range(attempts):
        try:
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        except Exception:
            pass

        rect = get_capture_rect_enhanced(hwnd)
        if rect:
            left, top, right, bottom = rect
            if right > left and bottom > top:
                return rect
        time.sleep(delay)
    return None


def get_window_info(window_title: str) -> Optional[dict]:
    """Get comprehensive window info"""
    hwnd = get_window_handle(window_title)
    if not hwnd:
        return None
    
    capture_rect = wait_for_clickable_rect(hwnd)
    if not capture_rect:
        return None
    
    left, top, right, bottom = capture_rect
    return {
        'hwnd': hwnd,
        'left': left,
        'top': top,
        'width': right - left,
        'height': bottom - top
    }


def activate_window(hwnd: int) -> bool:
    """Activate window to foreground"""
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.05)
        return True
    except Exception:
        return False


def click_foreground_sendinput(x: int, y: int) -> bool:
    """Click in foreground using SendInput"""
    if x == 0 and y == 0:
        return False
    
    normalized_x, normalized_y = normalize_virtual_screen_coords(x, y)
    _send_mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, normalized_x, normalized_y)
    time.sleep(0.01)
    
    # Left button down
    _send_mouse(MOUSEEVENTF_LEFTDOWN)
    time.sleep(0.02 + random.random() * 0.01)
    
    # Left button up
    _send_mouse(MOUSEEVENTF_LEFTUP)
    
    return True


def click_background(hwnd: int, x: int, y: int) -> bool:
    """Click in background using PostMessage"""
    try:
        lparam = _make_lparam(x, y)
        win32gui.PostMessage(hwnd, win32con.WM_ACTIVATE, 1, 0)
        time.sleep(0.01)
        win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, 1, lparam)
        time.sleep(0.1)
        win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lparam)
        return True
    except Exception:
        return False


def click(x: int, y: int, window_title: str, background: bool = False) -> bool:
    """
    Unified click interface using DPI-aware coordinates.
    
    Args:
        x: X coordinate (in window client coordinate system)
        y: Y coordinate (in window client coordinate system)
        window_title: Window title to find
        background: Use background (PostMessage) or foreground (SendInput) click
    
    Returns:
        Success boolean
    """
    hwnd = get_window_handle(window_title)
    if not hwnd:
        print(f'[click] Window not found: "{window_title}"')
        return False

    if not background:
        activate_window(hwnd)

    rect = wait_for_clickable_rect(hwnd)
    if not rect:
        print("[click] Could not resolve window client rect")
        return False

    left, top, right, bottom = rect
    width = right - left
    height = bottom - top
    
    if x < 0 or y < 0 or x >= width or y >= height:
        print(f"[click] Coordinate out of bounds: ({x}, {y}) for {width}x{height}")
        return False

    # Calculate actual screen coordinates
    screen_x = left + x
    screen_y = top + y

    if background:
        return click_background(hwnd, x, y)
    else:
        time.sleep(0.05 + random.random() * 0.03)
        return click_foreground_sendinput(screen_x, screen_y)


def right_click(x: int, y: int, window_title: Optional[str] = None, background: bool = False) -> bool:
    """Right click at coordinates"""
    print(f'[click] Right click: ({x}, {y})')
    
    if window_title:
        win_info = get_window_info(window_title)
        if not win_info:
            print(f'[click] Window not found: {window_title}')
            return False
        
        screen_x = win_info['left'] + x
        screen_y = win_info['top'] + y
        
        if background:
            lparam = _make_lparam(x, y)
            win32gui.PostMessage(win_info['hwnd'], win32con.WM_ACTIVATE, 1, 0)
            time.sleep(0.01)
            win32gui.PostMessage(win_info['hwnd'], win32con.WM_RBUTTONDOWN, 1, lparam)
            time.sleep(0.1)
            win32gui.PostMessage(win_info['hwnd'], win32con.WM_RBUTTONUP, 0, lparam)
            return True
        else:
            activate_window(win_info['hwnd'])
            time.sleep(0.05)
            normalized_x, normalized_y = normalize_virtual_screen_coords(screen_x, screen_y)
            _send_mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, normalized_x, normalized_y)
            time.sleep(0.02)
            _send_mouse(0x0008)  # RIGHTDOWN
            time.sleep(0.02)
            _send_mouse(0x0010)  # RIGHTUP
            return True
    else:
        normalized_x, normalized_y = normalize_virtual_screen_coords(x, y)
        _send_mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, normalized_x, normalized_y)
        time.sleep(0.02)
        _send_mouse(0x0008)
        time.sleep(0.02)
        _send_mouse(0x0010)
        return True
