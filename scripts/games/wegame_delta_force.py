import ctypes
import subprocess
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import win32gui
from PIL import ImageGrab

from scripts.click import click as window_click
from scripts.screenshot import capture_window
from scripts.window import activate_window, get_window_info

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
WEGAME_EXE = Path(r"D:\WeGame\wegame.exe")
GAME_ROOT = Path(r"D:\WeGameApps\rail_apps\DeltaForce(2001918)")
CLIENT_EXE = GAME_ROOT / "DeltaForceClient.exe"
SHIPPING_EXE = GAME_ROOT / "DeltaForce" / "Binaries" / "Win64" / "DeltaForceClient-Win64-Shipping.exe"
LAUNCHER_LOG_DIR = GAME_ROOT / "WeGameLauncher" / "log"
SCREENSHOTS_DIR = ROOT_DIR / "screenshots"
CC_CONNECT_EXE = ROOT_DIR / "cc-connect.cmd"
CC_CONNECT_DATA_DIR = Path(r"C:\Users\Administrator\.cc-connect")
CC_CONNECT_PROJECT = "delta-force-skill-minimal_deaac76e"
WEGAME_WINDOW_TITLE = "WeGame"
DELTA_WINDOW_TITLE = "三角洲行动"
DEFAULT_QR_REFRESH_SCREEN = (2629, 1430)


def _run_powershell(command: str, timeout: int = 20) -> str:
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        cwd=str(ROOT_DIR),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    return (completed.stdout or "").strip()


def _visible_windows() -> List[Dict]:
    windows = []

    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title:
                windows.append({"hwnd": hwnd, "title": title})
        return True

    win32gui.EnumWindows(callback, None)
    return windows


def _process_snapshot() -> str:
    return _run_powershell(
        "Get-Process | "
        "Where-Object { $_.ProcessName -match 'DeltaForce|launcher|wegame|browser|ACE|AntiCheat|Tenio' "
        "-or $_.MainWindowTitle -match '三角洲|Delta|WeGame|腾讯游戏' } | "
        "Select-Object ProcessName,Id,MainWindowTitle,Path | ConvertTo-Json -Depth 3",
        timeout=10,
    )


def latest_launcher_log_tail(lines: int = 80) -> Optional[str]:
    if not LAUNCHER_LOG_DIR.exists():
        return None
    logs = sorted(LAUNCHER_LOG_DIR.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        return None
    latest = str(logs[0]).replace("'", "''")
    return _run_powershell(
        f"$p = '{latest}'; Get-Content -LiteralPath $p -Tail {int(lines)}",
        timeout=10,
    )


def check_mouse_injection() -> Dict:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    before = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(before))
    target_x = max(0, before.x - 7)
    target_y = max(0, before.y - 7)
    ctypes.set_last_error(0)
    ok = user32.SetCursorPos(target_x, target_y)
    err = ctypes.get_last_error()
    time.sleep(0.05)
    after = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(after))

    # Best effort restore. In restricted sessions this may fail in the same way.
    user32.SetCursorPos(before.x, before.y)
    moved = abs(after.x - target_x) <= 1 and abs(after.y - target_y) <= 1
    return {
        "requested": {"x": target_x, "y": target_y},
        "before": {"x": before.x, "y": before.y},
        "after": {"x": after.x, "y": after.y},
        "setCursorPosReturn": int(ok),
        "lastError": int(err),
        "moved": moved,
    }


def status() -> Dict:
    return {
        "paths": {
            "wegame": str(WEGAME_EXE),
            "wegameExists": WEGAME_EXE.exists(),
            "gameRoot": str(GAME_ROOT),
            "gameRootExists": GAME_ROOT.exists(),
            "client": str(CLIENT_EXE),
            "clientExists": CLIENT_EXE.exists(),
            "shipping": str(SHIPPING_EXE),
            "shippingExists": SHIPPING_EXE.exists(),
        },
        "windows": _visible_windows(),
        "processesJson": _process_snapshot(),
        "mouseInjection": check_mouse_injection(),
        "latestLauncherLogTail": latest_launcher_log_tail(),
    }


