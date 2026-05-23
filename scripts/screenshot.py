import ctypes
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple

import win32con
import win32gui
import win32ui
from PIL import Image

from scripts.window import get_window_handle


# Set DPI awareness before any other win32 calls
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-Monitor DPI
except Exception:
    try:
        ctypes.windll.user32.SetProcessDpiAware()  # Legacy fallback
    except Exception:
        pass


ROOT_DIR = Path(__file__).resolve().parent.parent
SCREENSHOTS_DIR = ROOT_DIR / "screenshots"
SCREENSHOT_RETENTION_HOURS = 24
SCREENSHOT_CLEANUP_INTERVAL_SECONDS = 1800
dwmapi = ctypes.windll.dwmapi
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
_last_screenshot_cleanup_at: Optional[datetime] = None


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class POINT(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_long),
        ("y", ctypes.c_long),
    ]


def _safe_name(name: str) -> str:
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, "_")
    return name.replace(" ", "_")


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]


def cleanup_old_screenshots(retention_hours: int = SCREENSHOT_RETENTION_HOURS) -> dict:
    cutoff = datetime.now() - timedelta(hours=retention_hours)
    deleted_files = 0
    deleted_dirs = 0
    if not SCREENSHOTS_DIR.exists():
        return {"deletedFiles": 0, "deletedDirs": 0, "cutoff": cutoff.isoformat(timespec="seconds")}

    for path in SCREENSHOTS_DIR.rglob("*"):
        if not path.is_file():
            continue
        try:
            modified_at = datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            continue
        if modified_at >= cutoff:
            continue
        try:
            path.unlink()
            deleted_files += 1
        except OSError:
            continue

    for path in sorted(SCREENSHOTS_DIR.rglob("*"), reverse=True):
        if not path.is_dir():
            continue
        try:
            next(path.iterdir())
        except StopIteration:
            try:
                path.rmdir()
                deleted_dirs += 1
            except OSError:
                continue
        except OSError:
            continue

    return {
        "deletedFiles": deleted_files,
        "deletedDirs": deleted_dirs,
        "cutoff": cutoff.isoformat(timespec="seconds"),
    }


def maybe_cleanup_old_screenshots(
    retention_hours: int = SCREENSHOT_RETENTION_HOURS,
    interval_seconds: int = SCREENSHOT_CLEANUP_INTERVAL_SECONDS,
) -> dict:
    global _last_screenshot_cleanup_at
    now = datetime.now()
    if _last_screenshot_cleanup_at and (now - _last_screenshot_cleanup_at).total_seconds() < interval_seconds:
        return {"skipped": True, "lastCleanupAt": _last_screenshot_cleanup_at.isoformat(timespec="seconds")}
    result = cleanup_old_screenshots(retention_hours=retention_hours)
    _last_screenshot_cleanup_at = now
    result["skipped"] = False
    result["lastCleanupAt"] = now.isoformat(timespec="seconds")
    return result


def get_physical_screen_size() -> Tuple[int, int]:
    """Get the physical screen size using GetDeviceCaps (DPI aware)"""
    hdc = user32.GetDC(0)
    HORZRES = 8
    VERTRES = 10
    width = gdi32.GetDeviceCaps(hdc, HORZRES)
    height = gdi32.GetDeviceCaps(hdc, VERTRES)
    user32.ReleaseDC(0, hdc)
    return width, height


