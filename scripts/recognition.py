import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import cv2
import numpy as np
from PIL import Image


ROOT_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = ROOT_DIR / "games"
TEMPLATE_BASE_WIDTH = 3840
_button_configs: Dict[str, Dict] = {}


def _load_button_config(game_id: str) -> Dict:
    if game_id in _button_configs:
        return _button_configs[game_id]

    config_path = ASSETS_DIR / game_id / "assets" / "buttons.json"
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as f:
            _button_configs[game_id] = json.load(f)
    else:
        _button_configs[game_id] = {}
    return _button_configs[game_id]


def _parse_roi_expr(expr: Union[int, str], width: int, height: int) -> int:
    if isinstance(expr, int):
        return expr
    value = expr.replace("width", str(width)).replace("height", str(height))
    try:
        return int(eval(value, {"__builtins__": {}}))
    except Exception:
        return 0


def _get_roi(config: Dict, width: int, height: int) -> Optional[Tuple[int, int, int, int]]:
    roi = config.get("roi")
    if not roi:
        return None
    return (
        _parse_roi_expr(roi[0], width, height),
        _parse_roi_expr(roi[1], width, height),
        _parse_roi_expr(roi[2], width, height),
        _parse_roi_expr(roi[3], width, height),
    )


def pil_to_cv2(image: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


def list_available_buttons(game_id: str) -> list:
    buttons_dir = ASSETS_DIR / game_id / "assets" / "buttons"
    if not buttons_dir.exists():
        return []
    return sorted(path.stem for path in buttons_dir.rglob("*.png"))


def load_template(game_id: str, button_name: str, scale: float = 1.0) -> Optional[np.ndarray]:
    buttons_dir = ASSETS_DIR / game_id / "assets" / "buttons"
    template_path = buttons_dir / f"{button_name}.png"
    if not template_path.exists():
        matches = sorted(path for path in buttons_dir.rglob(f"{button_name}.png") if path.is_file())
        if not matches:
            return None
        template_path = matches[0]

    data = np.fromfile(os.fspath(template_path), dtype=np.uint8)
    template = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if template is None:
        return None

    if scale != 1.0:
        new_width = max(1, int(template.shape[1] * scale))
        new_height = max(1, int(template.shape[0] * scale))
        template = cv2.resize(template, (new_width, new_height), interpolation=cv2.INTER_AREA)
    return template


def _get_template_scales(config: Dict, game_width: Optional[int]) -> List[float]:
    base_scale = (game_width / TEMPLATE_BASE_WIDTH) if game_width else 1.0
    multiplier = float(config.get("scale", 1.0))
    center = max(0.05, base_scale * multiplier)
    if config.get("scales"):
        return [max(0.05, base_scale * float(item)) for item in config["scales"]]
    if config.get("multi_scale", True):
        return sorted({round(center * factor, 4) for factor in (0.9, 1.0, 1.1)})
    return [center]


def find_button(
    screenshot: Image.Image,
    game_id: str,
    button_name: str,
    threshold: float = 0.8,
    game_width: Optional[int] = None,
) -> Optional[Dict]:
    """
    Find a single button in the screenshot using template matching.
    
    Args:
        screenshot: PIL Image of the game screen
        game_id: Game identifier (e.g., 'delta-force')
        button_name: Name of the button template (without .png)
        threshold: Minimum matching confidence (0-1)
        game_width: Current game window width for template scaling
    
    Returns:
        Dict with x, y, width, height, confidence, or None if not found
    """
    config = _load_button_config(game_id).get(button_name, {})
    source = pil_to_cv2(screenshot)
    height, width = source.shape[:2]
    threshold = config.get("threshold", threshold)
    roi = _get_roi(config, width, height)
    use_3_channels = config.get("use_3_channels", False)

    offset_x = offset_y = 0
    if roi:
        x, y, w, h = roi
        if x < 0 or y < 0 or x + w > width or y + h > height:
            return None
        source = source[y : y + h, x : x + w]
        offset_x, offset_y = x, y

    best = None
    match_mode = config.get("match_mode")
    for scale in _get_template_scales(config, game_width):
        template = load_template(game_id, button_name, scale)
        if template is None:
            continue
        if match_mode == "masked_text":
            source_display = source
            template_display = template
            hsv = cv2.cvtColor(template_display, cv2.COLOR_BGR2HSV)
            lower = np.array(config.get("mask_lower_hsv", [0, 0, 150]), dtype=np.uint8)
            upper = np.array(config.get("mask_upper_hsv", [180, 90, 255]), dtype=np.uint8)
            template_mask = cv2.inRange(hsv, lower, upper)
            template_mask = cv2.dilate(template_mask, np.ones((3, 3), np.uint8), iterations=1)
        elif use_3_channels:
            source_display = source
            template_display = template
            template_mask = None
        else:
            source_display = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
            template_display = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
            template_mask = None

        if source_display.shape[0] < template_display.shape[0] or source_display.shape[1] < template_display.shape[1]:
            continue

        if match_mode == "masked_text":
            result = cv2.matchTemplate(source_display, template_display, cv2.TM_CCORR_NORMED, mask=template_mask)
        else:
            result = cv2.matchTemplate(source_display, template_display, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if best is None or max_val > best["confidence"]:
            h, w = template_display.shape[:2]
            best = {
                "x": offset_x + max_loc[0] + w // 2,
                "y": offset_y + max_loc[1] + h // 2,
                "width": w,
                "height": h,
                "confidence": float(max_val),
                "scale": scale,
            }

    if not best or best["confidence"] < threshold:
        return None

    return {
        "x": best["x"],
        "y": best["y"],
        "width": best["width"],
        "height": best["height"],
        "confidence": round(float(best["confidence"]), 3),
        "scale": round(float(best["scale"]), 4),
    }


def find_all_buttons(
    screenshot: Image.Image,
    game_id: str,
    game_width: Optional[int] = None,
    threshold: float = 0.8,
) -> Dict[str, List[Dict]]:
    """
    Find all buttons in the screenshot.
    
    Returns:
        Dict mapping button_name to list of matches (x, y, width, height, confidence)
    """
    results = {}
    for button_name in list_available_buttons(game_id):
        matches = find_all_template_matches(screenshot, game_id, button_name, game_width, threshold)
        if matches:
            results[button_name] = matches
    return results


def find_all_template_matches(
    screenshot: Image.Image,
    game_id: str,
    button_name: str,
    game_width: Optional[int] = None,
    threshold: float = 0.8,
    max_results: int = 10,
) -> List[Dict]:
    """
    Find all instances of a button template in the screenshot.
    After finding one, masks the region and continues to find more.
    
    Args:
        screenshot: PIL Image
        game_id: Game identifier
        button_name: Template name
        game_width: Window width for scaling
        threshold: Minimum confidence
        max_results: Maximum number of matches to find
    
    Returns:
        List of dicts with x, y, width, height, confidence
    """
    config = _load_button_config(game_id).get(button_name, {})
    threshold = config.get("threshold", threshold)
    single = find_button(screenshot, game_id, button_name, threshold=threshold, game_width=game_width)
    scale = single.get("scale") if single else None
    template = load_template(game_id, button_name, scale or 1.0)
    if template is None:
        return []

    source = pil_to_cv2(screenshot)
    height, width = source.shape[:2]
    use_3_channels = config.get("use_3_channels", False)
    roi = _get_roi(config, width, height)
    offset_x = offset_y = 0
    if roi:
        x, y, w, h = roi
        if x < 0 or y < 0 or x + w > width or y + h > height:
            return []
        source = source[y : y + h, x : x + w]
        offset_x, offset_y = x, y

    if use_3_channels:
        source_gray = source
        template_gray = template
    else:
        source_gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
        template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)

    if source_gray.shape[0] < template_gray.shape[0] or source_gray.shape[1] < template_gray.shape[1]:
        return []

    th, tw = template_gray.shape[:2]
    result_map = cv2.matchTemplate(source_gray, template_gray, cv2.TM_CCOEFF_NORMED)
    
    matches = []
    mask = np.ones(result_map.shape, dtype=np.uint8) * 255
    
    for _ in range(max_results):
        _, max_val, _, max_loc = cv2.minMaxLoc(result_map, mask)
        if max_val < threshold:
            break
        
        # Add padding around the match to mask it out
        pad = max(th // 2, 20)
        x1 = max(0, max_loc[0] - pad)
        x2 = min(result_map.shape[1], max_loc[0] + tw + pad)
        y1 = max(0, max_loc[1] - pad)
        y2 = min(result_map.shape[0], max_loc[1] + th + pad)
        mask[y1:y2, x1:x2] = 0
        
        matches.append({
            "x": offset_x + max_loc[0] + tw // 2,
            "y": offset_y + max_loc[1] + th // 2,
            "width": tw,
            "height": th,
            "confidence": round(float(max_val), 3),
            "scale": round(float(scale or 1.0), 4),
        })
    
    return matches


def find_color_regions(
    screenshot: Image.Image,
    lower_bound: Tuple[int, int, int],
    upper_bound: Tuple[int, int, int],
    min_area: int = 100,
    roi: Optional[Tuple[int, int, int, int]] = None,
) -> List[Dict]:
    """
    Find regions matching a specific color range (e.g., yellow badges).
    
    Args:
        screenshot: PIL Image
        lower_bound: HSV lower bound (H, S, V)
        upper_bound: HSV upper bound
        min_area: Minimum contour area to consider
        roi: Optional (x, y, w, h) region to search in
    
    Returns:
        List of dicts with x, y, width, height, area, center
    """
    source = pil_to_cv2(screenshot)
    height, width = source.shape[:2]
    
    if roi:
        x, y, w, h = roi
        if x < 0 or y < 0 or x + w > width or y + h > height:
            return []
        source = source[y : y + h, x : x + w]
    
    hsv = cv2.cvtColor(source, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(lower_bound), np.array(upper_bound))
    
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    results = []
    for cnt in contours:
        if cv2.contourArea(cnt) < min_area:
            continue
        x, y, w, h = cv2.boundingRect(cnt)
        M = cv2.moments(cnt)
        if M["m00"] != 0:
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
        else:
            cx, cy = x + w // 2, y + h // 2
        
        results.append({
            "x": cx,
            "y": cy,
            "width": w,
            "height": h,
            "area": int(cv2.contourArea(cnt)),
            "center_x": cx,
            "center_y": cy,
        })
    
    return results


def find_yellow_badges(
    screenshot: Image.Image,
    min_area: int = 50,
    roi: Optional[Tuple[int, int, int, int]] = None,
) -> List[Dict]:
    """
    Find yellow badge regions (common for "ready to collect" indicators).
    Yellow in HSV: H=20-30, S=100-255, V=100-255
    
    Args:
        screenshot: PIL Image
        min_area: Minimum pixel area
        roi: Optional region of interest
    
    Returns:
        List of dicts with center coordinates and size
    """
    return find_color_regions(
        screenshot,
        lower_bound=(15, 80, 100),
        upper_bound=(35, 255, 255),
        min_area=min_area,
        roi=roi,
    )


def find_green_buttons(
    screenshot: Image.Image,
    min_area: int = 100,
    roi: Optional[Tuple[int, int, int, int]] = None,
) -> List[Dict]:
    """
    Find green button/indicator regions.
    Green in HSV: H=35-85, S=50-255, V=50-255
    
    Returns:
        List of dicts with center coordinates and size
    """
    return find_color_regions(
        screenshot,
        lower_bound=(35, 50, 50),
        upper_bound=(85, 255, 255),
        min_area=min_area,
        roi=roi,
    )


def match_template_multi(
    screenshot: Image.Image,
    template: np.ndarray,
    threshold: float = 0.8,
    roi: Optional[Tuple[int, int, int, int]] = None,
    max_results: int = 10,
    use_3_channels: bool = False,
) -> List[Dict]:
    """
    Multi-instance template matching with masking.
    
    Args:
        screenshot: PIL Image or np.ndarray
        template: OpenCV image template
        threshold: Minimum confidence
        roi: Optional (x, y, w, h) region to search in
        max_results: Maximum matches to find
        use_3_channels: Use color matching instead of grayscale
    
    Returns:
        List of dicts with x, y, width, height, confidence
    """
    if isinstance(screenshot, Image.Image):
        source = pil_to_cv2(screenshot)
    else:
        source = screenshot

    height, width = source.shape[:2]
    
    if roi:
        x, y, w, h = roi
        if x < 0 or y < 0 or x + w > width or y + h > height:
            return []
        source = source[y : y + h, x : x + w]
    
    if use_3_channels:
        source_display = source
        template_display = template
    else:
        source_display = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
        template_display = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)

    th, tw = template_display.shape[:2]
    result_map = cv2.matchTemplate(source_display, template_display, cv2.TM_CCOEFF_NORMED)
    
    mask = np.ones(result_map.shape, dtype=np.uint8) * 255
    matches = []
    
    for _ in range(max_results):
        _, max_val, _, max_loc = cv2.minMaxLoc(result_map, mask)
        if max_val < threshold:
            break
        
        pad = max(th // 2, 20)
        x1 = max(0, max_loc[0] - pad)
        x2 = min(result_map.shape[1], max_loc[0] + tw + pad)
        y1 = max(0, max_loc[1] - pad)
        y2 = min(result_map.shape[0], max_loc[1] + th + pad)
        mask[y1:y2, x1:x2] = 0
        
        matches.append({
            "x": max_loc[0] + tw // 2,
            "y": max_loc[1] + th // 2,
            "width": tw,
            "height": th,
            "confidence": round(float(max_val), 3),
            "match_x": max_loc[0],
            "match_y": max_loc[1],
        })
    
    return matches


def ocr_text_regions(
    screenshot: Image.Image,
    expected_text: Optional[str] = None,
) -> List[Dict]:
    """
    OCR placeholder - returns text regions for future OCR integration.
    Currently not implemented, requires PaddleOCR or similar.
    
    Returns:
        Empty list placeholder for future implementation
    """
    # TODO: Integrate PaddleOCR or similar
    return []


def find_button_with_fallback(
    screenshot: Image.Image,
    game_id: str,
    button_name: str,
    game_width: Optional[int] = None,
    use_color_fallback: bool = True,
) -> Optional[Dict]:
    """
    Find button using template matching, with color-based fallback for special buttons.
    
    Args:
        screenshot: PIL Image
        game_id: Game identifier
        button_name: Button template name
        game_width: Window width for scaling
        use_color_fallback: Use color matching if template not found
    
    Returns:
        Button match dict or None
    """
    # Try template matching first
    result = find_button(screenshot, game_id, button_name, game_width=game_width)
    if result:
        return result
    
    # Fallback for collect buttons - look for yellow badges
    if use_color_fallback and "collect" in button_name.lower():
        badges = find_yellow_badges(screenshot)
        if badges:
            # Return the first yellow badge as potential collect indicator
            return badges[0]
    
    return None
