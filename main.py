#!/usr/bin/env python3
import argparse
import json
import sys
import time
from datetime import datetime

from scripts.analytics_db import get_summary as get_analytics_summary
from scripts.analytics_server import serve as serve_analytics
from scripts.config import load_config, set_api_key, set_gui_agent_config, set_swat_product_config
from scripts.games import delta_force
from scripts.games import wegame_delta_force
from scripts.keyboard import hold_key, press_key
from scripts.maintenance import cleanup_old_logs
from scripts.recognition import find_all_buttons, find_button, list_available_buttons
from scripts.screenshot import take_desktop_screenshot, take_screenshot
from scripts.swat_product_strategy import plan_best_swat_products
from scripts.window import activate_window, get_window_info, list_windows


WINDOW_TITLE = delta_force.WINDOW_TITLE
GAME_ID = delta_force.GAME_ID


def result(action: str, **kwargs) -> dict:
    data = {
        "action": action,
        "game": GAME_ID,
        "windowTitle": WINDOW_TITLE,
        "timestamp": datetime.now().isoformat(),
    }
    data.update(kwargs)
    return data


def print_json(data: dict) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def handle_screenshot(_args):
    print_json(delta_force.screenshot())


def handle_desktop_screenshot(_args):
    path = take_desktop_screenshot()
    print_json(result("desktop_screenshot", screenshotPath=path))


def handle_find(args):
    path = take_screenshot(WINDOW_TITLE)
    from PIL import Image

    image = Image.open(path).convert("RGB")
    game_width = image.width
    button = find_button(image, GAME_ID, args.button_name, threshold=args.threshold, game_width=game_width)
    print_json(result("find", buttonName=args.button_name, found=button is not None, button=button, screenshotPath=path))


def handle_findall(_args):
    path = take_screenshot(WINDOW_TITLE)
    from PIL import Image

    image = Image.open(path).convert("RGB")
    game_width = image.width
    buttons = find_all_buttons(image, GAME_ID, game_width=game_width)
    print_json(result("findall", buttons=buttons, screenshotPath=path))


def handle_buttons(_args):
    print_json(result("buttons", buttons=list_available_buttons(GAME_ID)))


def handle_click_button(args):
    print_json(delta_force.click_button(args.button_name, threshold=args.threshold, background=args.background))


def handle_check_idle(_args):
    print_json(delta_force.check_idle_slot())


def handle_check_teqinchu_idle(_args):
    print_json(delta_force.check_teqinchu_idle_slot())


def handle_check_complete(args):
    print_json(delta_force.check_station_complete(args.station))


def handle_collect_station(args):
    print_json(delta_force.collect_station_if_complete(args.station, background=args.background))


def handle_collect_completed(args):
    print_json(delta_force.collect_completed_stations(background=args.background))


def handle_check_forced_offline(_args):
    print_json(delta_force.check_forced_offline())


def handle_forced_offline(args):
    print_json(delta_force.handle_forced_offline(background=args.background))


def handle_produce_762x51_example(args):
    print_json(
        delta_force.produce_762x51mm_m62(
            background=args.background,
            dry_run=args.dry_run,
            profit_guard=args.profit_guard,
        )
    )


def handle_produce_station_item(args):
    print_json(
        delta_force.produce_station_item(
            args.station,
            args.item_name,
            background=args.background,
            dry_run=args.dry_run,
            profit_guard=args.profit_guard,
        )
    )


def _parse_station_item_specs(specs: list[str]) -> dict:
    parsed = {}
    for spec in specs:
        if "=" not in spec:
            raise ValueError(f"Invalid station item spec: {spec!r}. Expected station=item")
        station, item_name = spec.split("=", 1)
        station = station.strip()
        item_name = item_name.strip()
        if not station or not item_name:
            raise ValueError(f"Invalid station item spec: {spec!r}. Expected station=item")
        parsed[station] = item_name
    return parsed


