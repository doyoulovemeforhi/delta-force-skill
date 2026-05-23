import ctypes
import re
import shutil
import subprocess
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import win32gui
import win32con
import win32process
import cv2
import numpy as np
from PIL import ImageGrab

from scripts.click import click as window_click
from scripts.rapidocr_reader import read_rapidocr_items
from scripts.screenshot import capture_screen_rect, capture_window, get_window_client_rect_dwm
from scripts.window import activate_window, get_window_info

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
ASSETS_DIR = ROOT_DIR / "games" / "delta-force" / "assets"
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
WEGAME_PROCESS_NAME = "wegame.exe"
DELTA_WINDOW_TITLE = "三角洲行动"
DEFAULT_QR_REFRESH_SCREEN = (2629, 1430)
LOGIN_TEXT_CANDIDATES = ("重新登录", "启动", "开始游戏", "进入游戏", "更新", "继续更新")
DELTA_GAME_TEXT_CANDIDATES = ("三角洲行动",)
LAUNCH_GAME_TEXT_CANDIDATES = ("启动", "开始游戏", "进入游戏", "更新", "继续更新")
QR_LOGIN_TEXT_CANDIDATES = ("QQ扫码登录", "扫码登录", "快捷安全登录")
QR_LOGIN_TEXT_BY_CHANNEL = {
    "qq": ("QQ扫码登录", "扫码登录", "快捷安全登录"),
    "wechat": ("微信扫码登录", "微信登录", "扫码登录", "快捷安全登录"),
}
QR_TAB_RATIOS = {
    "qq": (0.473, 0.514),
    "wechat": (0.527, 0.514),
}
QR_REFRESH_TEXT_CANDIDATES = ("刷新", "点击刷新", "二维码已过期")
QR_REFRESH_ARROW_TEMPLATE = ASSETS_DIR / "buttons" / "wegame_qr_refresh_arrow.png"


def _texts_have_qr_state(texts: List[str]) -> bool:
    return any(("二维码" in str(text) or "微信" in str(text) or "扫码" in str(text)) for text in texts)


def _texts_have_expired_qr_state(texts: List[str]) -> bool:
    return any(("失效" in str(text) or "过期" in str(text) or "刷新" in str(text)) for text in texts)


def _texts_have_account_password_state(texts: List[str]) -> bool:
    return any(("请输入密码" in str(text) or "账号密码登录" in str(text) or "自动登录" in str(text)) for text in texts)


def _resolve_cc_connect_exe() -> Optional[str]:
    if CC_CONNECT_EXE.exists():
        return str(CC_CONNECT_EXE)
    return shutil.which("cc-connect.cmd") or shutil.which("cc-connect")


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


def _find_visible_window_by_process_name(process_name: str) -> Optional[int]:
    try:
        import psutil
    except ImportError:
        return None

    wanted = process_name.lower()
    pids = set()
    for proc in psutil.process_iter(["pid", "name"]):
        name = (proc.info.get("name") or "").lower()
        if name == wanted or name.startswith(wanted.replace(".exe", "")):
            pids.add(proc.info["pid"])
    if not pids:
        return None

    candidates = []

    def callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid not in pids:
                return True
            rect = get_window_client_rect_dwm(hwnd)
            if not rect:
                return True
            left, top, right, bottom = rect
            area = max(0, right - left) * max(0, bottom - top)
            if area > 10000:
                candidates.append((area, hwnd))
        except Exception:
            pass
        return True

    win32gui.EnumWindows(callback, None)
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def _find_visible_window_by_title(title: str) -> Optional[int]:
    wanted = title.strip().lower()
    candidates = []

    def callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        window_title = win32gui.GetWindowText(hwnd)
        if not window_title or wanted not in window_title.strip().lower():
            return True
        try:
            rect = get_window_client_rect_dwm(hwnd)
            if not rect:
                return True
            left, top, right, bottom = rect
            area = max(0, right - left) * max(0, bottom - top)
            if area > 10000:
                candidates.append((area, hwnd))
        except Exception:
            pass
        return True

    win32gui.EnumWindows(callback, None)
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def _find_wegame_window_handle() -> Optional[int]:
    return _find_visible_window_by_process_name(WEGAME_PROCESS_NAME) or _find_visible_window_by_title(WEGAME_WINDOW_TITLE)


