import time
from typing import Optional

import win32api
import win32con
import win32gui


VK_CODES = {
    "w": 0x57,
    "a": 0x41,
    "s": 0x53,
    "d": 0x44,
    "f": 0x46,
    "m": 0x4D,
    "tab": win32con.VK_TAB,
    "space": win32con.VK_SPACE,
    "enter": win32con.VK_RETURN,
    "escape": win32con.VK_ESCAPE,
    "esc": win32con.VK_ESCAPE,
    "shift": win32con.VK_SHIFT,
    "ctrl": win32con.VK_CONTROL,
    "alt": win32con.VK_MENU,
}


def get_vk_code(key_name: str) -> Optional[int]:
    return VK_CODES.get(key_name.lower())


def key_down(key_name: str, hwnd: Optional[int] = None) -> bool:
    vk = get_vk_code(key_name)
    if vk is None:
        print(f"[keyboard] Unknown key: {key_name}")
        return False
    if hwnd:
        win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, vk, 0)
    else:
        win32api.keybd_event(vk, 0, 0, 0)
    return True


def key_up(key_name: str, hwnd: Optional[int] = None) -> bool:
    vk = get_vk_code(key_name)
    if vk is None:
        return False
    if hwnd:
        win32gui.PostMessage(hwnd, win32con.WM_KEYUP, vk, 0)
    else:
        win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
    return True


def press_key(key_name: str, delay_ms: int = 100, hwnd: Optional[int] = None) -> bool:
    if not key_down(key_name, hwnd):
        return False
    time.sleep(delay_ms / 1000.0)
    return key_up(key_name, hwnd)


def hold_key(key_name: str, hold_ms: int, hwnd: Optional[int] = None) -> bool:
    if not key_down(key_name, hwnd):
        return False
    time.sleep(hold_ms / 1000.0)
    return key_up(key_name, hwnd)
