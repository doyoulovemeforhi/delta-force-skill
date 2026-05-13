import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
from PIL import Image


ROOT_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = ROOT_DIR / "games"
_ocr_engine = None


def _get_engine():
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr import RapidOCR

        _ocr_engine = RapidOCR()
    return _ocr_engine


def _parse_roi_expr(expr: Union[int, str], width: int, height: int) -> int:
    if isinstance(expr, int):
        return expr
    value = expr.replace("width", str(width)).replace("height", str(height))
    try:
        return int(eval(value, {"__builtins__": {}}))
    except Exception:
        return 0


def _roi_from_config(config: Dict, width: int, height: int) -> Tuple[int, int, int, int]:
    roi = config.get("roi") or [0, 0, width, height]
    x = _parse_roi_expr(roi[0], width, height)
    y = _parse_roi_expr(roi[1], width, height)
    w = _parse_roi_expr(roi[2], width, height)
    h = _parse_roi_expr(roi[3], width, height)
    return max(0, x), max(0, y), max(1, w), max(1, h)


def _load_reader_config(game_id: str) -> Dict:
    path = ASSETS_DIR / game_id / "assets" / "screen_readers.json"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def parse_duration_text(text: Optional[str]) -> Optional[int]:
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
        r"(?:(\d{1,3})\s*(?:小时|小時|时|時|h|H))?\s*"
        r"(?:(\d{1,2})\s*(?:分钟|分鐘|分|m|M))?\s*"
        r"(?:(\d{1,2})\s*(?:秒|s|S))",
        cleaned,
    )
    if zh_match and any(group is not None for group in zh_match.groups()):
        hours = int(zh_match.group(1) or 0)
        minutes = int(zh_match.group(2) or 0)
        seconds = int(zh_match.group(3) or 0)
        if minutes < 60 and seconds < 60:
            return hours * 3600 + minutes * 60 + seconds
    return None


def _parse_number_text(text: Optional[str]) -> Optional[float]:
    if not isinstance(text, str):
        return None
    cleaned = text.strip().replace(",", "")
    if not cleaned:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*([kK]?)", cleaned)
    if not match:
        return None
    value = float(match.group(1))
    if match.group(2):
        value *= 1000
    return value


def _box_to_rect(box) -> Dict:
    points = np.array(box, dtype=float)
    xs = points[:, 0]
    ys = points[:, 1]
    left = int(xs.min())
    top = int(ys.min())
    right = int(xs.max())
    bottom = int(ys.max())
    return {
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
        "x": int((left + right) / 2),
        "y": int((top + bottom) / 2),
        "width": right - left,
        "height": bottom - top,
    }


def read_rapidocr_items(screenshot: Image.Image) -> Dict:
    image = screenshot.convert("RGB")
    engine = _get_engine()
    output = engine(np.array(image))
    raw_txts = getattr(output, "txts", None)
    raw_scores = getattr(output, "scores", None)
    raw_boxes = getattr(output, "boxes", None)
    txts = list(raw_txts) if raw_txts is not None else []
    scores = list(raw_scores) if raw_scores is not None else []
    boxes = list(raw_boxes) if raw_boxes is not None else []
    items: List[Dict] = []
    for index, text in enumerate(txts):
        box = boxes[index] if index < len(boxes) else [[0, 0], [0, 0], [0, 0], [0, 0]]
        score = float(scores[index]) if index < len(scores) else None
        rect = _box_to_rect(box)
        items.append({"text": text, "score": score, "box": rect})
    return {"success": bool(items), "items": items, "engine": "rapidocr"}


def read_rapidocr_value(screenshot: Image.Image, game_id: str, reader_name: str) -> Dict:
    configs = _load_reader_config(game_id)
    reader_config = configs.get(reader_name)
    if not reader_config:
        return {"readerName": reader_name, "success": False, "reason": "reader_config_missing"}

    width, height = screenshot.size
    x, y, w, h = _roi_from_config(reader_config, width, height)
    crop = screenshot.crop((x, y, min(width, x + w), min(height, y + h)))
    kind = reader_config.get("kind", "number")

    try:
        ocr = read_rapidocr_items(crop)
    except Exception as exc:
        return {
            "readerName": reader_name,
            "success": False,
            "reason": "rapidocr_error",
            "error": str(exc),
            "roi": {"left": x, "top": y, "right": x + w, "bottom": y + h},
        }

    texts = [item["text"] for item in ocr.get("items", []) if item.get("text")]
    joined = " ".join(texts).strip() or None
    value = parse_duration_text(joined) if kind == "time" else _parse_number_text(joined)

    return {
        "readerName": reader_name,
        "success": value is not None,
        "text": joined,
        "value": value,
        "kind": kind,
        "confidence": max((item.get("score") or 0 for item in ocr.get("items", [])), default=0),
        "parsed": value is not None,
        "items": ocr.get("items", []),
        "roi": {"left": x, "top": y, "right": x + w, "bottom": y + h},
        "engine": "rapidocr",
    }