def handle_produce_station_items(args):
    try:
        item_specs = _parse_station_item_specs(args.specs)
    except ValueError as exc:
        print_json(result("produce_station_items", success=False, reason="invalid_specs", error=str(exc)))
        return

    print_json(
        delta_force.produce_station_items(
            item_specs,
            background=args.background,
            dry_run=args.dry_run,
            profit_guard=args.profit_guard,
        )
    )


def handle_evaluate_production(args):
    print_json(delta_force.evaluate_production_item(args.station, args.item_name))


def handle_plan_swat_products(args):
    print_json(
        plan_best_swat_products(
            cookie=args.cookie,
            version=args.version,
            swimlane=args.swimlane,
            metric=args.metric,
        )
    )


def handle_produce_swat_products(args):
    plan = plan_best_swat_products(
        cookie=args.cookie,
        version=args.version,
        swimlane=args.swimlane,
        metric=args.metric,
    )
    if not plan.get("success"):
        print_json(
            result(
                "produce_swat_products",
                metric=args.metric,
                plan=plan,
                execution=None,
                success=False,
                reason=plan.get("reason") or "swat_product_plan_failed",
            )
        )
        return
    if not plan.get("stationItemCandidates") and not plan.get("stationItems"):
        print_json(
            result(
                "produce_swat_products",
                metric=args.metric,
                plan=plan,
                execution=None,
                success=False,
                reason="swat_product_plan_empty",
            )
        )
        return
    economic_overrides = {
        item["station"]: {
            "unitExpectedRevenue": item.get("singlePrice"),
            "outputQuantity": item.get("perCount"),
            "expectedRevenue": (float(item.get("singlePrice") or 0) * int(item.get("perCount") or 1)),
            "durationSeconds": item.get("productionSeconds"),
            "source": "swat_product_api",
        }
        for item in plan.get("selected", [])
        if item.get("station")
    }
    execution = delta_force.produce_station_items(
        plan.get("stationItemCandidates") or plan.get("stationItems", {}),
        background=args.background,
        dry_run=args.dry_run,
        profit_guard=args.profit_guard,
        economic_overrides=economic_overrides,
    )
    print_json(
        result(
            "produce_swat_products",
            metric=args.metric,
            plan=plan,
            execution=execution,
            success=bool(plan.get("success") and execution.get("success")),
        )
    )


def handle_read_metric(args):
    print_json(delta_force.read_screen_metric(args.reader_name))


def handle_find_fill_confirm(_args):
    print_json(delta_force.find_fill_confirm_button())


def handle_click_fill_confirm(args):
    print_json(delta_force.click_fill_confirm(background=args.background))


def handle_click_text(args):
    print_json(delta_force.click_text(args.text, dry_run=args.dry_run))


def handle_find_market_item(args):
    print_json(delta_force.find_market_item_by_name(args.item_name))


def handle_click_market_item(args):
    print_json(delta_force.click_market_item_by_name(args.item_name, background=args.background))


def handle_read_market_detail(_args):
    print_json(delta_force.read_market_detail_state())


def handle_read_market_sale_detail(_args):
    print_json(delta_force.read_market_sale_detail_state())


def handle_read_market_sale_overview(_args):
    print_json(delta_force.read_market_sale_overview_state())


def handle_set_market_quantity(args):
    print_json(delta_force.set_market_purchase_quantity(args.quantity, background=args.background))


def handle_buy_market_item(args):
    print_json(delta_force.buy_market_item_quantity(args.item_name, args.quantity, background=args.background))


def handle_sell_market_item(args):
    print_json(delta_force.sell_market_item(args.item_name, background=args.background))


def handle_redeem_department_item(args):
    print_json(
        delta_force.redeem_department_item(
            args.department_name,
            args.item_name,
            times=args.times,
            background=args.background,
        )
    )


def handle_collect(args):
    print_json(delta_force.collect_completed_stations(background=args.background))


def handle_read_inventory_visible(_args):
    print_json(delta_force.read_inventory_visible())


def handle_scan_inventory_stash(args):
    print_json(delta_force.scan_inventory_stash(max_scrolls=args.max_scrolls, background=args.background))


def handle_scan_inventory_all_boxes(args):
    print_json(
        delta_force.scan_inventory_all_boxes(
            max_scrolls=args.max_scrolls,
            background=args.background,
            include_pages=args.include_pages,
        )
    )