def get_window_rect_dwm(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    """Get window rectangle using DwmGetWindowAttribute for correct position"""
    try:
        rect = RECT()
        DWMWA_EXTENDED_FRAME_BOUNDS = 9
        dwmapi.DwmGetWindowAttribute(
            hwnd,
            DWMWA_EXTENDED_FRAME_BOUNDS,
            ctypes.byref(rect),
            ctypes.sizeof(rect),
        )
        return (rect.left, rect.top, rect.right, rect.bottom)
    except Exception:
        return None


def get_window_client_rect_dwm(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    """
    Get actual capturable game client area (DPI-aware, account for border).
    Returns (left, top, right, bottom) in screen coordinates.
    """
    try:
        client_rect = win32gui.GetClientRect(hwnd)
        if not client_rect:
            return None

        origin = POINT(0, 0)
        if not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
            return None

        _, _, client_width, client_height = client_rect
        left = origin.x
        top = origin.y
        right = left + client_width
        bottom = top + client_height

        return (left, top, right, bottom)
    except Exception:
        return None


def get_capture_rect(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    """Backward-compatible name for the client-area capture rectangle."""
    return get_window_client_rect_dwm(hwnd)


def capture_screen_rect(rect: Tuple[int, int, int, int]) -> Image.Image:
    left, top, right, bottom = rect
    width = right - left
    height = bottom - top

    desktop = win32gui.GetDesktopWindow()
    hwnd_dc = win32gui.GetWindowDC(desktop)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
    save_dc.SelectObject(bitmap)
    save_dc.BitBlt((0, 0), (width, height), mfc_dc, (left, top), win32con.SRCCOPY)

    bmpstr = bitmap.GetBitmapBits(True)
    import numpy as np
    img = np.frombuffer(bmpstr, dtype=np.uint8).reshape(height, width, 4)
    import cv2
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGRA2RGB)
    image = Image.fromarray(img_rgb)

    win32gui.DeleteObject(bitmap.GetHandle())
    save_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(desktop, hwnd_dc)
    return image


def get_physical_virtual_screen_rect() -> Tuple[int, int, int, int]:
    """Return the physical virtual desktop rectangle in screen coordinates."""
    SM_XVIRTUALSCREEN = 76
    SM_YVIRTUALSCREEN = 77
    SM_CXVIRTUALSCREEN = 78
    SM_CYVIRTUALSCREEN = 79
    left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    if width <= 0 or height <= 0:
        width, height = get_physical_screen_size()
        left = top = 0
    return (left, top, left + width, top + height)


def capture_desktop() -> Image.Image:
    """Capture the physical virtual desktop without logical DPI scaling."""
    return capture_screen_rect(get_physical_virtual_screen_rect())


def capture_window_by_title(window_title: str) -> Optional[Image.Image]:
    hwnd = get_window_handle(window_title)
    if not hwnd:
        return None
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        time.sleep(0.3)
    rect = get_window_client_rect_dwm(hwnd)
    if not rect:
        return None
    return capture_screen_rect(rect)


def capture_window(window_title: str) -> Optional[Image.Image]:
    """Backward-compatible helper used by launch/workflow modules."""
    return capture_window_by_title(window_title)


def capture_window_with_rect(window_title: str) -> Tuple[Optional[Image.Image], Optional[Tuple[int, int, int, int]]]:
    hwnd = get_window_handle(window_title)
    if not hwnd:
        return None, None
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        time.sleep(0.3)
    rect = get_window_client_rect_dwm(hwnd)
    if not rect:
        return None, None
    return capture_screen_rect(rect), rect


def capture_delta_force_window() -> Optional[Image.Image]:
    """
    Capture Delta Force game window with proper DPI handling.
    Tries multiple possible window titles.
    """
    # Try common Delta Force window titles
    titles = ['三角洲行动', 'Delta Force', '三角洲', 'DeltaForceClient-Win64-Sh']
    
    for title in titles:
        hwnd = get_window_handle(title)
        if hwnd:
            # Check if window is visible and not iconic
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                time.sleep(0.3)
            
            rect = get_window_client_rect_dwm(hwnd)
            if rect:
                return capture_screen_rect(rect)
    
    return None


def capture_window_by_process_name(process_name: str = "DeltaForceClient-Win64-Sh") -> Optional[Image.Image]:
    """
    Capture window by process name (useful when window title changes).
    Uses EnumWindows + GetWindowThreadProcessId to find windows by process.
    """
    import win32process
    
    pid = None
    try:
        import psutil
        for proc in psutil.process_iter(['pid', 'name']):
            if process_name.lower() in proc.info['name'].lower():
                pid = proc.info['pid']
                break
    except ImportError:
        pass
    
    if not pid:
        return None
    
    found_hwnds = []
    def callback(hwnd, results):
        try:
            _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
            if found_pid == pid and win32gui.IsWindowVisible(hwnd):
                rect = get_window_client_rect_dwm(hwnd)
                if rect:
                    results.append(hwnd)
        except Exception:
            pass
        return True
    
    win32gui.EnumWindows(callback, found_hwnds)
    
    if found_hwnds:
        # Use the first visible window
        target_hwnd = found_hwnds[0]
        if win32gui.IsIconic(target_hwnd):
            win32gui.ShowWindow(target_hwnd, win32con.SW_RESTORE)
            time.sleep(0.3)
        rect = get_window_client_rect_dwm(target_hwnd)
        if rect:
            return capture_screen_rect(rect)
    
    return None


def take_screenshot(window_title: str = "三角洲行动") -> Tuple[Optional[Image.Image], Optional[Tuple[int, int, int, int]]]:
    """
    Take screenshot of window and return image + rect.
    
    Returns:
        (Image, (left, top, right, bottom)) or (None, None)
    """
    hwnd = get_window_handle(window_title)
    if not hwnd:
        # Try to find by process
        return capture_delta_force_window(), None
    
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        time.sleep(0.3)
    
    rect = get_window_client_rect_dwm(hwnd)
    if not rect:
        return None, None
    
    return capture_screen_rect(rect), rect


def save_screenshot(image: Image.Image, subfolder: str = "misc") -> str:
    """Save screenshot to screenshots folder with timestamp."""
    maybe_cleanup_old_screenshots()
    target_dir = SCREENSHOTS_DIR / _safe_name(subfolder)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"screenshot_{_timestamp()}.png"
    image.save(path)
    return os.path.relpath(path, ROOT_DIR)


def take_desktop_screenshot(subfolder: str = "desktop") -> str:
    """Capture the full physical desktop, save it, and return a repo-relative path."""
    return save_screenshot(capture_desktop(), subfolder)


def take_screenshot(window_title: str = "三角洲行动") -> str:
    """
    Take a client-area screenshot, save it, and return a repo-relative path.

    The older implementation returned an in-memory image tuple. The CLI and game
    flows expect a saved path, so this final definition keeps that public API.
    """
    image = capture_window_by_title(window_title)
    if image is None:
        image = capture_delta_force_window()
    if image is None:
        raise RuntimeError(f'Unable to capture window: "{window_title}"')
    return save_screenshot(image, window_title)
