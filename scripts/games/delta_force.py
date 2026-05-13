import json
import os
import re
import time
from pathlib import Path
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

from scripts.click import click
from scripts.config import get_api_key, get_gui_agent_config
from scripts.gui_agent import AliyunGUIAgent
from scripts.keyboard import press_key
from scripts.rapidocr_reader import parse_duration_text as parse_rapidocr_duration_text
from scripts.rapidocr_reader import read_rapidocr_items, read_rapidocr_value
from scripts.recognition import find_all_template_matches, find_button
from scripts.screenshot import take_screenshot
from scripts.window import activate_window, get_window_info


GAME_ID = "delta-force"
WINDOW_TITLE = "三角洲行动"
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
STATIONS = ("tech_center", "workbench", "pharmacy_station", "armor_bench")
STATION_LABELS = {
    "tech_center": "技术中心",
    "workbench": "工作台",
    "pharmacy_station": "制药台",
    "armor_bench": "防具台",
}
ITEM_762X51MM_M62 = "762x51mm M62"
FILL_CONFIRM_ROI = (1450 / 3840, 1450 / 2160, 1200 / 3840, 260 / 2160)
PRICE_CHANGE_CONFIRM_ROI = (1450 / 3840, 1650 / 2160, 1200 / 3840, 360 / 2160)
PRODUCTION_ITEMS_PATH = ROOT_DIR / "games" / GAME_ID / "assets" / "production_items.json"
PRODUCTION_STATE_PATH = ROOT_DIR / "logs" / "production_state.json"
TRADING_HOUSE_BASE_SIZE = (3840, 2160)
TRADING_HOUSE_RESULTS_ROI = (860 / 3840, 300 / 2160, 3000 / 3840, 1160 / 2160)
TRADING_HOUSE_DETAIL_NAME_ROI = (860 / 3840, 300 / 2160, 1200 / 3840, 220 / 2160)
TRADING_HOUSE_SELECTED_DETAIL_TITLE_ROI = (3050 / 3840, 260 / 2160, 760 / 3840, 140 / 2160)
TRADING_HOUSE_LOWEST_PRICE_ROI = (250 / 3840, 320 / 2160, 520 / 3840, 110 / 2160)
TRADING_HOUSE_QUANTITY_ROI = (3120 / 3840, 1440 / 2160, 380 / 3840, 90 / 2160)
TRADING_HOUSE_TOTAL_PRICE_ROI = (3110 / 3840, 1680 / 2160, 420 / 3840, 90 / 2160)
TRADING_HOUSE_BANNER_ROI = (1280 / 3840, 300 / 2160, 1550 / 3840, 90 / 2160)
TRADING_HOUSE_TRACK_RANGE = (3072 / 3840, 3458 / 3840)
TRADING_HOUSE_TRACK_Y = 1548 / 2160
TRADING_HOUSE_MINUS_BUTTON = (2958 / 3840, 1548 / 2160)
TRADING_HOUSE_PLUS_BUTTON = (3565 / 3840, 1548 / 2160)
TRADING_HOUSE_BUY_BUTTON = (3265 / 3840, 1720 / 2160)
_production_items_cache: Optional[Dict] = None


def _result(action: str, **kwargs) -> Dict:
    data = {"action": action, "game": GAME_ID, "windowTitle": WINDOW_TITLE}
    data.update(kwargs)
    return data


def _load_screenshot(path: str) -> Image.Image:
    return Image.open(ROOT_DIR / path).convert("RGB")


def _trading_house_size(image: Optional[Image.Image] = None) -> Tuple[int, int]:
    if image is not None:
        return image.size
    info = get_window_info(WINDOW_TITLE) or {}
    width = int(info.get("width") or TRADING_HOUSE_BASE_SIZE[0])
    height = int(info.get("height") or TRADING_HOUSE_BASE_SIZE[1])
    return width, height


def _resolve_trading_roi(roi: Tuple[float, float, float, float], image: Optional[Image.Image] = None) -> Tuple[int, int, int, int]:
    width, height = _trading_house_size(image)
    left = int(round(width * roi[0]))
    top = int(round(height * roi[1]))
    roi_width = int(round(width * roi[2]))
    roi_height = int(round(height * roi[3]))
    return left, top, roi_width, roi_height


def _resolve_trading_roi_bounds(roi: Tuple[float, float, float, float], image: Optional[Image.Image] = None) -> Tuple[int, int, int, int]:
    left, top, roi_width, roi_height = _resolve_trading_roi(roi, image)
    return left, top, left + roi_width, top + roi_height


def _resolve_trading_point(point: Tuple[float, float], image: Optional[Image.Image] = None) -> Tuple[int, int]:
    width, height = _trading_house_size(image)
    return int(round(width * point[0])), int(round(height * point[1]))


def _load_production_items() -> Dict:
    global _production_items_cache
    if _production_items_cache is not None:
        return _production_items_cache
    if not PRODUCTION_ITEMS_PATH.exists():
        _production_items_cache = {}
        return _production_items_cache
    with PRODUCTION_ITEMS_PATH.open("r", encoding="utf-8") as handle:
        _production_items_cache = json.load(handle)
    return _production_items_cache


def _load_production_state() -> Dict:
    if not PRODUCTION_STATE_PATH.exists():
        return {"stations": {}}
    try:
        with PRODUCTION_STATE_PATH.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"stations": {}}
    if not isinstance(state, dict):
        return {"stations": {}}
    state.setdefault("stations", {})
    return state


def _save_production_state(state: Dict) -> None:
    PRODUCTION_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = PRODUCTION_STATE_PATH.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
    tmp_path.replace(PRODUCTION_STATE_PATH)


def _record_station_production(report: Dict) -> None:
    if not report or not report.get("station"):
        return
    state = _load_production_state()
    state.setdefault("stations", {})[report["station"]] = {
        "station": report.get("station"),
        "itemName": report.get("itemName"),
        "displayName": report.get("displayName"),
        "startedAt": report.get("startedAt"),
        "nextCollectAt": report.get("nextCollectAt"),
        "durationSeconds": report.get("durationSeconds"),
        "durationText": report.get("durationText"),
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
    }
    _save_production_state(state)


def _clear_station_production(station_name: str) -> None:
    state = _load_production_state()
    if state.get("stations", {}).pop(station_name, None) is not None:
        state["updatedAt"] = datetime.now().isoformat(timespec="seconds")
        _save_production_state(state)


def _defer_station_production_check(station_name: str, seconds: int = 600, reason: str = "visual_still_producing") -> Optional[Dict]:
    state = _load_production_state()
    record = state.get("stations", {}).get(station_name)
    if not record:
        return None
    now = datetime.now()
    record["nextCollectAt"] = (now + timedelta(seconds=seconds)).isoformat(timespec="seconds")
    record["deferredAt"] = now.isoformat(timespec="seconds")
    record["deferSeconds"] = seconds
    record["deferReason"] = reason
    record["updatedAt"] = now.isoformat(timespec="seconds")
    state["updatedAt"] = now.isoformat(timespec="seconds")
    _save_production_state(state)
    return record


def _station_due_for_collect(station_name: str, grace_seconds: int = 60) -> Tuple[bool, Optional[Dict]]:
    record = _load_production_state().get("stations", {}).get(station_name)
    if not record:
        return False, None
    next_collect_at = record.get("nextCollectAt")
    if not next_collect_at:
        started_at = record.get("startedAt")
        if not started_at:
            return False, record
        try:
            started_time = datetime.fromisoformat(started_at)
        except ValueError:
            return False, record
        # Some recipes do not have a configured duration yet. Use a conservative
        # fallback so non-yellow completed slots are still eventually collected.
        return datetime.now() >= started_time + timedelta(hours=10), record
    try:
        due_time = datetime.fromisoformat(next_collect_at)
    except ValueError:
        return False, record
    return datetime.now() >= due_time + timedelta(seconds=grace_seconds), record


def _station_has_active_production(station_name: str, grace_seconds: int = 60) -> Tuple[bool, Optional[Dict]]:
    due, record = _station_due_for_collect(station_name, grace_seconds=grace_seconds)
    if not record or due:
        return False, record
    if record.get("startedAt") and record.get("nextCollectAt"):
        return True, record
    return False, record