def _activate_hwnd(hwnd: int) -> bool:
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            time.sleep(0.2)
        win32gui.ShowWindow(hwnd, win32con.SW_SHOWNORMAL)
        win32gui.BringWindowToTop(hwnd)
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        return True
    except Exception:
        return False


def _capture_hwnd(hwnd: int):
    _activate_hwnd(hwnd)
    rect = get_window_client_rect_dwm(hwnd)
    if not rect:
        return None, None
    return capture_screen_rect(rect), rect


def _click_hwnd_client(hwnd: int, x: int, y: int) -> bool:
    image, rect = _capture_hwnd(hwnd)
    if not rect:
        return False
    left, top, right, bottom = rect
    if x < 0 or y < 0 or x >= right - left or y >= bottom - top:
        return False
    ctypes.windll.user32.SetCursorPos(int(left + x), int(top + y))
    time.sleep(0.02)
    ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.03)
    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
    return True


def _click_wegame_ratio(x_ratio: float, y_ratio: float) -> Dict:
    hwnd = _find_wegame_window_handle()
    if not hwnd:
        return {"success": False, "clicked": False, "reason": "wegame_window_not_found"}
    image, rect = _capture_hwnd(hwnd)
    if image is None or not rect:
        return {"success": False, "clicked": False, "reason": "wegame_capture_failed"}
    width, height = image.size
    x = int(width * x_ratio)
    y = int(height * y_ratio)
    clicked = _click_hwnd_client(hwnd, x, y)
    time.sleep(0.8)
    return {
        "success": bool(clicked),
        "clicked": bool(clicked),
        "x": x,
        "y": y,
        "windowSize": {"width": width, "height": height},
    }


def switch_login_channel(channel: str = "qq") -> Dict:
    normalized = (channel or "qq").strip().lower()
    if normalized in {"wx", "weixin", "wechat"}:
        normalized = "wechat"
    elif normalized != "qq":
        normalized = "qq"
    ratio = QR_TAB_RATIOS[normalized]
    result = _click_wegame_ratio(ratio[0], ratio[1])
    result["channel"] = normalized
    result["action"] = "switch_login_channel"
    return result