def handle_analytics_summary(args):
    print_json(result("analytics_summary", **get_analytics_summary(limit=args.limit)))


def handle_analytics_server(args):
    print_json(result("analytics_server_starting", host=args.host, port=args.port))
    serve_analytics(host=args.host, port=args.port)


def handle_cleanup_artifacts(args):
    print_json(
        result(
            "cleanup_artifacts",
            logs=cleanup_old_logs(retention_hours=args.log_retention_hours),
        )
    )


def handle_key(args):
    activate_window(WINDOW_TITLE)
    ok = press_key(args.key)
    time.sleep(0.3)
    path = take_screenshot(WINDOW_TITLE)
    print_json(result("key", key=args.key, success=ok, screenshotPath=path))


def handle_enter_game_by_tab_prompt(_args):
    print_json(delta_force.enter_game_by_tab_prompt())


def handle_hold(args):
    activate_window(WINDOW_TITLE)
    ok = hold_key(args.key, args.hold_ms)
    time.sleep(0.3)
    path = take_screenshot(WINDOW_TITLE)
    print_json(result("hold", key=args.key, holdMs=args.hold_ms, success=ok, screenshotPath=path))


def handle_windows(_args):
    print_json(result("windows", windows=list_windows()))


def handle_config(args):
    if args.swat_cookie is not None or args.swat_version is not None or args.swat_swimlane is not None:
        set_swat_product_config(
            cookie=args.swat_cookie,
            version=args.swat_version,
            swimlane=args.swat_swimlane,
        )
        print_json(result("config", saved=True, section="swat_product"))
        return

    if args.gui_base_url or args.gui_model or args.gui_provider:
        set_gui_agent_config(
            base_url=args.gui_base_url,
            model=args.gui_model,
            provider=args.gui_provider,
        )
        print_json(result("config", saved=True, section="gui_agent"))
        return

    if args.set_api_key:
        set_api_key(args.set_api_key, provider=args.provider)
        print_json(result("config", saved=True, provider=args.provider))
        return
    config = load_config()
    if "gui_agent" in config and "api_key" in config["gui_agent"]:
        key = config["gui_agent"]["api_key"]
        config["gui_agent"]["api_key"] = f"{key[:6]}***{key[-4:]}" if len(key) > 10 else "***"
    print_json(result("config", config=config))


def handle_launch_status(_args):
    print_json(result("launch_status", **wegame_delta_force.status()))


def handle_launch_wegame(_args):
    print_json(result("launch_wegame", **wegame_delta_force.start_wegame()))


def handle_safe_check(_args):
    print_json(delta_force.check_game_safe_for_automation())


def handle_next_action(_args):
    print_json(delta_force.compute_next_action())


def handle_sync_overview_remaining_times(_args):
    print_json(delta_force.sync_overview_remaining_times())


def handle_status(_args):
    print_json(delta_force.get_status())


def handle_launch_direct(args):
    print_json(result("launch_direct", **wegame_delta_force.start_direct_client(wait_seconds=args.wait)))


def handle_launch_game_from_wegame(args):
    print_json(result("launch_game_from_wegame", **wegame_delta_force.launch_delta_from_wegame(wait_seconds=args.wait)))


def handle_launch_and_enter_game(args):
    launch = wegame_delta_force.launch_delta_from_wegame(wait_seconds=args.wait)
    enter = None
    if launch.get("success"):
        enter = delta_force.enter_game_by_tab_prompt()
    print_json(
        result(
            "launch_and_enter_game",
            success=bool(launch.get("success") and enter and enter.get("success")),
            launch=launch,
            enter=enter,
        )
    )


