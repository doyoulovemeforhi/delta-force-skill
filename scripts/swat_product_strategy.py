import http.cookiejar
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib import parse, request

from scripts.config import get_swat_product_config


ROOT_DIR = Path(__file__).resolve().parent.parent
MAPPING_PATH = ROOT_DIR / "games" / "delta-force" / "assets" / "swat_product_mapping.json"
SNAPSHOT_DIR = ROOT_DIR / "logs" / "swat_product_snapshots"
API_URL = "https://www.kkrb.net/getSwatProductData"
HOURLY_API_URL = "https://www.kkrb.net/getSwatProductHourlyData"
MENU_URL = "https://www.kkrb.net/getMenu"
DEFAULT_REFERER = "https://www.kkrb.net/?viewpage=view%2Fswat%2Fswat_product"
HOURLY_REFERER = "https://www.kkrb.net/?viewpage=view%2Fswat%2Fswat_product_hourly"
DEFAULT_ORIGIN = "https://www.kkrb.net"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)


def _load_mapping() -> Dict[str, Any]:
    with MAPPING_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _normalize_name(value: str) -> str:
    return "".join(str(value or "").lower().split())


def _build_headers(cookie: str, swimlane: Optional[str] = None) -> Dict[str, str]:
    headers = {
        "accept": "*/*",
        "accept-language": "zh-CN,zh;q=0.9",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "origin": DEFAULT_ORIGIN,
        "referer": DEFAULT_REFERER,
        "user-agent": DEFAULT_USER_AGENT,
        "x-requested-with": "XMLHttpRequest",
        "cookie": cookie,
    }
    if swimlane:
        headers["swimlane"] = swimlane
    return headers


def _build_browser_page_headers() -> Dict[str, str]:
    return {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "accept-language": "zh-CN,zh;q=0.9",
        "cache-control": "max-age=0",
        "sec-ch-ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
        "user-agent": DEFAULT_USER_AGENT,
    }


def _build_browser_ajax_headers(referer: str, swimlane: Optional[str] = None) -> Dict[str, str]:
    headers = {
        "accept": "*/*",
        "accept-language": "zh-CN,zh;q=0.9",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "origin": DEFAULT_ORIGIN,
        "referer": referer,
        "priority": "u=1, i",
        "sec-ch-ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": DEFAULT_USER_AGENT,
        "x-requested-with": "XMLHttpRequest",
    }
    if swimlane:
        headers["swimlane"] = swimlane
    return headers


def _snapshot_response(data: Dict[str, Any]) -> str:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / f"swat_product_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    return str(path)


def _open_browser_session(referer: str) -> request.OpenerDirector:
    jar = http.cookiejar.CookieJar()
    opener = request.build_opener(request.HTTPCookieProcessor(jar))
    bootstrap_req = request.Request(referer, headers=_build_browser_page_headers())
    with opener.open(bootstrap_req, timeout=30) as response:
        body = response.read().decode("utf-8", errors="replace")
    if "meta name=\"app-version\"" not in body:
        token_match = re.search(r"document\\.cookie\\s*=\\s*'yxd_token=([^']+)'", body)
        raise RuntimeError(
            "browser_bootstrap_failed"
            + (f": yxd_token={token_match.group(1)}" if token_match else "")
        )
    return opener


def _fetch_live_built_version(opener: request.OpenerDirector, referer: str, swimlane: Optional[str]) -> Dict[str, Any]:
    payload = parse.urlencode({"globalData": "false"}).encode("utf-8")
    req = request.Request(
        MENU_URL,
        data=payload,
        headers=_build_browser_ajax_headers(referer, swimlane),
        method="POST",
    )
    with opener.open(req, timeout=30) as response:
        raw = response.read().decode("utf-8", errors="replace")
    parsed = json.loads(raw)
    if parsed.get("code") != 1:
        return {
            "success": False,
            "reason": "swat_menu_error",
            "code": parsed.get("code"),
            "message": parsed.get("msg"),
        }
    return {
        "success": True,
        "builtVersion": parsed.get("built_ver"),
        "menu": parsed,
    }