def _load_cv_image(path: Path):
    if not path.exists():
        return None
    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def _match_qr_refresh_arrow(image) -> Optional[Dict]:
    template = _load_cv_image(QR_REFRESH_ARROW_TEMPLATE)
    if template is None or image is None:
        return None

    source = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)
    source_h, source_w = source.shape[:2]
    # The QR code stays in the center of the WeGame login dialog. Searching only
    # this area prevents accidental matches on other circular UI icons.
    roi_x = int(source_w * 0.38)
    roi_y = int(source_h * 0.50)
    roi_w = int(source_w * 0.24)
    roi_h = int(source_h * 0.24)
    roi = source[roi_y : roi_y + roi_h, roi_x : roi_x + roi_w]
    if roi.size == 0:
        return None

    best = None
    source_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    for scale in (0.75, 0.875, 1.0, 1.125, 1.25, 1.5):
        tw = max(1, int(template.shape[1] * scale))
        th = max(1, int(template.shape[0] * scale))
        if tw >= roi_w or th >= roi_h:
            continue
        resized = cv2.resize(template, (tw, th), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
        template_gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        result = cv2.matchTemplate(source_gray, template_gray, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        candidate = {
            "x": int(roi_x + max_loc[0] + tw / 2),
            "y": int(roi_y + max_loc[1] + th / 2),
            "width": int(tw),
            "height": int(th),
            "confidence": round(float(max_val), 4),
            "scale": scale,
            "roi": {"x": roi_x, "y": roi_y, "width": roi_w, "height": roi_h},
        }
        if best is None or candidate["confidence"] > best["confidence"]:
            best = candidate

    if best and best["confidence"] >= 0.72:
        return best
    return None


def refresh_qr_by_arrow_template(target_title: Optional[str] = None) -> Dict:
    title = target_title or _choose_launch_window_title()
    hwnd = _find_wegame_window_handle() if title == WEGAME_WINDOW_TITLE else None
    if hwnd:
        image, _ = _capture_hwnd(hwnd)
    else:
        activate_window(title)
        time.sleep(0.3)
        image = capture_window(title)
    if image is None:
        return {"success": False, "clicked": False, "targetWindow": title, "reason": "window_capture_failed"}

    target = _match_qr_refresh_arrow(image)
    if not target:
        return {"success": False, "clicked": False, "targetWindow": title, "reason": "arrow_template_not_found"}

    if hwnd:
        clicked = _click_hwnd_client(hwnd, target["x"], target["y"])
    else:
        clicked = window_click(target["x"], target["y"], title, background=False)
    time.sleep(0.8)
    return {"success": bool(clicked), "clicked": bool(clicked), "targetWindow": title, "target": target}


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
    if get_window_info(DELTA_WINDOW_TITLE):
        activate_window(DELTA_WINDOW_TITLE)
        time.sleep(0.1)
    hwnd = _find_wegame_window_handle()
    if hwnd:
        _activate_hwnd(hwnd)
        time.sleep(0.1)


def _has_wegame_window() -> bool:
    return bool(_find_wegame_window_handle())


def _save_window_screenshot(prefix: str, window_title: str) -> Path:
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    path = SCREENSHOTS_DIR / f"{prefix}_{_timestamp()}.jpg"
    image = None
    if window_title == WEGAME_WINDOW_TITLE:
        hwnd = _find_wegame_window_handle()
        if hwnd:
            image, _ = _capture_hwnd(hwnd)
    if image is None:
        image = capture_window(window_title)
    if image is None:
        image = ImageGrab.grab(all_screens=True)
    image.convert("RGB").save(path, format="JPEG", quality=88, optimize=True)
    return path


def _send_image(image_path: Path, message: str, project: str = CC_CONNECT_PROJECT) -> Dict:
    cc_connect = _resolve_cc_connect_exe()
    if not cc_connect:
        return {
            "command": None,
            "exitCode": 1,
            "output": "cc-connect.cmd not found in repo root or PATH",
        }
    command = [
        cc_connect,
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


def _normalize_ocr_text(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").lower())


def _ocr_items_for_window(window_title: str) -> Dict:
    hwnd = None
    image = None
    if window_title == WEGAME_WINDOW_TITLE:
        hwnd = _find_wegame_window_handle()
        if hwnd:
            image, _ = _capture_hwnd(hwnd)
    if image is None:
        image = capture_window(window_title)
    if image is None:
        image = ImageGrab.grab(all_screens=True)
    try:
        ocr = read_rapidocr_items(image)
    except Exception as exc:
        return {"success": False, "reason": "rapidocr_error", "error": str(exc), "items": []}
    return {"success": True, "image": image, "items": ocr.get("items", []), "engine": ocr.get("engine"), "hwnd": hwnd}


def _find_text_candidate(items: List[Dict], texts) -> Optional[Dict]:
    normalized_targets = [_normalize_ocr_text(text) for text in texts if text]
    best = None
    best_score = -1.0
    for item in items:
        raw = item.get("text") or ""
        normalized = _normalize_ocr_text(raw)
        if not normalized:
            continue
        score = 0.0
        for target in normalized_targets:
            if not target:
                continue
            if normalized == target:
                score = max(score, 3.0)
            elif target in normalized:
                score = max(score, 2.0)
        if score <= 0:
            continue
        score += float(item.get("score") or 0)
        box = item.get("box") or {}
        candidate = {
            "text": raw,
            "score": round(score, 4),
            "ocrScore": item.get("score"),
            "x": int(box.get("x") or 0),
            "y": int(box.get("y") or 0),
            "box": box,
        }
        if score > best_score:
            best_score = score
            best = candidate
    return best


def click_wegame_text_by_ocr(texts=None, window_title: str = WEGAME_WINDOW_TITLE, settle_seconds: float = 0.8) -> Dict:
    candidates = tuple(texts or LOGIN_TEXT_CANDIDATES)
    activate_window(window_title)
    time.sleep(0.3)
    ocr = _ocr_items_for_window(window_title)
    if not ocr.get("success"):
        return {"success": False, "clicked": False, "reason": ocr.get("reason"), "error": ocr.get("error")}
    target = _find_text_candidate(ocr.get("items", []), candidates)
    if not target:
        return {
            "success": False,
            "clicked": False,
            "reason": "ocr_text_not_found",
            "targets": list(candidates),
            "ocrTexts": [item.get("text") for item in ocr.get("items", [])],
        }
    if ocr.get("hwnd"):
        clicked = _click_hwnd_client(int(ocr["hwnd"]), target["x"], target["y"])
    else:
        clicked = window_click(target["x"], target["y"], window_title, background=False)
    time.sleep(max(0.0, settle_seconds))
    return {
        "success": bool(clicked),
        "clicked": bool(clicked),
        "target": target,
        "targets": list(candidates),
        "windowTitle": window_title,
    }


def _click_wegame_ocr_candidate(texts, prefer_last: bool = False, settle_seconds: float = 0.8) -> Dict:
    hwnd = _find_wegame_window_handle()
    if not hwnd:
        return {"success": False, "clicked": False, "reason": "wegame_window_not_found", "targets": list(texts)}
    image, _ = _capture_hwnd(hwnd)
    if image is None:
        return {"success": False, "clicked": False, "reason": "wegame_capture_failed", "targets": list(texts)}
    try:
        ocr = read_rapidocr_items(image)
    except Exception as exc:
        return {"success": False, "clicked": False, "reason": "rapidocr_error", "error": str(exc), "targets": list(texts)}

    candidates = []
    normalized_targets = [_normalize_ocr_text(text) for text in texts if text]
    for item in ocr.get("items", []):
        normalized = _normalize_ocr_text(item.get("text") or "")
        if not normalized:
            continue
        if any(normalized == target or target in normalized for target in normalized_targets):
            box = item.get("box") or {}
            candidates.append({
                "text": item.get("text"),
                "ocrScore": item.get("score"),
                "x": int(box.get("x") or 0),
                "y": int(box.get("y") or 0),
                "box": box,
            })
    if not candidates:
        return {
            "success": False,
            "clicked": False,
            "reason": "ocr_text_not_found",
            "targets": list(texts),
            "ocrTexts": [item.get("text") for item in ocr.get("items", [])],
        }
    candidates.sort(key=lambda item: ((item.get("box") or {}).get("y", 0), (item.get("box") or {}).get("x", 0)))
    target = candidates[-1] if prefer_last else candidates[0]
    clicked = _click_hwnd_client(hwnd, target["x"], target["y"])
    time.sleep(max(0.0, settle_seconds))
    return {
        "success": bool(clicked),
        "clicked": bool(clicked),
        "target": target,
        "targets": list(texts),
        "candidateCount": len(candidates),
    }


def _wait_for_delta_window(wait_seconds: int = 90) -> Dict:
    deadline = time.time() + max(1, wait_seconds)
    samples = []
    while time.time() < deadline:
        info = get_window_info(DELTA_WINDOW_TITLE)
        if info:
            activate_window(DELTA_WINDOW_TITLE)
            return {"success": True, "windowInfo": info, "samples": samples}
        samples.append({"at": _timestamp(), "processesJson": _process_snapshot()})
        time.sleep(3)
    return {"success": False, "reason": "delta_window_not_visible", "samples": samples[-5:]}


def wait_for_wegame_logged_in(wait_seconds: int = 180) -> Dict:
    deadline = time.time() + max(1, wait_seconds)
    last_texts = []
    logged_in_markers = ("我的游戏", "三角洲行动", "商店", "精选")
    login_markers = ("扫码登录", "请输入密码", "二维码", "账号密码登录")
    while time.time() < deadline:
        if not _has_wegame_window():
            time.sleep(2)
            continue
        ocr = _ocr_items_for_window(WEGAME_WINDOW_TITLE)
        texts = [str(item.get("text") or "") for item in ocr.get("items", [])]
        last_texts = texts
        has_logged_in_marker = any(marker in text for marker in logged_in_markers for text in texts)
        has_login_marker = any(marker in text for marker in login_markers for text in texts)
        if has_logged_in_marker and not has_login_marker:
            return {"success": True, "ocrTexts": texts}
        time.sleep(3)
    return {"success": False, "reason": "wegame_login_wait_timeout", "ocrTexts": last_texts}


def launch_delta_from_wegame(wait_seconds: int = 120) -> Dict:
    steps: List[Dict] = []
    existing = get_window_info(DELTA_WINDOW_TITLE)
    if existing:
        activate_window(DELTA_WINDOW_TITLE)
        return {"success": True, "alreadyRunning": True, "windowInfo": existing, "steps": steps}

    if not _has_wegame_window():
        steps.append({"action": "start_wegame", **start_wegame()})
    _bring_launch_windows_to_front()

    game_click = _click_wegame_ocr_candidate(DELTA_GAME_TEXT_CANDIDATES, prefer_last=True, settle_seconds=2.5)
    game_click["action"] = "click_delta_game_entry"
    steps.append(game_click)

    launch_click = _click_wegame_ocr_candidate(LAUNCH_GAME_TEXT_CANDIDATES, prefer_last=True, settle_seconds=2.0)
    launch_click["action"] = "click_launch_button_by_ocr"
    steps.append(launch_click)
    if not launch_click.get("clicked"):
        fallback = _click_wegame_ratio(0.86, 0.94)
        fallback["action"] = "click_launch_button_by_ratio"
        steps.append(fallback)

    wait_result = _wait_for_delta_window(wait_seconds=wait_seconds)
    steps.append({"action": "wait_for_delta_window", **wait_result})
    return {
        "success": bool(wait_result.get("success")),
        "alreadyRunning": False,
        "windowInfo": wait_result.get("windowInfo"),
        "steps": steps,
    }


def _choose_launch_window_title() -> str:
    if _has_wegame_window():
        return WEGAME_WINDOW_TITLE
    return DELTA_WINDOW_TITLE if get_window_info(DELTA_WINDOW_TITLE) else WEGAME_WINDOW_TITLE


def refresh_qr_by_ocr(target_title: Optional[str] = None) -> Dict:
    title = target_title or _choose_launch_window_title()
    activate_window(title)
    time.sleep(0.3)
    ocr = _ocr_items_for_window(title)
    if not ocr.get("success"):
        return {"success": False, "clicked": False, "targetWindow": title, "reason": ocr.get("reason"), "error": ocr.get("error")}
    target = _find_text_candidate(ocr.get("items", []), QR_REFRESH_TEXT_CANDIDATES)
    if not target:
        return {
            "success": False,
            "clicked": False,
            "targetWindow": title,
            "reason": "ocr_refresh_text_not_found",
            "ocrTexts": [item.get("text") for item in ocr.get("items", [])],
        }
    if ocr.get("hwnd"):
        clicked = _click_hwnd_client(int(ocr["hwnd"]), target["x"], target["y"])
    else:
        clicked = window_click(target["x"], target["y"], title, background=False)
    time.sleep(0.8)
    return {"success": bool(clicked), "clicked": bool(clicked), "targetWindow": title, "target": target}


def refresh_qr_and_send(
    message: str = "WeGame 二维码刷新后截图",
    project: str = CC_CONNECT_PROJECT,
    screen_x: int = DEFAULT_QR_REFRESH_SCREEN[0],
    screen_y: int = DEFAULT_QR_REFRESH_SCREEN[1],
    settle_ms: int = 900,
    login_channel: str = "qq",
) -> Dict:
    _bring_launch_windows_to_front()
    time.sleep(0.15)

    channel_switch = switch_login_channel(login_channel)
    target_title = WEGAME_WINDOW_TITLE if _has_wegame_window() else DELTA_WINDOW_TITLE
    preflight = {"action": "ensure_qr_page", "clicked": False}
    if login_channel == "qq" and _has_wegame_window():
        state_ocr = _ocr_items_for_window(WEGAME_WINDOW_TITLE)
        state_texts = [item.get("text") for item in state_ocr.get("items", [])]
        if _texts_have_account_password_state(state_texts):
            qr_entry = _find_text_candidate(state_ocr.get("items", []), ("QQ扫码登录",))
            if qr_entry:
                if state_ocr.get("hwnd"):
                    entry_clicked = _click_hwnd_client(int(state_ocr["hwnd"]), qr_entry["x"], qr_entry["y"])
                else:
                    entry_clicked = window_click(qr_entry["x"], qr_entry["y"], WEGAME_WINDOW_TITLE, background=False)
                preflight = {
                    "action": "ensure_qr_page",
                    "clicked": bool(entry_clicked),
                    "target": qr_entry,
                    "ocrTexts": state_texts,
                }
                time.sleep(2)
    window_info = get_window_info(target_title)

    clicked = False
    click_mode = "template"
    template_refresh = refresh_qr_by_arrow_template(target_title)
    clicked = bool(template_refresh.get("clicked"))

    ocr_refresh = {"skipped": True, "reason": "template_refresh_clicked"}
    if not clicked:
        click_mode = "ocr"
        ocr_refresh = refresh_qr_by_ocr(target_title)
        clicked = bool(ocr_refresh.get("clicked"))

    allow_coordinate_fallback = True
    if not clicked and _has_wegame_window():
        state_ocr = _ocr_items_for_window(WEGAME_WINDOW_TITLE)
        state_texts = [item.get("text") for item in state_ocr.get("items", [])]
        if _texts_have_qr_state(state_texts) and not _texts_have_expired_qr_state(state_texts):
            click_mode = "send_only"
            clicked = False
            allow_coordinate_fallback = False
            ocr_refresh = {
                "skipped": True,
                "reason": "qr_visible_and_not_expired",
                "ocrTexts": state_texts,
            }

    if not clicked and allow_coordinate_fallback and window_info:
        local_x = max(0, int(screen_x - window_info["left"]))
        local_y = max(0, int(screen_y - window_info["top"]))
        clicked = window_click(local_x, local_y, target_title, background=False)
        click_mode = "window"

    if not clicked and allow_coordinate_fallback:
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

    time.sleep(max(0, settle_ms) / 1000.0)
    screenshot_path = _save_window_screenshot("wegame_qr_refresh_send", target_title)
    send_result = _send_image(screenshot_path, message=message, project=project)

    return {
        "clicked": clicked,
        "clickMode": click_mode,
        "loginChannel": channel_switch.get("channel"),
        "channelSwitch": channel_switch,
        "preflight": preflight,
        "templateRefresh": template_refresh,
        "ocrRefresh": ocr_refresh,
        "screenTarget": {"x": int(screen_x), "y": int(screen_y)},
        "targetWindow": target_title,
        "windowInfo": window_info,
        "settleMs": int(settle_ms),
        "screenshotPath": str(screenshot_path),
        "sendResult": send_result,
    }


def login_flow_ocr(
    message: str = "WeGame 登录二维码",
    project: str = CC_CONNECT_PROJECT,
    wait_seconds: int = 60,
    qr_refresh_seconds: int = 60,
    login_channel: str = "qq",
) -> Dict:
    steps: List[Dict] = []
    normalized_channel = (login_channel or "qq").strip().lower()
    if normalized_channel in {"wx", "weixin", "wechat"}:
        normalized_channel = "wechat"
    elif normalized_channel != "qq":
        normalized_channel = "qq"
    if not _has_wegame_window():
        steps.append({"action": "start_wegame", **start_wegame()})
    else:
        hwnd = _find_wegame_window_handle()
        if hwnd:
            _activate_hwnd(hwnd)
        steps.append({"action": "activate_wegame", "success": True})

    launch_title = _choose_launch_window_title()
    launch_click = None
    initial_ocr = _ocr_items_for_window(launch_title)
    initial_texts = [item.get("text") for item in initial_ocr.get("items", [])]
    already_in_qr_page = _texts_have_qr_state(initial_texts)
    steps.append({"action": "detect_initial_login_state", "qrState": already_in_qr_page, "ocrTexts": initial_texts})

    if not already_in_qr_page:
        for _ in range(max(1, wait_seconds // 3)):
            launch_title = _choose_launch_window_title()
            launch_click = click_wegame_text_by_ocr(LOGIN_TEXT_CANDIDATES, window_title=launch_title, settle_seconds=1.5)
            launch_click["action"] = "click_launch_by_ocr"
            steps.append(launch_click)
            if launch_click.get("clicked"):
                break
            if _texts_have_qr_state(launch_click.get("ocrTexts", [])):
                break
            time.sleep(3)

    qr_result = None
    deadline = time.time() + max(1, wait_seconds)
    qr_wait_started_at = time.time()
    while time.time() < deadline:
        title = _choose_launch_window_title()
        ocr = _ocr_items_for_window(title)
        texts = [item.get("text") for item in ocr.get("items", [])]
        qr_login_target = _find_text_candidate(
            ocr.get("items", []),
            QR_LOGIN_TEXT_BY_CHANNEL.get(normalized_channel, QR_LOGIN_TEXT_CANDIDATES),
        )
        if qr_login_target:
            if ocr.get("hwnd"):
                clicked = _click_hwnd_client(int(ocr["hwnd"]), qr_login_target["x"], qr_login_target["y"])
            else:
                clicked = window_click(qr_login_target["x"], qr_login_target["y"], title, background=False)
            steps.append({
                "action": "click_qr_login_by_ocr",
                "success": bool(clicked),
                "clicked": bool(clicked),
                "target": qr_login_target,
                "ocrTexts": texts,
            })
            time.sleep(2)
            continue

        has_qr_state = _texts_have_qr_state(texts)
        waited_after_launch = bool(launch_click and launch_click.get("clicked")) and (time.time() - qr_wait_started_at) >= 6
        if has_qr_state or waited_after_launch:
            qr_result = refresh_qr_and_send(
                message=message,
                project=project,
                settle_ms=900,
                login_channel=normalized_channel,
            )
            qr_result["action"] = "refresh_qr_and_send"
            qr_result["qrOcrDetected"] = has_qr_state
            qr_result["qrOcrTexts"] = texts
            steps.append(qr_result)
            break
        time.sleep(2)

    return {
        "success": bool(qr_result and qr_result.get("sendResult", {}).get("exitCode") == 0),
        "action": "login_flow_ocr",
        "launchWindow": launch_title,
        "launchClicked": bool(launch_click and launch_click.get("clicked")),
        "qrSent": bool(qr_result and qr_result.get("sendResult", {}).get("exitCode") == 0),
        "loginChannel": normalized_channel,
        "qrRefreshSeconds": int(qr_refresh_seconds),
        "steps": steps,
    }