def handle_login_launch_and_enter_game(args):
    steps = []
    if get_window_info(WINDOW_TITLE):
        enter = delta_force.enter_game_by_tab_prompt()
        steps.append({"action": "enter_game_by_tab_prompt", **enter})
        print_json(
            result(
                "login_launch_and_enter_game",
                success=bool(enter.get("success")),
                loginChannel=args.login_channel,
                qrSent=False,
                loggedIn=None,
                launched=True,
                enteredLobby=bool(enter.get("success")),
                steps=steps,
            )
        )
        return

    logged_in = wegame_delta_force.wait_for_wegame_logged_in(wait_seconds=3)
    steps.append({"action": "check_wegame_logged_in", **logged_in})
    login = None
    if not logged_in.get("success"):
        login = wegame_delta_force.login_flow_ocr(
            message=args.message,
            project=args.project,
            wait_seconds=args.qr_wait,
            qr_refresh_seconds=args.qr_refresh_seconds,
            login_channel=args.login_channel,
        )
        steps.append({"action": "login_flow_ocr", **login})
        logged_in = wegame_delta_force.wait_for_wegame_logged_in(wait_seconds=args.scan_wait)
        steps.append({"action": "wait_for_wegame_logged_in", **logged_in})

    launch = None
    enter = None
    if logged_in.get("success"):
        launch = wegame_delta_force.launch_delta_from_wegame(wait_seconds=args.launch_wait)
        steps.append({"action": "launch_delta_from_wegame", **launch})
        if launch.get("success"):
            enter = delta_force.enter_game_by_tab_prompt()
            steps.append({"action": "enter_game_by_tab_prompt", **enter})

    print_json(
        result(
            "login_launch_and_enter_game",
            success=bool(logged_in.get("success") and launch and launch.get("success") and enter and enter.get("success")),
            loginChannel=args.login_channel,
            qrSent=bool(login and login.get("qrSent")),
            loggedIn=bool(logged_in.get("success")),
            launched=bool(launch and launch.get("success")),
            enteredLobby=bool(enter and enter.get("success")),
            steps=steps,
        )
    )


def handle_refresh_qr_send(args):
    print_json(
        result(
            "refresh_qr_send",
            **wegame_delta_force.refresh_qr_and_send(
                message=args.message,
                project=args.project,
                screen_x=args.x,
                screen_y=args.y,
                settle_ms=args.settle_ms,
                login_channel=args.login_channel,
            ),
        )
    )