def fetch_swat_product_data(
    cookie: Optional[str] = None,
    version: Optional[str] = None,
    swimlane: Optional[str] = None,
    timeout_seconds: int = 30,
    metric: str = "hourlyProfit",
) -> Dict[str, Any]:
    config = get_swat_product_config()
    cookie = cookie or config.get("cookie")
    version = version or config.get("version")
    swimlane = swimlane or config.get("swimlane")
    referer = DEFAULT_REFERER
    api_url = API_URL

    raw = None
    live_version = None
    try:
        opener = _open_browser_session(referer)
        menu_result = _fetch_live_built_version(opener, referer, swimlane)
        if not menu_result.get("success"):
            return menu_result
        live_version = menu_result.get("builtVersion")
        payload = parse.urlencode({"version": live_version}).encode("utf-8")
        req = request.Request(
            api_url,
            data=payload,
            headers=_build_browser_ajax_headers(referer, swimlane),
            method="POST",
        )
        with opener.open(req, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except Exception as browser_exc:
        if not cookie or not version:
            return {"success": False, "reason": "browser_session_failed", "error": str(browser_exc)}
        payload = parse.urlencode({"version": version}).encode("utf-8")
        req = request.Request(api_url, data=payload, headers=_build_headers(cookie, swimlane), method="POST")
        try:
            with request.urlopen(req, timeout=timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except Exception as exc:
            return {"success": False, "reason": "request_failed", "error": str(exc)}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {"success": False, "reason": "response_not_json", "error": str(exc), "raw": raw[:1000]}

    snapshot_path = _snapshot_response(parsed)
    code = parsed.get("code")
    message = parsed.get("msg")
    if code not in (None, 0, 1, 200, "0", "1", "200"):
        return {
            "success": False,
            "reason": "swat_api_error",
            "code": code,
            "message": message,
            "version": live_version or (parsed.get("data") or {}).get("version") if isinstance(parsed.get("data"), dict) else live_version,
            "products": [],
            "snapshotPath": snapshot_path,
        }

    products = ((parsed.get("data") or {}).get("cn") or [])
    if not products:
        return {
            "success": False,
            "reason": "swat_products_empty",
            "code": code,
            "message": message,
            "version": live_version or (parsed.get("data") or {}).get("version") if isinstance(parsed.get("data"), dict) else live_version,
            "products": [],
            "snapshotPath": snapshot_path,
        }

    return {
        "success": True,
        "code": code,
        "message": message,
        "version": live_version or (parsed.get("data") or {}).get("version"),
        "products": products,
        "snapshotPath": snapshot_path,
    }


def _build_item_lookup(mapping: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    lookup: Dict[str, Dict[str, str]] = {}
    for item in mapping.get("items", []):
        station = item.get("station")
        local_name = item.get("localItemName")
        for alias in item.get("remoteAliases", []):
            lookup[_normalize_name(alias)] = {"station": station, "localItemName": local_name}
    return lookup


def _infer_local_item_name(remote_name: str, mapped_item: Optional[Dict[str, str]]) -> str:
    if mapped_item and mapped_item.get("localItemName"):
        return mapped_item["localItemName"]
    return remote_name


def _build_search_names(remote_name: str, local_name: str) -> List[str]:
    names: List[str] = []
    for name in (remote_name, local_name):
        if name and name not in names:
            names.append(name)
    return names


def _flatten_product(product: Dict[str, Any], metric: str, place_to_station: Dict[str, str], item_lookup: Dict[str, Dict[str, str]]) -> Optional[Dict[str, Any]]:
    place = product.get("place")
    station = place_to_station.get(place)
    item_name = str(product.get("itemName") or "").strip()
    if not station or not item_name:
        return None
    mapped_item = item_lookup.get(_normalize_name(item_name))
    mapping_station = mapped_item.get("station") if mapped_item else None
    if mapping_station and mapping_station != station:
        return None

    forges = product.get("itemForge") or []
    if not forges:
        return None

    if metric == "hourlyProfit":
        best_forge = max(
            forges,
            key=lambda entry: float(entry.get("hourlyProfit") or 0),
        )
        metric_value = float(best_forge.get("hourlyProfit") or 0)
    else:
        # Total profit is an item-level value in the remote payload. When two
        # forge paths produce the same item, prefer the faster path.
        best_forge = min(
            forges,
            key=lambda entry: float(entry.get("productionTime") or 999999),
        )
        metric_value = float(product.get("profit") or 0)
    production_hours = float(best_forge.get("productionTime") or 0)

    local_name = _infer_local_item_name(item_name, mapped_item)
    search_names = _build_search_names(item_name, local_name)

    return {
        "station": station,
        "stationDisplayName": product.get("placeName"),
        "remoteItemName": item_name,
        "localItemName": local_name,
        "searchNames": search_names,
        "mappingSource": "mapping" if mapped_item else "remote_name",
        "metricValue": metric_value,
        "metric": metric,
        "requiredLevel": int(best_forge.get("requiredLevel") or 0),
        "productionHours": production_hours,
        "productionSeconds": int(production_hours * 3600),
        "hourlyProfit": float(best_forge.get("hourlyProfit") or 0),
        "profit": float(product.get("profit") or 0),
        "singlePrice": float(product.get("singlePrice") or 0),
        "totalMaterialValue": float(product.get("totalMaterialValue") or 0),
        "perCount": int(product.get("perCount") or 0),
        "itemId": product.get("itemID"),
        "pic": product.get("pic"),
    }


def plan_best_swat_products(
    cookie: Optional[str] = None,
    version: Optional[str] = None,
    swimlane: Optional[str] = None,
    metric: str = "hourlyProfit",
) -> Dict[str, Any]:
    if metric not in {"hourlyProfit", "profit"}:
        return {"success": False, "reason": "unsupported_metric", "metric": metric}

    fetched = fetch_swat_product_data(cookie=cookie, version=version, swimlane=swimlane, metric=metric)
    if not fetched.get("success"):
        fetched["action"] = "plan_best_swat_products"
        return fetched

    mapping = _load_mapping()
    place_to_station = mapping.get("placeToStation", {})
    item_lookup = _build_item_lookup(mapping)
    candidates: List[Dict[str, Any]] = []

    for product in fetched.get("products", []):
        flattened = _flatten_product(product, metric, place_to_station, item_lookup)
        if flattened:
            candidates.append(flattened)

    if not candidates:
        return {
            "success": False,
            "action": "plan_best_swat_products",
            "reason": "swat_product_candidates_empty",
            "metric": metric,
            "snapshotPath": fetched.get("snapshotPath"),
            "sourceVersion": fetched.get("version"),
            "selected": [],
            "stationItems": {},
            "stationItemCandidates": {},
            "candidates": [],
        }

    by_station: Dict[str, Dict[str, Any]] = {}
    for candidate in candidates:
        station = candidate["station"]
        current = by_station.get(station)
        if current is None or candidate["metricValue"] > current["metricValue"]:
            by_station[station] = candidate

    selected = [by_station[key] for key in sorted(by_station)]
    station_items = {item["station"]: item["remoteItemName"] for item in selected}
    station_item_candidates = {item["station"]: item["searchNames"] for item in selected}

    return {
        "success": True,
        "action": "plan_best_swat_products",
        "metric": metric,
        "snapshotPath": fetched.get("snapshotPath"),
        "sourceVersion": fetched.get("version"),
        "selected": selected,
        "stationItems": station_items,
        "stationItemCandidates": station_item_candidates,
        "candidates": sorted(candidates, key=lambda item: item["metricValue"], reverse=True),
    }