def start_wegame() -> Dict:
    if not WEGAME_EXE.exists():
        return {"started": False, "error": f"Missing {WEGAME_EXE}"}
    subprocess.Popen([str(WEGAME_EXE)], cwd=str(WEGAME_EXE.parent))
    time.sleep(5)
    return {"started": True, "status": status()}


def start_direct_client(wait_seconds: int = 60) -> Dict:
    if not CLIENT_EXE.exists():
        return {"started": False, "error": f"Missing {CLIENT_EXE}"}
    subprocess.Popen([str(CLIENT_EXE)], cwd=str(GAME_ROOT))
    samples = []
    for second in range(wait_seconds):
        time.sleep(1)
        if second in {2, 5, 10, 20, 40, wait_seconds - 1}:
            samples.append({"second": second + 1, "processesJson": _process_snapshot()})
    return {"started": True, "waitSeconds": wait_seconds, "samples": samples, "finalStatus": status()}


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _bring_launch_windows_to_front() -> None:
    for title in [DELTA_WINDOW_TITLE, WEGAME_WINDOW_TITLE]:
        activate_window(title)
        time.sleep(0.1)


def _save_window_screenshot(prefix: str, window_title: str) -> Path:
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    path = SCREENSHOTS_DIR / f"{prefix}_{_timestamp()}.jpg"
    image = capture_window(window_title)
    if image is None:
        image = ImageGrab.grab(all_screens=True)
    image.convert("RGB").save(path, format="JPEG", quality=88, optimize=True)
    return path


def _send_image(image_path: Path, message: str, project: str = CC_CONNECT_PROJECT) -> Dict:
    command = [
        str(CC_CONNECT_EXE),
        "send",
        "--data-dir",
        str(CC_CONNECT_DATA_DIR),
        "-p",
        project,
        "--image",
        str(image_path),
        "-m",
        message,
    ]
    completed = subprocess.run(
        command,
        cwd=str(ROOT_DIR),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
    )
    return {
        "command": command,
        "exitCode": completed.returncode,
        "output": (completed.stdout or "").strip(),
    }


def refresh_qr_and_send(
    message: str = "WeGame 二维码刷新后截图",
    project: str = CC_CONNECT_PROJECT,
    screen_x: int = DEFAULT_QR_REFRESH_SCREEN[0],
    screen_y: int = DEFAULT_QR_REFRESH_SCREEN[1],
    settle_ms: int = 900,
) -> Dict:
    _bring_launch_windows_to_front()
    time.sleep(0.15)

    target_title = DELTA_WINDOW_TITLE if get_window_info(DELTA_WINDOW_TITLE) else WEGAME_WINDOW_TITLE
    window_info = get_window_info(target_title)

    clicked = False
    click_mode = "screen"
    try:
        ctypes.windll.user32.SetCursorPos(int(screen_x), int(screen_y))
        time.sleep(0.02)
        ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
        time.sleep(0.02)
        ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
        clicked = True
    except Exception:
        clicked = False

    if not clicked and window_info:
        local_x = max(0, int(screen_x - window_info["left"]))
        local_y = max(0, int(screen_y - window_info["top"]))
        clicked = window_click(local_x, local_y, target_title, background=False)
        click_mode = "window"

    time.sleep(max(0, settle_ms) / 1000.0)
    screenshot_path = _save_window_screenshot("wegame_qr_refresh_send", target_title)
    send_result = _send_image(screenshot_path, message=message, project=project)

    return {
        "clicked": clicked,
        "clickMode": click_mode,
        "screenTarget": {"x": int(screen_x), "y": int(screen_y)},
        "targetWindow": target_title,
        "windowInfo": window_info,
        "settleMs": int(settle_ms),
        "screenshotPath": str(screenshot_path),
        "sendResult": send_result,
    }