def handle_login_flow_ocr(args):
    login_result = wegame_delta_force.login_flow_ocr(
        message=args.message,
        project=args.project,
        wait_seconds=args.wait,
        qr_refresh_seconds=args.qr_refresh_seconds,
        login_channel=args.login_channel,
    )
    login_result.pop("action", None)
    print_json(
        result(
            "login_flow_ocr",
            **login_result,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Delta Force minimal manufacturing skill")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("screenshot")
    subparsers.add_parser("desktop_screenshot")

    find_parser = subparsers.add_parser("find")
    find_parser.add_argument("button_name")
    find_parser.add_argument("--threshold", type=float, default=0.8)

    subparsers.add_parser("findall")
    subparsers.add_parser("buttons")

    click_button_parser = subparsers.add_parser("click_button")
    click_button_parser.add_argument("button_name")
    click_button_parser.add_argument("--threshold", type=float, default=0.8)
    click_button_parser.add_argument("--background", action="store_true")

    subparsers.add_parser("check_idle")
    subparsers.add_parser("check_teqinchu_idle")

    check_complete_parser = subparsers.add_parser("check_complete")
    check_complete_parser.add_argument("station")

    collect_station_parser = subparsers.add_parser("collect_station")
    collect_station_parser.add_argument("station")
    collect_station_parser.add_argument("--background", action="store_true")

    collect_completed_parser = subparsers.add_parser("collect_completed")
    collect_completed_parser.add_argument("--background", action="store_true")

    subparsers.add_parser("check_forced_offline")

    forced_offline_parser = subparsers.add_parser("handle_forced_offline")
    forced_offline_parser.add_argument("--background", action="store_true")

    produce_762_parser = subparsers.add_parser("produce_762x51_example")
    produce_762_parser.add_argument("--background", action="store_true")
    produce_762_parser.add_argument("--dry-run", action="store_true")
    produce_762_parser.add_argument("--profit-guard", action="store_true")
    produce_762_parser.add_argument("--allow-unprofitable", action="store_true", help=argparse.SUPPRESS)
    produce_762_m62_parser = subparsers.add_parser("produce_762x51mm_m62")
    produce_762_m62_parser.add_argument("--background", action="store_true")
    produce_762_m62_parser.add_argument("--dry-run", action="store_true")
    produce_762_m62_parser.add_argument("--profit-guard", action="store_true")
    produce_762_m62_parser.add_argument("--allow-unprofitable", action="store_true", help=argparse.SUPPRESS)

    produce_station_item_parser = subparsers.add_parser("produce_station_item")
    produce_station_item_parser.add_argument("station")
    produce_station_item_parser.add_argument("item_name")
    produce_station_item_parser.add_argument("--background", action="store_true")
    produce_station_item_parser.add_argument("--dry-run", action="store_true")
    produce_station_item_parser.add_argument("--profit-guard", action="store_true")
    produce_station_item_parser.add_argument("--allow-unprofitable", action="store_true", help=argparse.SUPPRESS)

    produce_station_items_parser = subparsers.add_parser("produce_station_items")
    produce_station_items_parser.add_argument("specs", nargs="+")
    produce_station_items_parser.add_argument("--background", action="store_true")
    produce_station_items_parser.add_argument("--dry-run", action="store_true")
    produce_station_items_parser.add_argument("--profit-guard", action="store_true")
    produce_station_items_parser.add_argument("--allow-unprofitable", action="store_true", help=argparse.SUPPRESS)

    evaluate_production_parser = subparsers.add_parser("evaluate_production")
    evaluate_production_parser.add_argument("station")
    evaluate_production_parser.add_argument("item_name")

    plan_swat_products_parser = subparsers.add_parser("plan_swat_products")
    plan_swat_products_parser.add_argument("--metric", default="hourlyProfit", choices=["hourlyProfit", "profit"])
    plan_swat_products_parser.add_argument("--cookie")
    plan_swat_products_parser.add_argument("--version")
    plan_swat_products_parser.add_argument("--swimlane")

    produce_swat_products_parser = subparsers.add_parser("produce_swat_products")
    produce_swat_products_parser.add_argument("--metric", default="hourlyProfit", choices=["hourlyProfit", "profit"])
    produce_swat_products_parser.add_argument("--cookie")
    produce_swat_products_parser.add_argument("--version")
    produce_swat_products_parser.add_argument("--swimlane")
    produce_swat_products_parser.add_argument("--background", action="store_true")
    produce_swat_products_parser.add_argument("--dry-run", action="store_true")
    produce_swat_products_parser.add_argument("--profit-guard", action="store_true")

    read_metric_parser = subparsers.add_parser("read_metric")
    read_metric_parser.add_argument("reader_name")

    subparsers.add_parser("find_fill_confirm")

    click_fill_confirm_parser = subparsers.add_parser("click_fill_confirm")
    click_fill_confirm_parser.add_argument("--background", action="store_true")

    click_text_parser = subparsers.add_parser("click_text")
    click_text_parser.add_argument("text")
    click_text_parser.add_argument("--dry-run", action="store_true")

    find_market_item_parser = subparsers.add_parser("find_market_item")
    find_market_item_parser.add_argument("item_name")

    click_market_item_parser = subparsers.add_parser("click_market_item")
    click_market_item_parser.add_argument("item_name")
    click_market_item_parser.add_argument("--background", action="store_true")

    subparsers.add_parser("read_market_detail")
    subparsers.add_parser("read_market_sale_detail")
    subparsers.add_parser("read_market_sale_overview")

    set_market_quantity_parser = subparsers.add_parser("set_market_quantity")
    set_market_quantity_parser.add_argument("quantity", type=int)
    set_market_quantity_parser.add_argument("--background", action="store_true")

    buy_market_item_parser = subparsers.add_parser("buy_market_item")
    buy_market_item_parser.add_argument("item_name")
    buy_market_item_parser.add_argument("quantity", type=int)
    buy_market_item_parser.add_argument("--background", action="store_true")

    sell_market_item_parser = subparsers.add_parser("sell_market_item")
    sell_market_item_parser.add_argument("item_name")
    sell_market_item_parser.add_argument("--background", action="store_true")

    redeem_department_item_parser = subparsers.add_parser("redeem_department_item")
    redeem_department_item_parser.add_argument("department_name")
    redeem_department_item_parser.add_argument("item_name")
    redeem_department_item_parser.add_argument("times", type=int)
    redeem_department_item_parser.add_argument("--background", action="store_true")

    collect_parser = subparsers.add_parser("collect")
    collect_parser.add_argument("--background", action="store_true")

    subparsers.add_parser("read_inventory_visible")

    scan_inventory_parser = subparsers.add_parser("scan_inventory_stash")
    scan_inventory_parser.add_argument("--max-scrolls", type=int, default=20)
    scan_inventory_parser.add_argument("--background", action="store_true")

    scan_inventory_all_parser = subparsers.add_parser("scan_inventory_all_boxes")
    scan_inventory_all_parser.add_argument("--max-scrolls", type=int, default=0)
    scan_inventory_all_parser.add_argument("--background", action="store_true")
    scan_inventory_all_parser.add_argument("--include-pages", action="store_true")

    analytics_summary_parser = subparsers.add_parser("analytics_summary")
    analytics_summary_parser.add_argument("--limit", type=int, default=20)

    analytics_server_parser = subparsers.add_parser("analytics_server")
    analytics_server_parser.add_argument("--host", default="127.0.0.1")
    analytics_server_parser.add_argument("--port", type=int, default=8765)

    cleanup_parser = subparsers.add_parser("cleanup_artifacts")
    cleanup_parser.add_argument("--log-retention-hours", type=int, default=24)

    key_parser = subparsers.add_parser("key")
    key_parser.add_argument("key")

    hold_parser = subparsers.add_parser("hold")
    hold_parser.add_argument("key")
    hold_parser.add_argument("hold_ms", type=int)

    subparsers.add_parser("windows")

    config_parser = subparsers.add_parser("config")
    config_parser.add_argument("--set-api-key")
    config_parser.add_argument("--provider", default="aliyun")
    config_parser.add_argument("--gui-base-url")
    config_parser.add_argument("--gui-model")
    config_parser.add_argument("--gui-provider")
    config_parser.add_argument("--swat-cookie")
    config_parser.add_argument("--swat-version")
    config_parser.add_argument("--swat-swimlane")
    subparsers.add_parser("launch_status")
    subparsers.add_parser("launch_wegame")

    subparsers.add_parser("safe_for_automation")
    subparsers.add_parser("next_action")
    subparsers.add_parser("sync_overview_remaining_times")
    subparsers.add_parser("status")
    subparsers.add_parser("enter_game_by_tab_prompt")

    launch_direct_parser = subparsers.add_parser("launch_direct")
    launch_direct_parser.add_argument("--wait", type=int, default=60)

    launch_game_parser = subparsers.add_parser("launch_game_from_wegame")
    launch_game_parser.add_argument("--wait", type=int, default=120)

    launch_enter_parser = subparsers.add_parser("launch_and_enter_game")
    launch_enter_parser.add_argument("--wait", type=int, default=120)

    login_launch_enter_parser = subparsers.add_parser("login_launch_and_enter_game")
    login_launch_enter_parser.add_argument("--message", default="WeGame 登录二维码")
    login_launch_enter_parser.add_argument("--project", default="delta-force-skill-minimal_deaac76e")
    login_launch_enter_parser.add_argument("--login-channel", choices=["qq", "wechat"], default="qq")
    login_launch_enter_parser.add_argument("--qr-wait", type=int, default=60)
    login_launch_enter_parser.add_argument("--scan-wait", type=int, default=180)
    login_launch_enter_parser.add_argument("--launch-wait", type=int, default=120)
    login_launch_enter_parser.add_argument("--qr-refresh-seconds", type=int, default=60)

    refresh_qr_send_parser = subparsers.add_parser("refresh_qr_send")
    refresh_qr_send_parser.add_argument("--message", default="WeGame 二维码刷新后截图")
    refresh_qr_send_parser.add_argument("--project", default="delta-force-skill-minimal_deaac76e")
    refresh_qr_send_parser.add_argument("--x", type=int, default=2629)
    refresh_qr_send_parser.add_argument("--y", type=int, default=1430)
    refresh_qr_send_parser.add_argument("--settle-ms", type=int, default=900)
    refresh_qr_send_parser.add_argument("--login-channel", choices=["qq", "wechat"], default="qq")

    login_flow_ocr_parser = subparsers.add_parser("login_flow_ocr")
    login_flow_ocr_parser.add_argument("--message", default="WeGame 登录二维码")
    login_flow_ocr_parser.add_argument("--project", default="delta-force-skill-minimal_deaac76e")
    login_flow_ocr_parser.add_argument("--wait", type=int, default=60)
    login_flow_ocr_parser.add_argument("--qr-refresh-seconds", type=int, default=60)
    login_flow_ocr_parser.add_argument("--login-channel", choices=["qq", "wechat"], default="qq")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    handlers = {
        "screenshot": handle_screenshot,
        "desktop_screenshot": handle_desktop_screenshot,
        "find": handle_find,
        "findall": handle_findall,
        "buttons": handle_buttons,
        "click_button": handle_click_button,
        "check_idle": handle_check_idle,
        "check_teqinchu_idle": handle_check_teqinchu_idle,
        "check_complete": handle_check_complete,
        "collect_station": handle_collect_station,
        "collect_completed": handle_collect_completed,
        "check_forced_offline": handle_check_forced_offline,
        "handle_forced_offline": handle_forced_offline,
        "produce_762x51_example": handle_produce_762x51_example,
        "produce_762x51mm_m62": handle_produce_762x51_example,
        "produce_station_item": handle_produce_station_item,
        "produce_station_items": handle_produce_station_items,
        "evaluate_production": handle_evaluate_production,
        "plan_swat_products": handle_plan_swat_products,
        "produce_swat_products": handle_produce_swat_products,
        "read_metric": handle_read_metric,
        "find_fill_confirm": handle_find_fill_confirm,
        "click_fill_confirm": handle_click_fill_confirm,
        "click_text": handle_click_text,
        "find_market_item": handle_find_market_item,
        "click_market_item": handle_click_market_item,
        "read_market_detail": handle_read_market_detail,
        "read_market_sale_detail": handle_read_market_sale_detail,
        "read_market_sale_overview": handle_read_market_sale_overview,
        "set_market_quantity": handle_set_market_quantity,
        "buy_market_item": handle_buy_market_item,
        "sell_market_item": handle_sell_market_item,
        "redeem_department_item": handle_redeem_department_item,
        "collect": handle_collect,
        "read_inventory_visible": handle_read_inventory_visible,
        "scan_inventory_stash": handle_scan_inventory_stash,
        "scan_inventory_all_boxes": handle_scan_inventory_all_boxes,
        "analytics_summary": handle_analytics_summary,
        "analytics_server": handle_analytics_server,
        "cleanup_artifacts": handle_cleanup_artifacts,
        "key": handle_key,
        "hold": handle_hold,
        "windows": handle_windows,
        "config": handle_config,
        "launch_status": handle_launch_status,
        "launch_wegame": handle_launch_wegame,
        "launch_direct": handle_launch_direct,
        "launch_game_from_wegame": handle_launch_game_from_wegame,
        "launch_and_enter_game": handle_launch_and_enter_game,
        "login_launch_and_enter_game": handle_login_launch_and_enter_game,
        "safe_for_automation": handle_safe_check,
        "next_action": handle_next_action,
        "sync_overview_remaining_times": handle_sync_overview_remaining_times,
        "status": handle_status,
        "enter_game_by_tab_prompt": handle_enter_game_by_tab_prompt,
        "refresh_qr_send": handle_refresh_qr_send,
        "login_flow_ocr": handle_login_flow_ocr,
    }
    handler = handlers.get(args.command)
    if not handler:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        sys.exit(1)
    handler(args)


if __name__ == "__main__":
    main()