def compute_next_action(grace_seconds: int = 60) -> Dict:
    """
    Determine if any collect/produce action is needed.

    Returns:
      needAction: True if any station is due for collection or visually idle
      dueStations: stations whose nextCollectAt has passed
      idleStations: stations whose overview slot visually matches the idle template
      producing: stations currently producing (with nextCollectAt)
      nextSuggestedRun: ISO timestamp of earliest nextCollectAt (for scheduling)
      nextSuggestedRunDelta: human-readable time until next run
    """
    state = _load_production_state()
    stations_state = state.get("stations", {})

    due_stations: List[str] = []
    producing: List[Dict] = []
    idle_stations: List[str] = []
    unknown_stations: List[str] = []

    now = datetime.now()
    next_run_times: List[datetime] = []
    visual_idle_stations = _detect_visual_idle_stations()

    for station_name in STATIONS:
        record = stations_state.get(station_name)
        if not record or not record.get("startedAt"):
            if station_name in visual_idle_stations:
                idle_stations.append(station_name)
            else:
                unknown_stations.append(station_name)
            continue

        is_due, due_record = _station_due_for_collect(station_name, grace_seconds=grace_seconds)
        if is_due:
            due_stations.append(station_name)
            continue

        next_collect_at = record.get("nextCollectAt")
        if next_collect_at:
            try:
                next_run_times.append(datetime.fromisoformat(next_collect_at))
            except ValueError:
                pass

        producing.append({
            "station": station_name,
            "itemName": record.get("itemName"),
            "displayName": record.get("displayName"),
            "startedAt": record.get("startedAt"),
            "nextCollectAt": next_collect_at,
            "durationText": record.get("durationText"),
        })

    need_action = bool(due_stations or idle_stations)
    next_run = min(next_run_times) if next_run_times else None
    delta = None
    if next_run:
        diff = next_run - now
        total_seconds = int(diff.total_seconds())
        hours, remainder = divmod(max(0, total_seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        delta = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    return _result(
        "compute_next_action",
        needAction=need_action,
        dueStations=due_stations,
        idleStations=idle_stations,
        unknownStations=unknown_stations,
        visualIdleStations=visual_idle_stations,
        producing=producing,
        nextSuggestedRun=next_run.isoformat() if next_run else None,
        nextSuggestedRunDelta=delta,
        checkedAt=now.isoformat(timespec="seconds"),
        totalStations=len(STATIONS),
    )


def _detect_visual_idle_stations() -> List[str]:
    """Return stations whose overview card has a matched "空闲中" slot."""
    try:
        path = take_screenshot(WINDOW_TITLE)
        image = _load_screenshot(path)
        game_width = image.width
        idle_slots = _find_idle_slots(image, game_width, threshold=0.75)
        visual_idle: List[str] = []
        for station_name in STATIONS:
            station = _find_station_anchor(image, station_name, game_width)
            if station and _idle_slot_for_station(station, idle_slots):
                visual_idle.append(station_name)
        return visual_idle
    except Exception:
        return []


def _number_or_none(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        normalized = value.replace(",", "").strip()
        if not normalized:
            return None
        try:
            return float(normalized)
        except ValueError:
            return None
    return None


def _seconds_or_none(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        parts = value.strip().split(":")
        if len(parts) == 3 and all(part.isdigit() for part in parts):
            hours, minutes, seconds = [int(part) for part in parts]
            return hours * 3600 + minutes * 60 + seconds
        if value.strip().isdigit():
            return int(value.strip())
    return None


def _format_duration(seconds: Optional[int]) -> Optional[str]:
    if seconds is None:
        return None
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _parse_duration_text(text: Optional[str]) -> Optional[int]:
    if not isinstance(text, str):
        return None
    cleaned = text.strip()
    if not cleaned:
        return None
    colon_match = re.search(r"(?<!\d)(\d{1,3})\s*[:：]\s*(\d{1,2})\s*[:：]\s*(\d{1,2})(?!\d)", cleaned)
    if colon_match:
        hours, minutes, seconds = [int(part) for part in colon_match.groups()]
        if minutes < 60 and seconds < 60:
            return hours * 3600 + minutes * 60 + seconds
        return None
    zh_match = re.search(
        r"(?:(\d{1,3})\s*(?:小时|时|h|H))?\s*(?:(\d{1,2})\s*(?:分钟|分|m|M))?\s*(?:(\d{1,2})\s*(?:秒|s|S))",
        cleaned,
    )
    if zh_match and any(group is not None for group in zh_match.groups()):
        hours = int(zh_match.group(1) or 0)
        minutes = int(zh_match.group(2) or 0)
        seconds = int(zh_match.group(3) or 0)
        if minutes < 60 and seconds < 60:
            return hours * 3600 + minutes * 60 + seconds
    return None


def evaluate_production_item(station_name: str, item_name: str) -> Dict:
    catalog = _load_production_items()
    config = catalog.get(item_name, {})
    configured_station = config.get("station")
    estimated_cost = _number_or_none(config.get("estimatedCost"))
    expected_revenue = _number_or_none(config.get("expectedRevenue"))
    unit_expected_revenue = _number_or_none(config.get("unitExpectedRevenue"))
    output_quantity = int(_number_or_none(config.get("outputQuantity")) or 1)
    if expected_revenue is None and unit_expected_revenue is not None:
        expected_revenue = unit_expected_revenue * output_quantity
    duration_seconds = _seconds_or_none(config.get("durationSeconds"))
    expected_profit = None
    if estimated_cost is not None and expected_revenue is not None:
        expected_profit = expected_revenue - estimated_cost
    if expected_profit is None:
        profit_status = "unknown"
    elif expected_profit < 0:
        profit_status = "negative"
    elif expected_profit > 0:
        profit_status = "positive"
    else:
        profit_status = "break_even"

    return _result(
        "evaluate_production_item",
        station=station_name,
        itemName=item_name,
        configured=bool(config),
        configuredStation=configured_station,
        stationMatches=(configured_station in (None, station_name)),
        displayName=config.get("displayName", item_name),
        estimatedCost=estimated_cost,
        unitExpectedRevenue=unit_expected_revenue,
        outputQuantity=output_quantity,
        expectedRevenue=expected_revenue,
        expectedProfit=expected_profit,
        profitable=(expected_profit is None or expected_profit >= 0),
        profitStatus=profit_status,
        profitKnown=expected_profit is not None,
        durationSeconds=duration_seconds,
        durationText=_format_duration(duration_seconds),
        currency=config.get("currency"),
        source=config.get("source"),
        configPath=str(PRODUCTION_ITEMS_PATH),
    )


def _merge_runtime_economics(evaluation: Dict, runtime: Dict) -> Dict:
    merged = dict(evaluation)
    output_quantity = int(runtime.get("outputQuantity") or merged.get("outputQuantity") or 1)
    merged["outputQuantity"] = output_quantity
    if runtime.get("unitExpectedRevenue") is not None:
        merged["unitExpectedRevenue"] = runtime["unitExpectedRevenue"]
        merged["expectedRevenue"] = float(runtime["unitExpectedRevenue"]) * output_quantity
    elif runtime.get("expectedRevenue") is not None:
        merged["expectedRevenue"] = runtime["expectedRevenue"]
    if runtime.get("estimatedCost") is not None:
        merged["estimatedCost"] = runtime["estimatedCost"]
    if runtime.get("durationSeconds") is not None:
        runtime_duration = int(runtime["durationSeconds"])
        configured_duration = merged.get("durationSeconds")
        if runtime_duration >= 300 and (
            configured_duration is None or runtime_duration >= int(configured_duration) * 0.25
        ):
            merged["durationSeconds"] = runtime_duration
            merged["durationText"] = _format_duration(runtime_duration)
        else:
            merged.setdefault("runtimeWarnings", []).append(
                f"ignored implausible runtime duration: {runtime_duration}s"
            )

    expected_cost = merged.get("estimatedCost")
    expected_revenue = merged.get("expectedRevenue")
    expected_profit = None
    if expected_cost is not None and expected_revenue is not None:
        expected_profit = float(expected_revenue) - float(expected_cost)
    if expected_profit is None:
        profit_status = "unknown"
    elif expected_profit < 0:
        profit_status = "negative"
    elif expected_profit > 0:
        profit_status = "positive"
    else:
        profit_status = "break_even"

    merged["expectedProfit"] = expected_profit
    merged["profitStatus"] = profit_status
    merged["profitKnown"] = expected_profit is not None
    merged["profitable"] = expected_profit is None or expected_profit >= 0
    merged["runtimeEconomics"] = runtime
    if runtime:
        merged["source"] = "runtime_screen_reader"
    return merged


def _production_report(station_name: str, item_name: str, evaluation: Dict, started_at: datetime) -> Dict:
    duration_seconds = evaluation.get("durationSeconds")
    next_collect_at = None
    if duration_seconds is not None:
        next_collect_at = (started_at + timedelta(seconds=int(duration_seconds))).isoformat(timespec="seconds")
    return _result(
        "production_report",
        station=station_name,
        itemName=item_name,
        displayName=evaluation.get("displayName", item_name),
        startedAt=started_at.isoformat(timespec="seconds"),
        nextCollectAt=next_collect_at,
        durationSeconds=duration_seconds,
        durationText=evaluation.get("durationText"),
        estimatedCost=evaluation.get("estimatedCost"),
        unitExpectedRevenue=evaluation.get("unitExpectedRevenue"),
        outputQuantity=evaluation.get("outputQuantity"),
        expectedRevenue=evaluation.get("expectedRevenue"),
        expectedProfit=evaluation.get("expectedProfit"),
        profitStatus=evaluation.get("profitStatus"),
        profitKnown=evaluation.get("profitKnown", False),
        currency=evaluation.get("currency"),
        source=evaluation.get("source"),
    )


def find_fill_confirm_button() -> Dict:
    path = take_screenshot(WINDOW_TITLE)
    image = _load_screenshot(path)
    width, height = image.size
    roi_left = int(width * FILL_CONFIRM_ROI[0])
    roi_top = int(height * FILL_CONFIRM_ROI[1])
    roi_width = int(width * FILL_CONFIRM_ROI[2])
    roi_height = int(height * FILL_CONFIRM_ROI[3])
    roi = (roi_left, roi_top, roi_left + roi_width, roi_top + roi_height)

    crop = np.array(image.crop(roi).convert("RGB"))
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    mask = cv2.inRange(hsv, np.array([55, 70, 50]), np.array([100, 255, 255]))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidates = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 900:
            continue
        x, y, candidate_width, candidate_height = cv2.boundingRect(contour)
        if candidate_width < 40 or candidate_height < 20:
            continue
        score = area + candidate_width * 3 + candidate_height * 10
        candidates.append(
            {
                "x": roi_left + x + candidate_width // 2,
                "y": roi_top + y + candidate_height // 2,
                "width": int(candidate_width),
                "height": int(candidate_height),
                "area": round(float(area), 1),
                "score": round(float(score), 1),
            }
        )

    button = max(candidates, key=lambda item: item["score"]) if candidates else None
    return _result(
        "find_fill_confirm",
        found=button is not None,
        button=button,
        roi={"left": roi[0], "top": roi[1], "right": roi[2], "bottom": roi[3]},
        screenshotPath=path,
    )


def find_price_change_confirm_button() -> Dict:
    path = take_screenshot(WINDOW_TITLE)
    image = _load_screenshot(path)
    width, height = image.size
    roi_left = int(width * PRICE_CHANGE_CONFIRM_ROI[0])
    roi_top = int(height * PRICE_CHANGE_CONFIRM_ROI[1])
    roi_width = int(width * PRICE_CHANGE_CONFIRM_ROI[2])
    roi_height = int(height * PRICE_CHANGE_CONFIRM_ROI[3])
    roi = (roi_left, roi_top, roi_left + roi_width, roi_top + roi_height)

    crop = np.array(image.crop(roi).convert("RGB"))
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    mask = cv2.inRange(hsv, np.array([55, 70, 50]), np.array([100, 255, 255]))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidates = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 2500:
            continue
        x, y, candidate_width, candidate_height = cv2.boundingRect(contour)
        if candidate_width < 180 or candidate_height < 45:
            continue
        score = area + candidate_width * 3 + candidate_height * 10
        candidates.append(
            {
                "x": roi_left + x + candidate_width // 2,
                "y": roi_top + y + candidate_height // 2,
                "width": int(candidate_width),
                "height": int(candidate_height),
                "area": round(float(area), 1),
                "score": round(float(score), 1),
            }
        )

    button = max(candidates, key=lambda item: item["score"]) if candidates else None
    return _result(
        "find_price_change_confirm",
        found=button is not None,
        button=button,
        roi={"left": roi[0], "top": roi[1], "right": roi[2], "bottom": roi[3]},
        screenshotPath=path,
    )


def click_fill_confirm(background: bool = False) -> Dict:
    found = find_fill_confirm_button()
    button = found.get("button")
    if not button:
        return _result(
            "click_fill_confirm",
            found=False,
            clicked=False,
            detection=found,
            screenshotPath=found.get("screenshotPath"),
        )
    clicked = click(button["x"], button["y"], WINDOW_TITLE, background=background)
    time.sleep(0.8)
    after_path = take_screenshot(WINDOW_TITLE)
    return _result(
        "click_fill_confirm",
        found=True,
        clicked=clicked,
        button=button,
        detection=found,
        afterScreenshotPath=after_path,
    )


def click_price_change_confirm(background: bool = False) -> Dict:
    found = find_price_change_confirm_button()
    button = found.get("button")
    if not button:
        return _result(
            "click_price_change_confirm",
            found=False,
            clicked=False,
            detection=found,
            screenshotPath=found.get("screenshotPath"),
        )
    clicked = click(button["x"], button["y"], WINDOW_TITLE, background=background)
    time.sleep(0.8)
    after_path = take_screenshot(WINDOW_TITLE)
    return _result(
        "click_price_change_confirm",
        found=True,
        clicked=clicked,
        button=button,
        detection=found,
        afterScreenshotPath=after_path,
    )


def screenshot() -> Dict:
    path = take_screenshot(WINDOW_TITLE)
    return _result("screenshot", screenshotPath=path)


def read_screen_metric(reader_name: str) -> Dict:
    path = take_screenshot(WINDOW_TITLE)
    image = _load_screenshot(path)
    result = read_rapidocr_value(image, GAME_ID, reader_name)
    result.update(_result("read_screen_metric", readerName=reader_name, reader="rapidocr", screenshotPath=path))
    return result


def detect_button(button_name: str, threshold: float = 0.8) -> Dict:
    path = take_screenshot(WINDOW_TITLE)
    image = _load_screenshot(path)
    game_width = image.width
    button = find_button(image, GAME_ID, button_name, threshold=threshold, game_width=game_width)
    return _result("detect_button", buttonName=button_name, found=button is not None, button=button, screenshotPath=path)


def ensure_game_window_front() -> Dict:
    activated = activate_window(WINDOW_TITLE)
    time.sleep(0.5)
    window_info = get_window_info(WINDOW_TITLE)
    return _result(
        "ensure_game_window_front",
        success=bool(activated and window_info),
        activated=activated,
        windowInfo=window_info,
    )


def check_game_safe_for_automation() -> Dict:
    """
    Check if the game is in a safe state for automation.
    Safe = user is at teqinchu base/menu (not in a match/raid).

    This MUST be called before high-impact automation. It may click the top
    Teqinchu navigation tab only when that tab is confidently visible, because
    that is a safe recovery path back to the base overview.
    """
    overview = check_teqinchu_overview()
    if overview.get("success"):
        return _result(
            "check_game_safe_for_automation",
            safe=True,
            detectedState="teqinchu_overview",
            reason=None,
            overview=overview,
        )

    idle = check_teqinchu_idle_slot()
    if idle.get("success"):
        return _result(
            "check_game_safe_for_automation",
            safe=True,
            detectedState="teqinchu_idle_slot",
            reason=None,
            idleSlot=idle,
        )

    teqinchu_entry = detect_text_by_ocr("特勤处")
    best_teqinchu_entry = teqinchu_entry.get("bestMatch") or {}
    if not teqinchu_entry.get("found") or best_teqinchu_entry.get("matchType") != "exact":
        teqinchu_entry = detect_text_by_ocr("进入特勤处")
    if not teqinchu_entry.get("found"):
        teqinchu_entry = detect_button("teqinchu", threshold=0.95)
    if teqinchu_entry.get("found"):
        entry_text = "进入特勤处" if (teqinchu_entry.get("bestMatch") or {}).get("normalizedText") == "进入特勤处" else "特勤处"
        entry_click = click_text_by_ocr(entry_text)
        if not entry_click.get("clicked"):
            entry_click = click_button("teqinchu")
        time.sleep(0.8)
        after_overview = check_teqinchu_overview()
        if after_overview.get("success"):
            return _result(
                "check_game_safe_for_automation",
                safe=True,
                detectedState="teqinchu_entry_recovered",
                reason=None,
                overview=after_overview,
                entry=teqinchu_entry,
                entryClick=entry_click,
            )

    return _result(
        "check_game_safe_for_automation",
        safe=False,
        detectedState="unknown",
        reason="not_in_teqinchu_base",
        overview=overview,
        idleSlot=idle,
        teqinchuEntry=locals().get("teqinchu_entry"),
        screenshotPath=overview.get("screenshotPath") or idle.get("screenshotPath"),
    )


def dismiss_possible_reward_overlay() -> Dict:
    pressed = press_key("space")
    time.sleep(0.8)
    path = take_screenshot(WINDOW_TITLE)
    return _result("dismiss_possible_reward_overlay", key="space", pressed=pressed, screenshotPath=path)


def check_forced_offline() -> Dict:
    try:
        path = take_screenshot(WINDOW_TITLE)
    except RuntimeError as exc:
        return _result(
            "check_forced_offline",
            detected=False,
            button=None,
            success=False,
            reason="game_window_not_capturable",
            error=str(exc),
        )
    image = _load_screenshot(path)
    game_width = image.width
    button = find_button(image, GAME_ID, "forced_offline_exit", game_width=game_width)
    return _result(
        "check_forced_offline",
        success=True,
        detected=button is not None,
        button=button,
        screenshotPath=path,
    )


def handle_forced_offline(background: bool = False) -> Dict:
    steps = []
    window_ready = ensure_game_window_front()
    steps.append(window_ready)
    if not window_ready.get("success"):
        return _result(
            "handle_forced_offline",
            success=False,
            detected=False,
            clicked=False,
            reason="game_window_not_ready",
            steps=steps,
        )

    state = check_forced_offline()
    steps.append(state)
    if not state.get("detected"):
        return _result(
            "handle_forced_offline",
            success=True,
            detected=False,
            clicked=False,
            steps=steps,
            screenshotPath=state.get("screenshotPath"),
        )

    exit_click = click_button("forced_offline_exit", background=background)
    exit_click["action"] = "click_forced_offline_exit"
    steps.append(exit_click)
    time.sleep(1.0)
    final_path = take_screenshot(WINDOW_TITLE)
    return _result(
        "handle_forced_offline",
        success=bool(exit_click.get("clicked")),
        detected=True,
        clicked=bool(exit_click.get("clicked")),
        steps=steps,
        screenshotPath=final_path,
    )


def check_teqinchu_idle_slot() -> Dict:
    path = take_screenshot(WINDOW_TITLE)
    image = _load_screenshot(path)
    game_width = image.width
    ocr_idle = _find_ocr_text_candidates(image, "空闲中")
    button = ocr_idle.get("candidates", [None])[0] if ocr_idle.get("candidates") else None
    if not button:
        idle_slots = find_all_template_matches(
            image,
            GAME_ID,
            "idle_slot",
            game_width=game_width,
            threshold=0.75,
            max_results=10,
        )
        button = idle_slots[0] if idle_slots else None
    return _result(
        "check_teqinchu_idle",
        success=button is not None,
        idleSlotFound=button is not None,
        idleSlot=button,
        detectionMethod="rapidocr" if ocr_idle.get("candidates") else "template",
        screenshotPath=path,
    )


def _find_idle_slots(image: Image.Image, game_width: int, threshold: float = 0.40) -> List[Dict]:
    ocr_idle = _find_ocr_text_candidates(image, "空闲中")
    if ocr_idle.get("candidates"):
        return ocr_idle["candidates"]
    return find_all_template_matches(
        image,
        GAME_ID,
        "idle_slot",
        game_width=game_width,
        threshold=threshold,
        max_results=10,
    )


def _idle_slot_for_station(station: Dict, idle_slots: List[Dict]) -> Optional[Dict]:
    candidates = [
        slot for slot in idle_slots
        if slot["y"] > station["y"] and 150 <= slot["y"] - station["y"] <= 550
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda item: (abs(item["x"] - station["x"]), item["y"] - station["y"]))


def check_idle_slot() -> Dict:
    return check_teqinchu_idle_slot()


def _station_complete_roi(station: Dict, image_size: Tuple[int, int]) -> Tuple[int, int, int, int]:
    image_width, image_height = image_size
    station_top = station["y"] - station["height"] // 2
    station_right = station["x"] + station["width"] // 2
    slot_top = station_top + station["height"] + 20
    left = max(0, station_right - 95)
    top = max(0, slot_top - 25)
    right = min(image_width, station_right + 35)
    bottom = min(image_height, slot_top + 95)
    return left, top, right, bottom


def _station_slot_highlight_roi(station: Dict, image_size: Tuple[int, int]) -> Tuple[int, int, int, int]:
    image_width, image_height = image_size
    station_left = station["x"] - station["width"] // 2
    station_right = station["x"] + station["width"] // 2
    station_top = station["y"] - station["height"] // 2
    slot_top = station_top + station["height"] + 10
    left = max(0, station_left)
    top = max(0, slot_top)
    right = min(image_width, station_right)
    # Lower-row station result cards are taller than the first-row cards in a
    # 4K screenshot. Keep enough vertical area to include the yellow completion
    # band/outline near the bottom of the card.
    bottom = min(image_height, slot_top + 650)
    return left, top, right, bottom


def _find_yellow_complete_badge(image: Image.Image, roi: Tuple[int, int, int, int]) -> Optional[Dict]:
    left, top, right, bottom = roi
    if right <= left or bottom <= top:
        return None

    crop = np.array(image.crop(roi).convert("RGB"))
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    mask = cv2.inRange(hsv, np.array([18, 80, 120]), np.array([45, 255, 255]))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidates: List[Dict] = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 60:
            continue
        x, y, width, height = cv2.boundingRect(contour)
        if height < 20 or width < 5:
            continue
        aspect = height / max(1, width)
        if aspect < 1.4:
            continue
        candidates.append(
            {
                "x": left + x + width // 2,
                "y": top + y + height // 2,
                "width": int(width),
                "height": int(height),
                "area": round(float(area), 1),
                "aspect": round(float(aspect), 2),
            }
        )

    if not candidates:
        return None
    return max(candidates, key=lambda item: (item["area"], item["height"]))


def _find_yellow_slot_highlight(image: Image.Image, roi: Tuple[int, int, int, int]) -> Optional[Dict]:
    left, top, right, bottom = roi
    if right <= left or bottom <= top:
        return None

    crop = np.array(image.crop(roi).convert("RGB"))
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    mask = cv2.inRange(hsv, np.array([18, 55, 110]), np.array([45, 255, 255]))
    yellow_pixels = int(cv2.countNonZero(mask))
    if yellow_pixels < 1500:
        return None

    height, width = mask.shape
    border_width = 12
    border_mask = np.zeros_like(mask)
    border_mask[:border_width, :] = mask[:border_width, :]
    border_mask[-border_width:, :] = mask[-border_width:, :]
    border_mask[:, :border_width] = mask[:, :border_width]
    border_mask[:, -border_width:] = mask[:, -border_width:]
    border_yellow_pixels = int(cv2.countNonZero(border_mask))

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    wide_boxes = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 40:
            continue
        x, y, width, height = cv2.boundingRect(contour)
        box = {
            "x": left + x + width // 2,
            "y": top + y + height // 2,
            "width": int(width),
            "height": int(height),
            "area": round(float(area), 1),
        }
        boxes.append(box)
        if width >= int(mask.shape[1] * 0.55) and height >= 35 and area >= 1000:
            wide_boxes.append(box)

    if not boxes:
        return None
    if wide_boxes:
        marker = max(wide_boxes, key=lambda item: (item["area"], item["width"]))
        return {
            "x": marker["x"],
            "y": marker["y"],
            "yellowPixels": yellow_pixels,
            "borderYellowPixels": border_yellow_pixels,
            "roi": {"left": left, "top": top, "right": right, "bottom": bottom},
            "boxes": boxes[:10],
            "mode": "wide_yellow_completion_band",
        }
    if border_yellow_pixels < 600:
        return None
    xs = [box["x"] for box in boxes]
    ys = [box["y"] for box in boxes]
    return {
        "x": int(sum(xs) / len(xs)),
        "y": int(sum(ys) / len(ys)),
        "yellowPixels": yellow_pixels,
        "borderYellowPixels": border_yellow_pixels,
        "roi": {"left": left, "top": top, "right": right, "bottom": bottom},
        "boxes": boxes[:10],
    }


def check_station_complete(station_name: str) -> Dict:
    path = take_screenshot(WINDOW_TITLE)
    image = _load_screenshot(path)
    game_width = image.width
    station = _find_station_anchor(image, station_name, game_width)
    if not station:
        return _result("check_complete", station=station_name, found=False, complete=False, screenshotPath=path)

    roi = _station_complete_roi(station, image.size)
    badge = _find_yellow_complete_badge(image, roi)
    highlight_roi = _station_slot_highlight_roi(station, image.size)
    highlight = _find_yellow_slot_highlight(image, highlight_roi)
    idle_slots = _find_idle_slots(image, game_width, threshold=0.75)
    idle_slot = _idle_slot_for_station(station, idle_slots)
    due_for_collect, due_record = _station_due_for_collect(station_name)
    remaining = _read_station_overview_remaining_from_image(image, station)
    complete_by_no_timer = bool(
        due_record
        and due_for_collect
        and not idle_slot
        and not remaining.get("parsed")
    )
    complete_marker = bool(badge or highlight or complete_by_no_timer)
    complete_mode = None
    if badge:
        complete_mode = "yellow_badge"
    elif highlight:
        complete_mode = "yellow_slot_highlight"
    elif complete_by_no_timer:
        complete_mode = "due_no_countdown_not_idle"
    return _result(
        "check_complete",
        station=station_name,
        found=True,
        complete=complete_marker,
        stationButton=station,
        badge=badge,
        highlight=highlight,
        completeMode=complete_mode,
        idle=idle_slot is not None,
        idleSlot=idle_slot,
        due=due_for_collect,
        productionRecord=due_record,
        remainingTime=remaining,
        badgeRoi={"left": roi[0], "top": roi[1], "right": roi[2], "bottom": roi[3]},
        highlightRoi={"left": highlight_roi[0], "top": highlight_roi[1], "right": highlight_roi[2], "bottom": highlight_roi[3]},
        screenshotPath=path,
    )


def check_station_state(station_name: str) -> Dict:
    path = take_screenshot(WINDOW_TITLE)
    image = _load_screenshot(path)
    game_width = image.width
    station = _find_station_anchor(image, station_name, game_width)
    if not station:
        return _result(
            "check_station_state",
            station=station_name,
            found=False,
            state="not_found",
            complete=False,
            idle=False,
            screenshotPath=path,
        )

    complete_roi = _station_complete_roi(station, image.size)
    badge = _find_yellow_complete_badge(image, complete_roi)
    highlight_roi = _station_slot_highlight_roi(station, image.size)
    highlight = _find_yellow_slot_highlight(image, highlight_roi)
    idle_slots = _find_idle_slots(image, game_width, threshold=0.75)
    idle_slot = _idle_slot_for_station(station, idle_slots)
    due_for_collect, due_record = _station_due_for_collect(station_name)
    remaining = _read_station_overview_remaining_from_image(image, station)
    complete_by_no_timer = bool(
        due_record
        and due_for_collect
        and not idle_slot
        and not remaining.get("parsed")
    )
    if badge or highlight:
        state = "complete_yellow"
    elif idle_slot:
        state = "idle"
    elif complete_by_no_timer:
        state = "complete_no_countdown"
    else:
        state = "busy_or_not_ready"
    complete_mode = None
    if badge:
        complete_mode = "yellow_badge"
    elif highlight:
        complete_mode = "yellow_slot_highlight"
    elif complete_by_no_timer:
        complete_mode = "due_no_countdown_not_idle"

    return _result(
        "check_station_state",
        station=station_name,
        found=True,
        state=state,
        complete=(badge is not None or highlight is not None or complete_by_no_timer),
        idle=idle_slot is not None,
        stationButton=station,
        badge=badge,
        highlight=highlight,
        completeMode=complete_mode,
        idleSlot=idle_slot,
        idleSlots=idle_slots,
        due=due_for_collect,
        productionRecord=due_record,
        remainingTime=remaining,
        badgeRoi={"left": complete_roi[0], "top": complete_roi[1], "right": complete_roi[2], "bottom": complete_roi[3]},
        highlightRoi={"left": highlight_roi[0], "top": highlight_roi[1], "right": highlight_roi[2], "bottom": highlight_roi[3]},
        screenshotPath=path,
    )


def check_teqinchu_overview() -> Dict:
    path = take_screenshot(WINDOW_TITLE)
    image = _load_screenshot(path)
    game_width = image.width
    found = {}
    for station_name in STATIONS:
        station = _find_station_anchor(image, station_name, game_width)
        if station:
            found[station_name] = station
    return _result(
        "check_teqinchu_overview",
        success=len(found) >= 2,
        foundStations=found,
        screenshotPath=path,
    )


def _station_overview_card_roi(station: Dict, image_size: Tuple[int, int]) -> Tuple[int, int, int, int]:
    image_width, image_height = image_size
    left = max(0, station["x"] - station["width"] // 2)
    top = max(0, station["y"] - station["height"] // 2)
    right = min(image_width, station["x"] + station["width"] // 2)
    bottom = min(image_height, top + station["height"] + 570)
    return left, top, right, bottom


def _ocr_items_in_roi(items: List[Dict], roi: Tuple[int, int, int, int]) -> List[Dict]:
    left, top, right, bottom = roi
    matched = []
    for item in items:
        box = item.get("box") or {}
        x = box.get("x")
        y = box.get("y")
        if x is not None and y is not None and left <= x <= right and top <= y <= bottom:
            matched.append(item)
    return sorted(matched, key=lambda item: ((item.get("box") or {}).get("y", 0), (item.get("box") or {}).get("x", 0)))


def _read_station_overview_remaining_from_image(image: Image.Image, station: Dict) -> Dict:
    roi = _station_overview_card_roi(station, image.size)
    try:
        ocr = read_rapidocr_items(image)
    except Exception as exc:
        return {
            "parsed": False,
            "text": None,
            "remainingSeconds": None,
            "reason": "rapidocr_error",
            "error": str(exc),
            "roi": {"left": roi[0], "top": roi[1], "right": roi[2], "bottom": roi[3]},
        }
    items = _ocr_items_in_roi(ocr.get("items", []), roi)
    parsed_items = []
    for item in items:
        seconds = parse_rapidocr_duration_text(item.get("text"))
        if seconds is not None:
            parsed_items.append((item, seconds))
    selected = max(parsed_items, key=lambda pair: pair[0].get("score") or 0) if parsed_items else None
    return {
        "parsed": selected is not None,
        "text": selected[0].get("text") if selected else None,
        "remainingSeconds": selected[1] if selected else None,
        "confidence": selected[0].get("score") if selected else None,
        "roi": {"left": roi[0], "top": roi[1], "right": roi[2], "bottom": roi[3]},
        "ocrTexts": [item.get("text") for item in items],
    }


def read_teqinchu_overview_remaining_times() -> Dict:
    _, overview_steps = _ensure_teqinchu_overview()
    path = take_screenshot(WINDOW_TITLE)
    image = _load_screenshot(path)
    overview = check_teqinchu_overview()
    if not overview.get("success"):
        return _result(
            "read_teqinchu_overview_remaining_times",
            success=False,
            reason="teqinchu_overview_not_found",
            steps=overview_steps,
            overview=overview,
            screenshotPath=path,
        )

    try:
        ocr = read_rapidocr_items(image)
        stations = {}
        found_stations = overview.get("foundStations", {})
        for station in STATIONS:
            station_button = found_stations.get(station)
            if not station_button:
                stations[station] = {
                    "text": None,
                    "remainingSeconds": None,
                    "state": "unknown",
                    "confidence": None,
                    "parsed": False,
                    "reason": "station_not_found",
                }
                continue

            roi = _station_overview_card_roi(station_button, image.size)
            items = _ocr_items_in_roi(ocr.get("items", []), roi)
            parsed_items = []
            for item in items:
                seconds = parse_rapidocr_duration_text(item.get("text"))
                if seconds is not None:
                    parsed_items.append((item, seconds))
            selected = max(parsed_items, key=lambda pair: pair[0].get("score") or 0) if parsed_items else None
            text = selected[0].get("text") if selected else None
            seconds = selected[1] if selected else None
            stations[station] = {
                "text": text,
                "remainingSeconds": seconds,
                "state": "producing" if seconds is not None else "unknown",
                "confidence": selected[0].get("score") if selected else None,
                "parsed": seconds is not None,
                "roi": {"left": roi[0], "top": roi[1], "right": roi[2], "bottom": roi[3]},
                "ocrTexts": [item.get("text") for item in items],
            }
        return _result(
            "read_teqinchu_overview_remaining_times",
            success=any(item["parsed"] for item in stations.values()),
            stations=stations,
            provider="rapidocr",
            engine=ocr.get("engine"),
            steps=overview_steps,
            screenshotPath=path,
        )
    except Exception as exc:
        return _result(
            "read_teqinchu_overview_remaining_times",
            success=False,
            reason="rapidocr_error",
            error=str(exc),
            steps=overview_steps,
            screenshotPath=path,
        )


def sync_overview_remaining_times() -> Dict:
    now = datetime.now()
    read = read_teqinchu_overview_remaining_times()
    steps = [read]
    if not read.get("success"):
        return _result(
            "sync_overview_remaining_times",
            success=False,
            reason=read.get("reason", "no_remaining_times_parsed"),
            updatedStations=[],
            steps=steps,
            screenshotPath=read.get("screenshotPath"),
        )

    state = _load_production_state()
    stations_state = state.setdefault("stations", {})
    updated = []
    skipped = []
    for station, parsed in read.get("stations", {}).items():
        seconds = parsed.get("remainingSeconds")
        if seconds is None:
            skipped.append({"station": station, "reason": "remaining_time_not_parsed", "text": parsed.get("text")})
            continue
        record = stations_state.get(station)
        if not record or not record.get("startedAt"):
            skipped.append({"station": station, "reason": "no_existing_production_record", "text": parsed.get("text")})
            continue
        next_collect_at = (now + timedelta(seconds=int(seconds))).isoformat(timespec="seconds")
        record["nextCollectAt"] = next_collect_at
        record["durationText"] = _format_duration(record.get("durationSeconds"))
        record["remainingSecondsSynced"] = int(seconds)
        record["remainingTextSynced"] = parsed.get("text")
        record["remainingSyncedAt"] = now.isoformat(timespec="seconds")
        record["updatedAt"] = now.isoformat(timespec="seconds")
        updated.append({"station": station, "remainingSeconds": int(seconds), "nextCollectAt": next_collect_at, "text": parsed.get("text")})
    if updated:
        state["updatedAt"] = now.isoformat(timespec="seconds")
        _save_production_state(state)
    return _result(
        "sync_overview_remaining_times",
        success=bool(updated),
        updatedStations=updated,
        skippedStations=skipped,
        steps=steps,
        screenshotPath=read.get("screenshotPath"),
    )


def click_station_idle_slot(station_name: str, background: bool = False) -> Dict:
    path = take_screenshot(WINDOW_TITLE)
    image = _load_screenshot(path)
    game_width = image.width
    station = _find_station_anchor(image, station_name, game_width)
    if not station:
        return _result(
            "click_station_idle_slot",
            station=station_name,
            found=False,
            clicked=False,
            reason="station_not_found",
            screenshotPath=path,
        )

    idle_slots = _find_idle_slots(image, game_width, threshold=0.75)
    slot = _idle_slot_for_station(station, idle_slots)
    if not slot:
        return _result(
            "click_station_idle_slot",
            station=station_name,
            found=False,
            clicked=False,
            reason="idle_slot_not_found_under_station",
            stationButton=station,
            idleSlots=idle_slots,
            screenshotPath=path,
        )

    clicked = click(slot["x"], slot["y"], WINDOW_TITLE, background=background)
    time.sleep(0.8)
    after_path = take_screenshot(WINDOW_TITLE)
    return _result(
        "click_station_idle_slot",
        station=station_name,
        found=True,
        clicked=clicked,
        stationButton=station,
        idleSlot=slot,
        screenshotPath=path,
        afterScreenshotPath=after_path,
    )


def inspect_production_actions(item_name: str) -> Dict:
    one_click_fill = detect_text_by_ocr("一键补齐")
    if not one_click_fill.get("found"):
        one_click_fill = detect_button("one_click_fill")
    produce = detect_text_by_ocr("生产")
    if not produce.get("found"):
        produce = detect_button("produce_button")
    return _result(
        "inspect_production_actions",
        itemName=item_name,
        oneClickFillFound=one_click_fill.get("found", False),
        oneClickFill=one_click_fill.get("button"),
        produceButtonFound=produce.get("found", False),
        produceButton=produce.get("button"),
        steps=[one_click_fill, produce],
        screenshotPath=produce.get("screenshotPath") or one_click_fill.get("screenshotPath"),
    )


def prepare_materials_if_needed(
    background: bool = False,
    expected_revenue: Optional[float] = None,
    profit_guard: bool = True,
) -> Dict:
    steps = []
    one_click_fill = detect_text_by_ocr("一键补齐")
    if not one_click_fill.get("found"):
        one_click_fill = detect_button("one_click_fill")
    steps.append(one_click_fill)
    if not one_click_fill.get("found"):
        produce = detect_text_by_ocr("生产")
        if not produce.get("found"):
            produce = detect_button("produce_button")
        steps.append(produce)
        if produce.get("found"):
            return _result(
                "prepare_materials_if_needed",
                needed=False,
                success=True,
                estimatedCost=0.0,
                expectedRevenue=expected_revenue,
                expectedProfit=expected_revenue if expected_revenue is not None else None,
                produceButtonFound=True,
                produceButton=produce.get("button"),
                steps=steps,
                screenshotPath=produce.get("screenshotPath"),
            )
        return _result(
            "prepare_materials_if_needed",
            needed=None,
            success=False,
            reason="production_action_button_not_found",
            expectedRevenue=expected_revenue,
            steps=steps,
            screenshotPath=produce.get("screenshotPath") or one_click_fill.get("screenshotPath"),
        )

    fill_click = click_text_by_ocr("一键补齐", background=background)
    if not fill_click.get("clicked"):
        fill_click = click_button("one_click_fill", background=background)
    steps.append(fill_click)
    if not fill_click.get("clicked"):
        return _result(
            "prepare_materials_if_needed",
            needed=True,
            success=False,
            reason="one_click_fill_not_clicked",
            steps=steps,
            screenshotPath=fill_click.get("screenshotPath"),
        )

    cost_read = read_screen_metric("fill_confirm_cost")
    cost_read["action"] = "read_fill_confirm_cost"
    steps.append(cost_read)
    estimated_cost = cost_read.get("value") if cost_read.get("success") else None
    expected_profit = None
    if estimated_cost is not None and expected_revenue is not None:
        expected_profit = float(expected_revenue) - float(estimated_cost)
        if profit_guard and expected_profit < 0:
            press_key("esc")
            time.sleep(0.4)
            return _result(
                "prepare_materials_if_needed",
                needed=True,
                success=False,
                skipped=True,
                reason="expected_profit_negative_after_fill_cost",
                estimatedCost=estimated_cost,
                expectedRevenue=expected_revenue,
                expectedProfit=expected_profit,
                steps=steps,
                screenshotPath=cost_read.get("screenshotPath"),
            )

    confirm_click = click_fill_confirm(background=background)
    steps.append(confirm_click)
    if not confirm_click.get("clicked"):
        return _result(
            "prepare_materials_if_needed",
            needed=True,
            success=False,
            reason="fill_confirm_not_clicked",
            steps=steps,
            screenshotPath=confirm_click.get("screenshotPath") or confirm_click.get("afterScreenshotPath"),
        )

    time.sleep(0.8)
    produce = detect_text_by_ocr("生产")
    if not produce.get("found"):
        produce = detect_button("produce_button")
    steps.append(produce)
    price_change_confirm = None
    if not produce.get("found"):
        price_change_confirm = click_price_change_confirm(background=background)
        steps.append(price_change_confirm)
        if price_change_confirm.get("clicked"):
            time.sleep(0.8)
            produce = detect_text_by_ocr("生产")
            if not produce.get("found"):
                produce = detect_button("produce_button")
            produce["action"] = "detect_button_after_price_change_confirm"
            steps.append(produce)
    if not produce.get("found"):
        for attempt in range(1, 3):
            time.sleep(1.0)
            retry = detect_text_by_ocr("生产")
            if not retry.get("found"):
                retry = detect_button("produce_button")
            retry["action"] = f"detect_button_retry_after_fill_{attempt}"
            steps.append(retry)
            if retry.get("found"):
                produce = retry
                break
    return _result(
        "prepare_materials_if_needed",
        needed=True,
        success=produce.get("found", False),
        reason=None if produce.get("found") else "produce_button_not_found_after_fill",
        estimatedCost=estimated_cost,
        expectedRevenue=expected_revenue,
        expectedProfit=expected_profit,
        produceButtonFound=produce.get("found", False),
        produceButton=produce.get("button"),
        priceChangeConfirmClicked=bool(price_change_confirm and price_change_confirm.get("clicked")),
        steps=steps,
        screenshotPath=produce.get("screenshotPath"),
    )


def click_produce_button(background: bool = False) -> Dict:
    produce_click = click_text_by_ocr("生产", background=background)
    if not produce_click.get("clicked"):
        produce_click = click_button("produce_button", background=background)
    produce_click["action"] = "click_produce_button"
    if not produce_click.get("clicked"):
        produce_click["reason"] = "produce_button_not_clicked"
    return produce_click


def click_collect_button_if_visible(background: bool = False) -> Dict:
    collect_click = click_text_by_ocr("收取", background=background)
    if not collect_click.get("clicked"):
        collect_click = click_button("collect_button", background=background)
    collect_click["action"] = "click_collect_button_if_visible"
    if not collect_click.get("clicked"):
        collect_click["reason"] = "collect_button_not_found"
    return collect_click


def collect_station_if_complete(station_name: str, background: bool = False, ensure_window: bool = True) -> Dict:
    steps = []
    if ensure_window:
        window_ready = ensure_game_window_front()
        steps.append(window_ready)
        if not window_ready.get("success"):
            return _result(
                "collect_station",
                station=station_name,
                complete=False,
                collected=False,
                reason="game_window_not_ready",
                steps=steps,
        )
        steps.append(dismiss_possible_reward_overlay())

    current_collect = click_collect_button_if_visible(background=background)
    steps.append(current_collect)
    if current_collect.get("clicked"):
        time.sleep(0.8)
        steps.append(dismiss_possible_reward_overlay())
        time.sleep(0.5)
        idle = check_teqinchu_idle_slot()
        idle["action"] = "check_teqinchu_idle_after_current_detail_collect"
        steps.append(idle)
        return _result(
            "collect_station",
            station=station_name,
            complete=True,
            collected=idle.get("success", False),
            click=current_collect,
            idleVerified=idle.get("success"),
            steps=steps,
            screenshotPath=idle.get("screenshotPath"),
        )

    overview = check_teqinchu_overview()
    steps.append(overview)
    if not overview.get("success"):
        for index in range(2):
            press_key("esc")
            time.sleep(0.6)
            overview = check_teqinchu_overview()
            overview["action"] = f"check_teqinchu_overview_after_escape_{index + 1}"
            steps.append(overview)
            if overview.get("success"):
                break

    if not overview.get("success"):
        entry = click_text_by_ocr("特勤处", background=background)
        if not entry.get("clicked"):
            entry = click_button("teqinchu", background=background)
        steps.append(entry)
        time.sleep(0.5)

    complete = check_station_complete(station_name)
    steps.append(complete)
    station = complete.get("stationButton")
    due_for_collect, due_record = _station_due_for_collect(station_name)
    if due_record:
        steps.append(
            _result(
                "check_station_due_for_collect",
                station=station_name,
                due=due_for_collect,
                record=due_record,
            )
        )
    if not station:
        return _result(
            "collect_station",
            station=station_name,
            complete=False,
            collected=False,
            reason="station_not_found",
            steps=steps,
            screenshotPath=complete.get("screenshotPath"),
        )

    should_collect = bool(complete.get("complete") or due_for_collect)
    if not should_collect:
        return _result(
            "collect_station",
            station=station_name,
            complete=False,
            collected=False,
            reason="not_complete_or_due",
            steps=steps,
            screenshotPath=complete.get("screenshotPath"),
        )

    # Three-state handling:
    # (1) complete_yellow: yellow badge visible → collect now
    # (2) due_without_yellow + idle: item was collected manually → clear state, ready for produce
    # (3) due_without_yellow + NOT idle: still producing → skip, do NOT click
    if not complete.get("complete"):
        # due_without_yellow: no yellow badge, item might still be producing
        idle_check = check_teqinchu_idle_slot()
        idle_check["action"] = "check_idle_before_due_without_yellow_click"
        steps.append(idle_check)
        if idle_check.get("success"):
            # Slot is idle: item was already collected manually. Clear state.
            _clear_station_production(station_name)
            return _result(
                "collect_station",
                station=station_name,
                complete=False,
                collected=False,
                reason="due_without_yellow_cleared_idle",
                steps=steps,
                screenshotPath=idle_check.get("screenshotPath"),
            )
        else:
            # Still producing: do NOT click the station
            deferred_record = _defer_station_production_check(
                station_name,
                seconds=600,
                reason="due_without_yellow_still_producing",
            )
            return _result(
                "collect_station",
                station=station_name,
                complete=False,
                collected=False,
                reason="still_producing_no_yellow_badge",
                deferredRecord=deferred_record,
                steps=steps,
                screenshotPath=idle_check.get("screenshotPath") or complete.get("screenshotPath"),
            )

    collect_x = int(station["x"])
    collect_y = int(station["y"]) + 300
    clicked = click(collect_x, collect_y, WINDOW_TITLE, background=background)
    time.sleep(0.8)
    collect_button = click_collect_button_if_visible(background=background)
    steps.append(collect_button)
    if collect_button.get("clicked"):
        clicked = True
        time.sleep(0.8)
        steps.append(dismiss_possible_reward_overlay())
        time.sleep(0.5)
    idle = check_teqinchu_idle_slot()
    steps.append(idle)
    if clicked and not idle.get("success"):
        steps.append(dismiss_possible_reward_overlay())
        time.sleep(0.5)
        idle = check_teqinchu_idle_slot()
        idle["action"] = "check_teqinchu_idle_after_reward_dismiss"
        steps.append(idle)

    collected = bool(clicked and idle.get("success"))
    if collected:
        _clear_station_production(station_name)

    return _result(
        "collect_station",
        station=station_name,
        complete=True,
        completeMode="yellow" if complete.get("complete") else "due_without_yellow",
        collected=collected,
        click={"x": collect_x, "y": collect_y, "success": clicked},
        idleVerified=idle.get("success"),
        steps=steps,
        screenshotPath=idle.get("screenshotPath"),
    )


def collect_completed_stations(background: bool = False) -> Dict:
    steps = []
    collected = []
    skipped = []
    window_ready = ensure_game_window_front()
    steps.append(window_ready)
    if not window_ready.get("success"):
        return _result(
            "collect_completed",
            success=False,
            reason="game_window_not_ready",
            collected=collected,
            skipped=list(STATIONS),
            steps=steps,
        )

    safe_check = check_game_safe_for_automation()
    steps.append(safe_check)
    if not safe_check.get("safe"):
        return _result(
            "collect_completed",
            success=False,
            reason="game_unsafe_for_automation",
            reasonDetail=safe_check.get("reason"),
            detectedState=safe_check.get("detectedState"),
            collected=collected,
            skipped=list(STATIONS),
            steps=steps,
            screenshotPath=safe_check.get("screenshotPath"),
        )

    steps.append(dismiss_possible_reward_overlay())

    for station in STATIONS:
        result = collect_station_if_complete(station, background=background, ensure_window=False)
        steps.append(result)
        if result.get("collected"):
            collected.append(station)
        else:
            skipped.append(station)
        time.sleep(0.4)
    final_path = take_screenshot(WINDOW_TITLE)
    return _result("collect_completed", collected=collected, skipped=skipped, steps=steps, screenshotPath=final_path)


def _ensure_teqinchu_overview(background: bool = False, attempts: int = 3) -> Tuple[Dict, List[Dict]]:
    steps = []

    overview = check_teqinchu_overview()
    steps.append(overview)
    if overview.get("success"):
        idle = check_teqinchu_idle_slot()
        steps.append(idle)
        return idle, steps

    idle = check_teqinchu_idle_slot()
    steps.append(idle)
    if idle.get("success"):
        return idle, steps

    entry = click_text_by_ocr("特勤处", background=background)
    if not entry.get("clicked"):
        entry = click_button("teqinchu", background=background)
    steps.append(entry)
    time.sleep(0.5)
    idle = check_teqinchu_idle_slot()
    steps.append(idle)
    if idle.get("success"):
        return idle, steps

    for index in range(attempts):
        press_key("esc")
        time.sleep(0.6)
        overview = check_teqinchu_overview()
        overview["action"] = f"check_teqinchu_overview_after_escape_{index + 1}"
        steps.append(overview)
        if overview.get("success"):
            idle = check_teqinchu_idle_slot()
            steps.append(idle)
            return idle, steps

        after_escape = check_teqinchu_idle_slot()
        after_escape["action"] = f"check_teqinchu_idle_after_escape_{index + 1}"
        steps.append(after_escape)
        if after_escape.get("success"):
            return after_escape, steps

        entry = click_text_by_ocr("特勤处", background=background)
        if not entry.get("clicked"):
            entry = click_button("teqinchu", background=background)
        steps.append(entry)
        time.sleep(0.5)
        idle = check_teqinchu_idle_slot()
        steps.append(idle)
        if idle.get("success"):
            return idle, steps

    return idle, steps


def _normalize_ocr_match_text(value: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", (value or "").lower())


def _find_ocr_text_candidates(
    image: Image.Image,
    text: str,
    roi: Optional[Tuple[int, int, int, int]] = None,
) -> Dict:
    query = _normalize_ocr_match_text(text)
    if not query:
        return {"success": False, "reason": "empty_query", "candidates": [], "ocrTexts": []}

    try:
        ocr = read_rapidocr_items(image)
    except Exception as exc:
        return {"success": False, "reason": "rapidocr_error", "error": str(exc), "candidates": [], "ocrTexts": []}

    items = _ocr_items_in_roi(ocr.get("items", []), roi) if roi else ocr.get("items", [])
    candidates = []
    for item in items:
        raw_text = item.get("text") or ""
        normalized = _normalize_ocr_match_text(raw_text)
        if not normalized:
            continue
        if query in normalized:
            pass
        elif normalized in query and len(normalized) >= max(2, len(query) // 2):
            pass
        else:
            continue
        box = item.get("box") or {}
        x = box.get("x")
        y = box.get("y")
        if x is None or y is None:
            continue
        candidates.append(
            {
                "text": raw_text,
                "normalizedText": normalized,
                "matchType": "exact" if normalized == query else "contains",
                "x": int(x),
                "y": int(y),
                "score": item.get("score"),
                "box": box,
            }
        )
    candidates.sort(
        key=lambda item: (
            item.get("matchType") == "exact",
            item.get("score") or 0,
            -len(item.get("normalizedText") or ""),
        ),
        reverse=True,
    )
    return {
        "success": bool(candidates),
        "candidates": candidates,
        "ocrTexts": [item.get("text") for item in items],
        "engine": ocr.get("engine"),
    }


def detect_text_by_ocr(
    text: str,
    roi: Optional[Tuple[int, int, int, int]] = None,
) -> Dict:
    path = take_screenshot(WINDOW_TITLE)
    image = _load_screenshot(path)
    found = _find_ocr_text_candidates(image, text, roi=roi)
    best = found.get("candidates", [None])[0] if found.get("candidates") else None
    return _result(
        "detect_text_by_ocr",
        text=text,
        found=best is not None,
        bestMatch=best,
        candidates=found.get("candidates", []),
        ocrTexts=found.get("ocrTexts", []),
        engine=found.get("engine"),
        reason=None if best else found.get("reason", "ocr_text_not_found"),
        screenshotPath=path,
    )


def click_text_by_ocr(
    text: str,
    background: bool = False,
    roi: Optional[Tuple[int, int, int, int]] = None,
) -> Dict:
    detected = detect_text_by_ocr(text, roi=roi)
    target = detected.get("bestMatch")
    if not target:
        detected["action"] = "click_text_by_ocr"
        detected["clicked"] = False
        return detected

    clicked = click(int(target["x"]), int(target["y"]), WINDOW_TITLE, background=background)
    time.sleep(0.5)
    after_path = take_screenshot(WINDOW_TITLE)
    return _result(
        "click_text_by_ocr",
        text=text,
        found=True,
        clicked=clicked,
        target=target,
        detection=detected,
        afterScreenshotPath=after_path,
    )


def _station_by_ocr_label(image: Image.Image, station_name: str) -> Optional[Dict]:
    label = STATION_LABELS.get(station_name)
    if not label:
        return None
    found = _find_ocr_text_candidates(image, label)
    candidates = found.get("candidates") or []
    if not candidates:
        return None
    target = candidates[0]
    box = target.get("box") or {}
    width = int(box.get("width") or max(120, len(label) * 36))
    height = int(box.get("height") or 60)
    return {
        "x": int(target["x"]),
        "y": int(target["y"]),
        "width": width,
        "height": height,
        "label": label,
        "source": "rapidocr",
        "box": box,
        "score": target.get("score"),
    }


def _find_station_anchor(image: Image.Image, station_name: str, game_width: int) -> Optional[Dict]:
    return _station_by_ocr_label(image, station_name) or find_button(image, GAME_ID, station_name, game_width=game_width)


def _normalize_market_item_text(value: str) -> str:
    text = (value or "").lower()
    replacements = {
        "×": "x",
        " mrn": " mm",
        "mrn": "mm",
        " rn": " m",
        "，": ",",
        "。": ".",
    }
    for src, target in replacements.items():
        text = text.replace(src, target)
    text = re.sub(r"\s+", " ", text).strip()
    compact = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", text)
    return compact


def _extract_first_int(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    match = re.search(r"(\d[\d,]*)", value)
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _extract_last_int(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    matches = re.findall(r"(\d[\d,]*)", value)
    if not matches:
        return None
    try:
        return int(matches[-1].replace(",", ""))
    except ValueError:
        return None


def _extract_quantity_pair(value: Optional[str]) -> Tuple[Optional[int], Optional[int]]:
    if not value:
        return None, None
    match = re.search(r"(\d+)\s*/\s*(\d+)", value)
    if not match:
        return None, None
    try:
        return int(match.group(1)), int(match.group(2))
    except ValueError:
        return None, None


def _market_text_similarity(target_name: str, candidate_text: str) -> float:
    target = _normalize_market_item_text(target_name)
    candidate = _normalize_market_item_text(candidate_text)
    if not target or not candidate:
        return 0.0
    if candidate == target:
        return 1.0
    if target in candidate or candidate in target:
        ratio = len(candidate) / max(1, len(target))
        return 0.94 + min(0.05, ratio * 0.05)
    return SequenceMatcher(None, target, candidate).ratio()


def _market_target_tokens(target_name: str) -> List[str]:
    normalized = _normalize_market_item_text(target_name)
    if not normalized:
        return []
    tokens = re.findall(r"[a-z]+|\d+", normalized)
    return [token for token in tokens if len(token) >= 2]


def _market_result_like_text_count(items: List[Dict]) -> int:
    count = 0
    for item in items:
        text = item.get("text") or ""
        normalized = _normalize_market_item_text(text)
        if not normalized:
            continue
        if "mm" in normalized and any(char.isdigit() for char in normalized):
            count += 1
            continue
        if re.search(r"\d+[x×]\d+", text):
            count += 1
    return count


def _find_market_item_candidates(target_name: str, image: Image.Image, roi: Optional[Tuple[int, int, int, int]] = None) -> Dict:
    roi = roi or _resolve_trading_roi_bounds(TRADING_HOUSE_RESULTS_ROI, image)
    try:
        ocr = read_rapidocr_items(image)
    except Exception as exc:
        return {
            "success": False,
            "reason": "rapidocr_error",
            "error": str(exc),
            "candidates": [],
            "ocrTexts": [],
            "roi": {"left": roi[0], "top": roi[1], "right": roi[2], "bottom": roi[3]},
        }

    items = _ocr_items_in_roi(ocr.get("items", []), roi)
    candidates = []
    target_normalized = _normalize_market_item_text(target_name)
    target_tokens = _market_target_tokens(target_name)
    for item in items:
        text = item.get("text") or ""
        normalized = _normalize_market_item_text(text)
        if not normalized:
            continue
        similarity = _market_text_similarity(target_name, text)
        token_hits = sum(1 for token in target_tokens if token in normalized)
        if similarity < 0.68 and token_hits == 0:
            continue
        box = item.get("box") or {}
        if box.get("x") is None or box.get("y") is None:
            continue
        match_type = "fuzzy"
        if normalized == target_normalized:
            match_type = "exact"
        elif target_normalized in normalized or normalized in target_normalized:
            match_type = "contains"
        candidates.append(
            {
                "text": text,
                "normalizedText": normalized,
                "similarity": round(similarity, 4),
                "matchType": match_type,
                "tokenHits": token_hits,
                "score": item.get("score"),
                "box": box,
                "x": box.get("x"),
                "y": box.get("y"),
            }
        )

    candidates.sort(
        key=lambda item: (
            item.get("matchType") == "exact",
            item.get("matchType") == "contains",
            item.get("tokenHits") or 0,
            item.get("similarity") or 0,
            item.get("score") or 0,
        ),
        reverse=True,
    )
    return {
        "success": bool(candidates),
        "candidates": candidates,
        "ocrTexts": [item.get("text") for item in items],
        "roi": {"left": roi[0], "top": roi[1], "right": roi[2], "bottom": roi[3]},
        "engine": ocr.get("engine"),
    }


def find_market_item_by_name(target_name: str) -> Dict:
    path = take_screenshot(WINDOW_TITLE)
    image = _load_screenshot(path)
    search = _find_market_item_candidates(target_name, image)
    candidates = search.get("candidates", [])
    best = candidates[0] if candidates else None
    return _result(
        "find_market_item_by_name",
        itemName=target_name,
        found=bool(best),
        bestMatch=best,
        candidates=candidates,
        roi=search.get("roi"),
        engine=search.get("engine"),
        reason=None if best else search.get("reason", "market_item_not_found"),
        ocrTexts=search.get("ocrTexts", []),
        screenshotPath=path,
    )


def _verify_market_selection(target_name: str, image: Image.Image, clicked_box: Dict) -> Dict:
    results_left, results_top, results_right, results_bottom = _resolve_trading_roi_bounds(TRADING_HOUSE_RESULTS_ROI, image)
    local_left = max(results_left, int(clicked_box.get("left", clicked_box.get("x", 0)) - 80))
    local_top = max(results_top, int(clicked_box.get("top", clicked_box.get("y", 0)) - 40))
    local_right = min(results_right, int(clicked_box.get("right", clicked_box.get("x", 0)) + 260))
    local_bottom = min(results_bottom, int(clicked_box.get("bottom", clicked_box.get("y", 0)) + 40))
    local_roi = (local_left, local_top, local_right, local_bottom)
    local_search = _find_market_item_candidates(target_name, image, roi=local_roi)
    if local_search.get("candidates"):
        best = local_search["candidates"][0]
        if (best.get("matchType") in {"exact", "contains"} or (best.get("similarity") or 0) >= 0.82):
            return {
                "verified": True,
                "method": "local_result_roi",
                "bestMatch": best,
                "roi": local_search.get("roi"),
                "ocrTexts": local_search.get("ocrTexts", []),
            }

    detail_search = _find_market_item_candidates(
        target_name,
        image,
        roi=_resolve_trading_roi_bounds(TRADING_HOUSE_SELECTED_DETAIL_TITLE_ROI, image),
    )
    if detail_search.get("candidates"):
        best = detail_search["candidates"][0]
        if (best.get("matchType") in {"exact", "contains"} or (best.get("similarity") or 0) >= 0.82):
            return {
                "verified": True,
                "method": "detail_name_roi",
                "bestMatch": best,
                "roi": detail_search.get("roi"),
                "ocrTexts": detail_search.get("ocrTexts", []),
            }

    return {
        "verified": False,
        "method": "unverified",
        "localOcrTexts": local_search.get("ocrTexts", []),
        "detailOcrTexts": detail_search.get("ocrTexts", []),
    }


def _market_result_list_looks_visible(image: Image.Image) -> bool:
    try:
        ocr = read_rapidocr_items(image)
    except Exception:
        return False
    items = _ocr_items_in_roi(ocr.get("items", []), _resolve_trading_roi_bounds(TRADING_HOUSE_RESULTS_ROI, image))
    return _market_result_like_text_count(items) >= 2


def _ensure_market_results_list(background: bool = False) -> Dict:
    steps = []
    path = take_screenshot(WINDOW_TITLE)
    image = _load_screenshot(path)
    if _market_result_list_looks_visible(image):
        return _result("ensure_market_results_list", success=True, alreadyVisible=True, steps=steps, screenshotPath=path)

    press_key("esc")
    time.sleep(0.5)
    after_path = take_screenshot(WINDOW_TITLE)
    after_image = _load_screenshot(after_path)
    visible = _market_result_list_looks_visible(after_image)
    steps.append(_result("market_escape_to_results", success=True, screenshotPath=after_path))
    return _result(
        "ensure_market_results_list",
        success=visible,
        alreadyVisible=False,
        steps=steps,
        screenshotPath=after_path,
    )


def _market_listing_click_point(match: Dict) -> Tuple[int, int]:
    box = match.get("box") or {}
    left = int(box.get("left", match.get("x", 0)))
    right = int(box.get("right", match.get("x", 0)))
    top = int(box.get("top", match.get("y", 0)))
    bottom = int(box.get("bottom", match.get("y", 0)))
    center_x = int(match.get("x", (left + right) / 2))
    results_left, results_top, results_right, results_bottom = _resolve_trading_roi_bounds(TRADING_HOUSE_RESULTS_ROI)
    body_x = max(results_left + 40, min(center_x, results_right - 40))
    body_y = bottom + 110
    if body_y < top + 60:
        body_y = top + 80
    body_y = max(results_top + 40, min(body_y, results_bottom - 40))
    return body_x, body_y


def _read_ocr_text_from_roi(image: Image.Image, roi: Tuple[int, int, int, int]) -> Dict:
    left, top, width, height = roi
    crop = image.crop((left, top, left + width, top + height))
    try:
        ocr = read_rapidocr_items(crop)
    except Exception as exc:
        return {"success": False, "reason": "rapidocr_error", "error": str(exc), "text": None, "items": []}
    texts = [item.get("text") for item in ocr.get("items", []) if item.get("text")]
    joined = " ".join(texts).strip() or None
    return {
        "success": bool(joined),
        "text": joined,
        "items": ocr.get("items", []),
        "roi": {"left": left, "top": top, "right": left + width, "bottom": top + height},
    }


def read_market_detail_state() -> Dict:
    path = take_screenshot(WINDOW_TITLE)
    image = _load_screenshot(path)
    title = _read_ocr_text_from_roi(image, _resolve_trading_roi(TRADING_HOUSE_SELECTED_DETAIL_TITLE_ROI, image))
    lowest = _read_ocr_text_from_roi(image, _resolve_trading_roi(TRADING_HOUSE_LOWEST_PRICE_ROI, image))
    quantity = _read_ocr_text_from_roi(image, _resolve_trading_roi(TRADING_HOUSE_QUANTITY_ROI, image))
    total_price = _read_ocr_text_from_roi(image, _resolve_trading_roi(TRADING_HOUSE_TOTAL_PRICE_ROI, image))
    current_quantity, max_quantity = _extract_quantity_pair(quantity.get("text"))
    return _result(
        "read_market_detail_state",
        success=bool(title.get("text") or lowest.get("text") or quantity.get("text")),
        itemTitle=title.get("text"),
        lowestPriceText=lowest.get("text"),
        lowestPrice=_extract_first_int(lowest.get("text")),
        quantityText=quantity.get("text"),
        currentQuantity=current_quantity,
        maxQuantity=max_quantity,
        totalPriceText=total_price.get("text"),
        totalPrice=_extract_last_int(total_price.get("text")),
        screenshotPath=path,
    )


def _click_client_point(point: Tuple[int, int], background: bool = False) -> bool:
    return click(point[0], point[1], WINDOW_TITLE, background=background)


def set_market_purchase_quantity(target_quantity: int, background: bool = False) -> Dict:
    steps = []
    if target_quantity <= 0:
        return _result("set_market_purchase_quantity", success=False, reason="invalid_target_quantity", targetQuantity=target_quantity, steps=steps)

    state = read_market_detail_state()
    steps.append(state)
    current = state.get("currentQuantity")
    maximum = state.get("maxQuantity") or 200
    if current is None:
        return _result("set_market_purchase_quantity", success=False, reason="quantity_read_failed", targetQuantity=target_quantity, steps=steps, screenshotPath=state.get("screenshotPath"))

    target = min(target_quantity, maximum)
    if current != target:
        start_x, end_x = TRADING_HOUSE_TRACK_RANGE
        ratio = (target - 1) / max(1, maximum - 1)
        width, height = _trading_house_size()
        track_x = int(round(width * (start_x + (end_x - start_x) * ratio)))
        track_y = int(round(height * TRADING_HOUSE_TRACK_Y))
        clicked_track = _click_client_point((track_x, track_y), background=background)
        steps.append(_result("click_market_quantity_track", success=clicked_track, x=track_x, y=track_y, targetQuantity=target))
        time.sleep(0.5)
        state = read_market_detail_state()
        steps.append(state)
        current = state.get("currentQuantity")

    if current is None:
        return _result("set_market_purchase_quantity", success=False, reason="quantity_read_failed_after_track", targetQuantity=target, steps=steps, screenshotPath=state.get("screenshotPath"))

    delta = target - current
    if delta != 0:
        button = _resolve_trading_point(TRADING_HOUSE_PLUS_BUTTON if delta > 0 else TRADING_HOUSE_MINUS_BUTTON)
        action = "click_market_quantity_plus" if delta > 0 else "click_market_quantity_minus"
        for index in range(abs(delta)):
            _click_client_point(button, background=background)
            time.sleep(0.04)
        time.sleep(0.4)
        state = read_market_detail_state()
        steps.append(_result(action, clicks=abs(delta), x=button[0], y=button[1]))
        steps.append(state)
        current = state.get("currentQuantity")

    return _result(
        "set_market_purchase_quantity",
        success=current == target,
        targetQuantity=target,
        finalQuantity=current,
        maxQuantity=maximum,
        totalPrice=state.get("totalPrice"),
        steps=steps,
        screenshotPath=state.get("screenshotPath"),
    )


def buy_market_item(item_name: str, quantity: int, background: bool = False) -> Dict:
    steps = []
    select = click_market_item_by_name(item_name, background=background)
    steps.append(select)
    if not select.get("clicked"):
        return _result("buy_market_item", success=False, reason="market_item_not_selected", itemName=item_name, targetQuantity=quantity, steps=steps, screenshotPath=select.get("afterScreenshotPath") or select.get("screenshotPath"))

    set_quantity = set_market_purchase_quantity(quantity, background=background)
    steps.append(set_quantity)
    if not set_quantity.get("success"):
        return _result("buy_market_item", success=False, reason="market_quantity_not_set", itemName=item_name, targetQuantity=quantity, steps=steps, screenshotPath=set_quantity.get("screenshotPath"))

    buy_button = _resolve_trading_point(TRADING_HOUSE_BUY_BUTTON)
    clicked = _click_client_point(buy_button, background=background)
    time.sleep(1.0)
    after_path = take_screenshot(WINDOW_TITLE)
    after_image = _load_screenshot(after_path)
    banner = _read_ocr_text_from_roi(after_image, _resolve_trading_roi(TRADING_HOUSE_BANNER_ROI, after_image))
    success = "购买成功" in (banner.get("text") or "")
    steps.append(_result("click_market_buy_button", success=clicked, x=buy_button[0], y=buy_button[1]))
    steps.append(_result("read_market_buy_banner", success=success, text=banner.get("text")))
    exit_path = None
    if success:
        press_key("esc")
        time.sleep(0.6)
        exit_path = take_screenshot(WINDOW_TITLE)
        steps.append(_result("exit_market_purchase_detail", success=True, key="esc", screenshotPath=exit_path))
    return _result(
        "buy_market_item",
        success=success,
        itemName=item_name,
        targetQuantity=quantity,
        finalQuantity=set_quantity.get("finalQuantity"),
        totalPrice=set_quantity.get("totalPrice"),
        bannerText=banner.get("text"),
        steps=steps,
        screenshotPath=exit_path or after_path,
        detailScreenshotPath=after_path,
    )


def buy_market_item_quantity(item_name: str, quantity: int, background: bool = False) -> Dict:
    if quantity <= 0:
        return _result(
            "buy_market_item_quantity",
            success=False,
            reason="invalid_target_quantity",
            itemName=item_name,
            targetQuantity=quantity,
            completedQuantity=0,
            batches=[],
        )

    steps = []
    select = click_market_item_by_name(item_name, background=background)
    steps.append(select)
    if not select.get("clicked"):
        return _result(
            "buy_market_item_quantity",
            success=False,
            reason="market_item_not_selected",
            itemName=item_name,
            targetQuantity=quantity,
            completedQuantity=0,
            batches=[],
            steps=steps,
            screenshotPath=select.get("afterScreenshotPath") or select.get("screenshotPath"),
        )

    detail_state = read_market_detail_state()
    steps.append(detail_state)
    batch_limit = detail_state.get("maxQuantity") or 200
    if batch_limit <= 0:
        batch_limit = 200

    remaining = quantity
    completed = 0
    total_price = 0
    batches = []
    latest_screenshot = detail_state.get("screenshotPath")

    while remaining > 0:
        batch_quantity = min(remaining, batch_limit)
        batch_steps = []
        set_quantity = set_market_purchase_quantity(batch_quantity, background=background)
        batch_steps.append(set_quantity)
        if not set_quantity.get("success"):
            batches.append(
                {
                    "quantity": batch_quantity,
                    "success": False,
                    "reason": "market_quantity_not_set",
                    "steps": batch_steps,
                    "screenshotPath": set_quantity.get("screenshotPath"),
                }
            )
            latest_screenshot = set_quantity.get("screenshotPath") or latest_screenshot
            return _result(
                "buy_market_item_quantity",
                success=False,
                reason="market_quantity_not_set",
                itemName=item_name,
                targetQuantity=quantity,
                completedQuantity=completed,
                remainingQuantity=remaining,
                batchLimit=batch_limit,
                totalPrice=total_price,
                batches=batches,
                steps=steps,
                screenshotPath=latest_screenshot,
            )

        buy_button = _resolve_trading_point(TRADING_HOUSE_BUY_BUTTON)
        clicked = _click_client_point(buy_button, background=background)
        time.sleep(1.0)
        after_path = take_screenshot(WINDOW_TITLE)
        after_image = _load_screenshot(after_path)
        banner = _read_ocr_text_from_roi(after_image, _resolve_trading_roi(TRADING_HOUSE_BANNER_ROI, after_image))
        banner_text = banner.get("text") or ""
        success = ("购买成功" in banner_text) or ("璐拱鎴愬姛" in banner_text)
        batch_steps.append(_result("click_market_buy_button", success=clicked, x=buy_button[0], y=buy_button[1]))
        batch_steps.append(_result("read_market_buy_banner", success=success, text=banner.get("text")))

        batch_total_price = set_quantity.get("totalPrice") or 0
        batches.append(
            {
                "quantity": batch_quantity,
                "success": success,
                "totalPrice": batch_total_price,
                "bannerText": banner.get("text"),
                "steps": batch_steps,
                "screenshotPath": after_path,
            }
        )
        latest_screenshot = after_path

        if not success:
            return _result(
                "buy_market_item_quantity",
                success=False,
                reason="market_buy_not_confirmed",
                itemName=item_name,
                targetQuantity=quantity,
                completedQuantity=completed,
                remainingQuantity=remaining,
                batchLimit=batch_limit,
                totalPrice=total_price,
                batches=batches,
                steps=steps,
                screenshotPath=latest_screenshot,
            )

        completed += batch_quantity
        remaining -= batch_quantity
        total_price += batch_total_price

    exit_path = None
    press_key("esc")
    time.sleep(0.6)
    exit_path = take_screenshot(WINDOW_TITLE)
    steps.append(_result("exit_market_purchase_detail", success=True, key="esc", screenshotPath=exit_path))
    return _result(
        "buy_market_item_quantity",
        success=True,
        itemName=item_name,
        targetQuantity=quantity,
        completedQuantity=completed,
        remainingQuantity=remaining,
        batchLimit=batch_limit,
        totalPrice=total_price,
        batches=batches,
        steps=steps,
        screenshotPath=exit_path or latest_screenshot,
        detailScreenshotPath=latest_screenshot,
    )


def click_market_item_by_name(target_name: str, background: bool = False) -> Dict:
    ensure_list = _ensure_market_results_list(background=background)
    steps = [ensure_list]
    if not ensure_list.get("success"):
        return _result(
            "click_market_item_by_name",
            itemName=target_name,
            found=False,
            reason="market_results_not_visible",
            steps=steps,
            screenshotPath=ensure_list.get("screenshotPath"),
        )

    path = take_screenshot(WINDOW_TITLE)
    image = _load_screenshot(path)
    search = _find_market_item_candidates(target_name, image)
    candidates = search.get("candidates", [])
    if not candidates:
        return _result(
            "click_market_item_by_name",
            itemName=target_name,
            found=False,
            reason=search.get("reason", "market_item_not_found"),
            steps=steps,
            roi=search.get("roi"),
            ocrTexts=search.get("ocrTexts", []),
            screenshotPath=path,
        )

    target = candidates[0]
    click_x, click_y = _market_listing_click_point(target)
    clicked = click(click_x, click_y, WINDOW_TITLE, background=background)
    time.sleep(0.4)
    after_path = take_screenshot(WINDOW_TITLE)
    after_image = _load_screenshot(after_path)
    verification = _verify_market_selection(target_name, after_image, target.get("box") or {})
    return _result(
        "click_market_item_by_name",
        itemName=target_name,
        found=True,
        clicked=clicked,
        selectedMatch=target,
        clickPoint={"x": click_x, "y": click_y},
        candidates=candidates[:5],
        verification=verification,
        verified=verification.get("verified", False),
        steps=steps,
        screenshotPath=path,
        afterScreenshotPath=after_path,
    )


def redeem_department_item(
    department_name: str,
    item_name: str,
    times: int = 1,
    background: bool = False,
) -> Dict:
    if times <= 0:
        return _result(
            "redeem_department_item",
            success=False,
            departmentName=department_name,
            itemName=item_name,
            requestedTimes=times,
            reason="invalid_times",
        )

    navigation = []
    quartermaster = detect_text_by_ocr("军需处")
    if quartermaster.get("found"):
        action = click_text_by_ocr("军需处", background=background)
        navigation.append(action)
        if not action.get("clicked"):
            return _result(
                "redeem_department_item",
                success=False,
                departmentName=department_name,
                itemName=item_name,
                requestedTimes=times,
                completedTimes=0,
                reason="navigation_failed",
                failedLabel="军需处",
                navigation=navigation,
            )
        time.sleep(0.8)

    for label in (department_name, item_name):
        action = click_text_by_ocr(label, background=background)
        navigation.append(action)
        if not action.get("clicked"):
            return _result(
                "redeem_department_item",
                success=False,
                departmentName=department_name,
                itemName=item_name,
                requestedTimes=times,
                completedTimes=0,
                reason="navigation_failed",
                failedLabel=label,
                navigation=navigation,
            )
        time.sleep(0.8)

    rounds = []
    completed_times = 0
    for round_index in range(1, times + 1):
        sold_out = detect_text_by_ocr("已售")
        if sold_out.get("found"):
            rounds.append(
                {
                    "round": round_index,
                    "success": False,
                    "reason": "sold_out",
                    "soldOut": sold_out,
                }
            )
            break

        round_result = {"round": round_index}
        fill = detect_text_by_ocr("一键补齐")
        round_result["fillAvailable"] = fill
        if fill.get("found"):
            fill_click = click_text_by_ocr("一键补齐", background=background)
            round_result["fillClick"] = fill_click
            if not fill_click.get("clicked"):
                round_result.update(success=False, reason="fill_click_failed")
                rounds.append(round_result)
                break
            time.sleep(0.8)

            fill_confirm = click_fill_confirm(background=background)
            round_result["fillConfirm"] = fill_confirm
            if not fill_confirm.get("clicked"):
                round_result.update(success=False, reason="fill_confirm_not_found")
                rounds.append(round_result)
                break
            time.sleep(0.8)

        exchange_click = click_text_by_ocr("兑换", background=background)
        round_result["exchangeClick"] = exchange_click
        if not exchange_click.get("clicked"):
            round_result.update(success=False, reason="exchange_button_not_found")
            rounds.append(round_result)
            break
        time.sleep(0.8)

        confirm_click = click_text_by_ocr("确认", background=background)
        round_result["confirmClick"] = confirm_click
        if not confirm_click.get("clicked"):
            round_result.update(success=False, reason="exchange_confirm_not_found")
            rounds.append(round_result)
            break

        completed_times += 1
        round_result.update(success=True)
        rounds.append(round_result)
        time.sleep(1.0)

    final_path = take_screenshot(WINDOW_TITLE)
    return _result(
        "redeem_department_item",
        success=completed_times == times,
        departmentName=department_name,
        itemName=item_name,
        requestedTimes=times,
        completedTimes=completed_times,
        navigation=navigation,
        rounds=rounds,
        screenshotPath=final_path,
    )


def click_item_by_ocr_text(item_name: str, background: bool = False) -> Dict:
    path = take_screenshot(WINDOW_TITLE)
    image = _load_screenshot(path)
    query = _normalize_ocr_match_text(item_name)
    if not query:
        return _result("click_item_by_ocr_text", itemName=item_name, found=False, reason="empty_query", screenshotPath=path)

    try:
        ocr = read_rapidocr_items(image)
    except Exception as exc:
        return _result(
            "click_item_by_ocr_text",
            itemName=item_name,
            found=False,
            reason="rapidocr_error",
            error=str(exc),
            screenshotPath=path,
        )

    candidates = []
    for item in ocr.get("items", []):
        text = item.get("text") or ""
        normalized = _normalize_ocr_match_text(text)
        if query in normalized or normalized in query:
            box = item.get("box") or {}
            x = box.get("x")
            y = box.get("y")
            if x is None or y is None:
                continue
            candidates.append({"text": text, "x": x, "y": y, "score": item.get("score"), "box": box})

    if not candidates:
        return _result(
            "click_item_by_ocr_text",
            itemName=item_name,
            found=False,
            reason="ocr_text_not_found",
            ocrTexts=[item.get("text") for item in ocr.get("items", [])],
            screenshotPath=path,
        )

    target = max(candidates, key=lambda item: item.get("score") or 0)
    clicked = click(int(target["x"]), int(target["y"]), WINDOW_TITLE, background=background)
    time.sleep(0.3)
    after_path = take_screenshot(WINDOW_TITLE)
    return _result(
        "click_item_by_ocr_text",
        itemName=item_name,
        found=True,
        clicked=clicked,
        target=target,
        screenshotPath=path,
        afterScreenshotPath=after_path,
    )


def produce_station_item(
    station_name: str,
    item_name: str,
    background: bool = False,
    dry_run: bool = False,
    ensure_window: bool = True,
    profit_guard: bool = True,
) -> Dict:
    steps = []

    if station_name not in STATIONS:
        return _result(
            "produce_station_item",
            success=False,
            reason="unknown_station",
            station=station_name,
            itemName=item_name,
            knownStations=list(STATIONS),
            steps=steps,
        )

    active_production, active_record = _station_has_active_production(station_name)
    if active_production:
        return _result(
            "produce_station_item",
            success=True,
            skipped=True,
            reason="station_already_producing_until_next_collect",
            station=station_name,
            itemName=item_name,
            productionRecord=active_record,
            steps=steps,
        )

    evaluation = evaluate_production_item(station_name, item_name)
    steps.append(evaluation)
    if evaluation.get("configuredStation") and not evaluation.get("stationMatches"):
        return _result(
            "produce_station_item",
            success=False,
            skipped=True,
            reason="station_item_mismatch",
            station=station_name,
            itemName=item_name,
            expectedStation=evaluation.get("configuredStation"),
            productionEvaluation=evaluation,
            steps=steps,
        )

    if profit_guard and evaluation.get("profitKnown") and evaluation.get("expectedProfit", 0) < 0:
        return _result(
            "produce_station_item",
            success=True,
            skipped=True,
            reason="expected_profit_negative",
            station=station_name,
            itemName=item_name,
            productionEvaluation=evaluation,
            steps=steps,
        )

    if ensure_window:
        window_ready = ensure_game_window_front()
        steps.append(window_ready)
        if not window_ready.get("success"):
            return _result(
                "produce_station_item",
                success=False,
                reason="game_window_not_ready",
                station=station_name,
                itemName=item_name,
                steps=steps,
            )

        steps.append(dismiss_possible_reward_overlay())

    _, overview_steps = _ensure_teqinchu_overview(background=background)
    steps.extend(overview_steps)
    station_state = check_station_state(station_name)
    steps.append(station_state)

    if station_state.get("complete"):
        collection = collect_station_if_complete(station_name, background=background, ensure_window=False)
        collection["action"] = "collect_station_before_produce"
        steps.append(collection)
        if collection.get("collected"):
            _, retry_steps = _ensure_teqinchu_overview(background=background)
            for retry_step in retry_steps:
                retry_step["action"] = f"retry_after_collect_{retry_step.get('action', 'step')}"
            steps.extend(retry_steps)
            station_state = check_station_state(station_name)
            station_state["action"] = "check_station_state_after_collect"
            steps.append(station_state)

    if station_state.get("state") == "busy_or_not_ready":
        due_for_collect, due_record = _station_due_for_collect(station_name)
        if due_record:
            steps.append(
                _result(
                    "check_station_due_for_collect_before_produce",
                    station=station_name,
                    due=due_for_collect,
                    record=due_record,
                )
            )
        if due_for_collect:
            collection = collect_station_if_complete(station_name, background=background, ensure_window=False)
            collection["action"] = "collect_due_station_before_produce"
            steps.append(collection)
            if collection.get("collected"):
                _, retry_steps = _ensure_teqinchu_overview(background=background)
                for retry_step in retry_steps:
                    retry_step["action"] = f"retry_after_due_collect_{retry_step.get('action', 'step')}"
                steps.extend(retry_steps)
                station_state = check_station_state(station_name)
                station_state["action"] = "check_station_state_after_due_collect"
                steps.append(station_state)

    if station_state.get("state") != "idle":
        return _result(
            "produce_station_item",
            success=False,
            reason=f"station_state_{station_state.get('state', 'unknown')}",
            stationState=station_state.get("state"),
            station=station_name,
            itemName=item_name,
            steps=steps,
            screenshotPath=station_state.get("screenshotPath"),
        )

    idle_click = click_station_idle_slot(station_name, background=background)
    steps.append(idle_click)
    if not idle_click.get("clicked"):
        return _result(
            "produce_station_item",
            success=False,
            reason="station_idle_slot_not_clicked",
            station=station_name,
            itemName=item_name,
            steps=steps,
            screenshotPath=idle_click.get("screenshotPath"),
        )

    if not idle_click.get("clicked"):
        return _result(
            "produce_station_item",
            success=False,
            reason="station_idle_slot_not_clicked",
            station=station_name,
            itemName=item_name,
            steps=steps,
            screenshotPath=idle_click.get("screenshotPath"),
        )

    item_click = click_button(item_name, background=background)
    item_click["action"] = "select_station_item"
    item_click["station"] = station_name
    item_click["itemName"] = item_name
    steps.append(item_click)
    if not item_click.get("clicked"):
        ocr_item_click = click_item_by_ocr_text(item_name, background=background)
        ocr_item_click["action"] = "select_station_item_by_ocr"
        ocr_item_click["station"] = station_name
        steps.append(ocr_item_click)
        if ocr_item_click.get("clicked"):
            item_click = ocr_item_click
        else:
            final_path = take_screenshot(WINDOW_TITLE)
            return _result(
                "produce_station_item",
                success=False,
                reason="item_not_selected",
                station=station_name,
                itemName=item_name,
                steps=steps,
                screenshotPath=final_path,
            )
    if not item_click.get("clicked"):
        final_path = take_screenshot(WINDOW_TITLE)
        return _result(
            "produce_station_item",
            success=False,
            reason="item_not_selected",
            station=station_name,
            itemName=item_name,
            steps=steps,
            screenshotPath=final_path,
        )

    runtime_economics = {}
    tax_after = read_screen_metric("tax_after_price")
    tax_after["action"] = "read_tax_after_price"
    steps.append(tax_after)
    if tax_after.get("success"):
        runtime_economics["unitExpectedRevenue"] = tax_after.get("value")
        runtime_economics["outputQuantity"] = evaluation.get("outputQuantity", 1)
    else:
        runtime_economics["taxAfterPriceReadError"] = tax_after.get("reason")

    if dry_run:
        actions = inspect_production_actions(item_name)
        steps.append(actions)
        remaining_time = read_screen_metric("remaining_time")
        remaining_time["action"] = "read_remaining_time"
        steps.append(remaining_time)
        if remaining_time.get("success"):
            runtime_economics["durationSeconds"] = remaining_time.get("value")
        merged_evaluation = _merge_runtime_economics(evaluation, runtime_economics)
        final_path = take_screenshot(WINDOW_TITLE)
        started_at = datetime.now()
        return _result(
            "produce_station_item",
            success=True,
            dryRun=True,
            station=station_name,
            itemName=item_name,
            productionEvaluation=merged_evaluation,
            productionReport=_production_report(station_name, item_name, merged_evaluation, started_at),
            oneClickFillFound=actions.get("oneClickFillFound", False),
            produceButtonFound=actions.get("produceButtonFound", False),
            steps=steps,
            screenshotPath=final_path,
        )

    material_step = prepare_materials_if_needed(
        background=background,
        expected_revenue=_merge_runtime_economics(evaluation, runtime_economics).get("expectedRevenue"),
        profit_guard=profit_guard,
    )
    steps.append(material_step)
    if material_step.get("estimatedCost") is not None:
        runtime_economics["estimatedCost"] = material_step.get("estimatedCost")
    if material_step.get("expectedRevenue") is not None:
        runtime_economics["expectedRevenue"] = material_step.get("expectedRevenue")
    merged_evaluation = _merge_runtime_economics(evaluation, runtime_economics)
    if material_step.get("skipped"):
        return _result(
            "produce_station_item",
            success=True,
            skipped=True,
            reason=material_step.get("reason"),
            station=station_name,
            itemName=item_name,
            productionEvaluation=merged_evaluation,
            steps=steps,
            screenshotPath=material_step.get("screenshotPath"),
        )
    if not material_step.get("success"):
        return _result(
            "produce_station_item",
            success=False,
            reason=material_step.get("reason", "materials_not_ready"),
            station=station_name,
            itemName=item_name,
            productionEvaluation=merged_evaluation,
            steps=steps,
            screenshotPath=material_step.get("screenshotPath"),
        )

    produce_click = click_produce_button(background=background)
    steps.append(produce_click)
    started_at = datetime.now()
    final_path = take_screenshot(WINDOW_TITLE)
    final_image = _load_screenshot(final_path)
    game_width = final_image.width
    production_in_progress = find_button(final_image, GAME_ID, "production_in_progress", game_width=game_width) is not None
    remaining_time = read_rapidocr_value(final_image, GAME_ID, "remaining_time")
    if remaining_time.get("success"):
        runtime_economics["durationSeconds"] = remaining_time.get("value")
        merged_evaluation = _merge_runtime_economics(evaluation, runtime_economics)
    production_report = _production_report(station_name, item_name, merged_evaluation, started_at)
    if produce_click.get("clicked"):
        _record_station_production(production_report)

    return _result(
        "produce_station_item",
        success=bool(produce_click.get("clicked")),
        station=station_name,
        itemName=item_name,
        productionEvaluation=merged_evaluation,
        productionReport=production_report,
        materialsFilled=material_step.get("needed", False),
        productionInProgress=production_in_progress,
        remainingTimeRead=remaining_time,
        steps=steps,
        screenshotPath=final_path,
    )


def produce_station_items(
    item_specs: Dict[str, str],
    background: bool = False,
    dry_run: bool = False,
    profit_guard: bool = True,
) -> Dict:
    steps = []
    produced = []
    skipped = []
    skipped_reasons = {}
    reports = []
    failures = []

    unknown = [station for station in item_specs if station not in STATIONS]
    if unknown:
        return _result(
            "produce_station_items",
            success=False,
            reason="unknown_station",
            unknownStations=unknown,
            knownStations=list(STATIONS),
            itemSpecs=item_specs,
            steps=steps,
        )

    window_ready = ensure_game_window_front()
    steps.append(window_ready)
    if not window_ready.get("success"):
        return _result(
            "produce_station_items",
            success=False,
            reason="game_window_not_ready",
            itemSpecs=item_specs,
            steps=steps,
        )

    safe_check = check_game_safe_for_automation()
    steps.append(safe_check)
    if not safe_check.get("safe"):
        return _result(
            "produce_station_items",
            success=False,
            reason="game_unsafe_for_automation",
            reasonDetail=safe_check.get("reason"),
            detectedState=safe_check.get("detectedState"),
            itemSpecs=item_specs,
            produced=produced,
            skipped=list(item_specs.values()),
            steps=steps,
            screenshotPath=safe_check.get("screenshotPath"),
        )

    steps.append(dismiss_possible_reward_overlay())

    for station in STATIONS:
        item_name = item_specs.get(station)
        if not item_name:
            continue

        result = produce_station_item(
            station,
            item_name,
            background=background,
            dry_run=dry_run,
            ensure_window=False,
            profit_guard=profit_guard,
        )
        steps.append(result)
        if result.get("skipped"):
            skipped.append(station)
            skipped_reasons[station] = result.get("reason")
        elif result.get("success"):
            produced.append(station)
        else:
            skipped.append(station)
            skipped_reasons[station] = result.get("reason")
            failures.append(station)
        if result.get("productionReport"):
            reports.append(result["productionReport"])
        time.sleep(0.5)

    final_overview = _ensure_teqinchu_overview(background=background)
    final_idle, final_overview_steps = final_overview
    for step in final_overview_steps:
        step["action"] = f"final_return_to_overview_{step.get('action', 'step')}"
    steps.extend(final_overview_steps)

    final_path = take_screenshot(WINDOW_TITLE)
    return _result(
        "produce_station_items",
        success=len(failures) == 0,
        dryRun=dry_run,
        profitGuard=profit_guard,
        itemSpecs=item_specs,
        produced=produced,
        skipped=skipped,
        skippedReasons=skipped_reasons,
        productionReports=reports,
        finalOverviewReady=bool(final_idle.get("success")),
        finalOverview=final_idle,
        steps=steps,
        screenshotPath=final_path,
    )


def produce_762x51mm_m62(
    background: bool = False,
    dry_run: bool = False,
    profit_guard: bool = True,
) -> Dict:
    result = produce_station_item(
        "workbench",
        ITEM_762X51MM_M62,
        background=background,
        dry_run=dry_run,
        profit_guard=profit_guard,
    )
    result["action"] = "produce_762x51mm_m62"
    result["selectedItem"] = ITEM_762X51MM_M62
    return result


def produce_762x51_example(
    background: bool = False,
    dry_run: bool = False,
    profit_guard: bool = True,
) -> Dict:
    return produce_762x51mm_m62(background=background, dry_run=dry_run, profit_guard=profit_guard)


def click_button(button_name: str, threshold: float = 0.8, background: bool = False) -> Dict:
    path = take_screenshot(WINDOW_TITLE)
    image = _load_screenshot(path)
    game_width = image.width
    button = find_button(image, GAME_ID, button_name, threshold=threshold, game_width=game_width)
    if not button:
        return _result("click_button", buttonName=button_name, found=False, screenshotPath=path)

    success = click(button["x"], button["y"], WINDOW_TITLE, background=background)
    time.sleep(0.3)
    after_path = take_screenshot(WINDOW_TITLE)
    return _result(
        "click_button",
        buttonName=button_name,
        found=True,
        clicked=success,
        x=button["x"],
        y=button["y"],
        confidence=button["confidence"],
        screenshotPath=path,
        afterScreenshotPath=after_path,
    )


def _parse_click_coordinates_from_content(content: str) -> Tuple[Optional[int], Optional[int], Optional[str]]:
    """从模型纯文本回复里解析一行 JSON：{{\"x\":..,\"y\":..}} 或 x/y 为 null。"""
    text = (content or "").strip()
    if not text:
        return None, None, "模型回复为空"
    if "```" in text:
        stripped = []
        in_fence = False
        for line in text.splitlines():
            if line.strip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence or (not stripped and "{" in line):
                stripped.append(line)
        if stripped:
            text = "\n".join(stripped)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None, None, "回复中未找到 JSON"
    try:
        obj = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None, None, "JSON 解析失败"
    x, y = obj.get("x"), obj.get("y")
    if x is None or y is None:
        reason = obj.get("reason")
        if isinstance(reason, str) and reason:
            return None, None, reason
        return None, None, "模型未给出可点击坐标"
    try:
        return int(x), int(y), None
    except (TypeError, ValueError):
        return None, None, "坐标不是有效整数"


def click_text(text: str, dry_run: bool = False) -> Dict:
    path = take_screenshot(WINDOW_TITLE)
    image = _load_screenshot(path)
    config = get_gui_agent_config()
    agent = AliyunGUIAgent(
        api_key=get_api_key(),
        base_url=config.get("base_url"),
        model=config.get("model"),
    )
    instruction = (
        f"用户要点击的界面元素（中文或英文描述均可）：{text}\n\n"
        "请根据当前截图判断该元素中心点在画面中的像素坐标（相对截图左上角）。\n"
        "请只输出一行 JSON，不要其它文字或 Markdown：\n"
        '{"x": 整数, "y": 整数}\n'
        "若无法可靠定位，请输出：\n"
        '{"x": null, "y": null, "reason": "简短中文原因"}'
    )
    result = agent.analyze(image, instruction)
    if not result.success:
        return _result("click_text", text=text, found=False, error=result.error, screenshotPath=path)

    cx, cy, parse_err = _parse_click_coordinates_from_content(result.content or "")
    if cx is None or cy is None:
        return _result(
            "click_text",
            text=text,
            found=False,
            error=parse_err or "无法解析坐标",
            modelReply=result.content,
            screenshotPath=path,
        )

    if (
        result.original_image_size
        and result.sent_image_size
        and result.original_image_size != result.sent_image_size
    ):
        ow, oh = result.original_image_size
        sw, sh = result.sent_image_size
        if sw > 0 and sh > 0:
            cx = int(round(cx * ow / sw))
            cy = int(round(cy * oh / sh))

    if dry_run:
        return _result(
            "click_text",
            text=text,
            found=True,
            dryRun=True,
            x=cx,
            y=cy,
            modelReply=result.content,
            screenshotPath=path,
        )

    success = click(cx, cy, WINDOW_TITLE)
    time.sleep(0.3)
    after_path = take_screenshot(WINDOW_TITLE)
    return _result(
        "click_text",
        text=text,
        found=True,
        clicked=success,
        x=cx,
        y=cy,
        modelReply=result.content,
        screenshotPath=path,
        afterScreenshotPath=after_path,
    )


def get_status() -> Dict:
    """
    Aggregated status for agent guardianship. Read-only, no screenshots.
    Combines production state, scheduler info, and last run summary.
    """
    now = datetime.now()

    # ── Production state ──
    action_plan = compute_next_action()
    prod_state = _load_production_state()

    # ── Game process check (lightweight) ──
    game_running = False
    window_visible = False
    try:
        import subprocess
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq DeltaForceClient-Win64-Shipping.exe"],
            capture_output=True, text=True, timeout=5
        )
        game_running = "DeltaForceClient" in result.stdout
    except Exception:
        game_running = None

    if game_running:
        try:
            from scripts.window import get_window_handle
            hwnd = get_window_handle(WINDOW_TITLE)
            window_visible = hwnd is not None
        except Exception:
            window_visible = None

    # ── Recent log info ──
    recent_log = None
    log_entries = []
    log_dir = ROOT_DIR / "logs"
    if log_dir.exists():
        log_files = sorted(
            log_dir.glob("scheduled_collect_produce_*.log"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        for lf in log_files[:5]:
            entry = {
                "logFile": lf.name,
                "sizeBytes": lf.stat().st_size,
                "modifiedAt": datetime.fromtimestamp(lf.stat().st_mtime).isoformat(),
            }
            log_entries.append(entry)
            if recent_log is None:
                recent_log = lf

    # ── Build summary text ──
    summary_parts = []
    if action_plan.get("needAction"):
        due = action_plan.get("dueStations", [])
        idle = action_plan.get("idleStations", [])
        if due:
            summary_parts.append(f"{', '.join(due)} 已完成待收取")
        if idle:
            summary_parts.append(f"{', '.join(idle)} 空闲无生产")
    else:
        producing_info = action_plan.get("producing", [])
        if producing_info:
            earliest = None
            for p in producing_info:
                nc = p.get("nextCollectAt")
                if nc:
                    try:
                        dt = datetime.fromisoformat(nc)
                        if earliest is None or dt < earliest:
                            earliest = dt
                            earliest_station = p.get("station", "?")
                    except ValueError:
                        pass
            if earliest:
                delta_min = int((earliest - now).total_seconds() / 60)
                summary_parts.append(f"全部生产中, 最早 {earliest_station} {earliest.strftime('%H:%M')} 到期 ({delta_min}分钟后)")
            else:
                summary_parts.append("全部生产中")
        else:
            summary_parts.append("无活跃生产")

    summary = "; ".join(summary_parts) if summary_parts else "状态未知"

    return _result(
        "status",
        checkedAt=now.isoformat(timespec="seconds"),
        summary=summary,
        actionPlan=action_plan,
        gameRunning=game_running,
        windowVisible=window_visible,
        productionState={
            station: prod_state.get("stations", {}).get(station)
            for station in STATIONS
        },
        recentLogs=log_entries,
        logsDir=str(log_dir),
    )
