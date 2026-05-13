#!/usr/bin/env python3
import argparse
import json
import sys
import time
from datetime import datetime

from scripts.config import load_config, set_api_key, set_gui_agent_config
from scripts.games import delta_force
from scripts.games import wegame_delta_force
from scripts.keyboard import hold_key, press_key
from scripts.recognition import find_all_buttons, find_button, list_available_buttons
from scripts.screenshot import take_desktop_screenshot, take_screenshot
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


def handle_set_market_quantity(args):
    print_json(delta_force.set_market_purchase_quantity(args.quantity, background=args.background))


def handle_buy_market_item(args):
    print_json(delta_force.buy_market_item_quantity(args.item_name, args.quantity, background=args.background))


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


def handle_key(args):
    activate_window(WINDOW_TITLE)
    ok = press_key(args.key)
    time.sleep(0.3)
    path = take_screenshot(WINDOW_TITLE)
    print_json(result("key", key=args.key, success=ok, screenshotPath=path))


def handle_hold(args):
    activate_window(WINDOW_TITLE)
    ok = hold_key(args.key, args.hold_ms)
    time.sleep(0.3)
    path = take_screenshot(WINDOW_TITLE)
    print_json(result("hold", key=args.key, holdMs=args.hold_ms, success=ok, screenshotPath=path))


def handle_windows(_args):
    print_json(result("windows", windows=list_windows()))


def handle_config(args):
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
            ),
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

    set_market_quantity_parser = subparsers.add_parser("set_market_quantity")
    set_market_quantity_parser.add_argument("quantity", type=int)
    set_market_quantity_parser.add_argument("--background", action="store_true")

    buy_market_item_parser = subparsers.add_parser("buy_market_item")
    buy_market_item_parser.add_argument("item_name")
    buy_market_item_parser.add_argument("quantity", type=int)
    buy_market_item_parser.add_argument("--background", action="store_true")

    redeem_department_item_parser = subparsers.add_parser("redeem_department_item")
    redeem_department_item_parser.add_argument("department_name")
    redeem_department_item_parser.add_argument("item_name")
    redeem_department_item_parser.add_argument("times", type=int)
    redeem_department_item_parser.add_argument("--background", action="store_true")

    collect_parser = subparsers.add_parser("collect")
    collect_parser.add_argument("--background", action="store_true")

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
    subparsers.add_parser("launch_status")
    subparsers.add_parser("launch_wegame")

    subparsers.add_parser("safe_for_automation")
    subparsers.add_parser("next_action")
    subparsers.add_parser("sync_overview_remaining_times")
    subparsers.add_parser("status")

    launch_direct_parser = subparsers.add_parser("launch_direct")
    launch_direct_parser.add_argument("--wait", type=int, default=60)

    refresh_qr_send_parser = subparsers.add_parser("refresh_qr_send")
    refresh_qr_send_parser.add_argument("--message", default="WeGame 二维码刷新后截图")
    refresh_qr_send_parser.add_argument("--project", default="delta-force-skill-minimal_deaac76e")
    refresh_qr_send_parser.add_argument("--x", type=int, default=2629)
    refresh_qr_send_parser.add_argument("--y", type=int, default=1430)
    refresh_qr_send_parser.add_argument("--settle-ms", type=int, default=900)

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
        "read_metric": handle_read_metric,
        "find_fill_confirm": handle_find_fill_confirm,
        "click_fill_confirm": handle_click_fill_confirm,
        "click_text": handle_click_text,
        "find_market_item": handle_find_market_item,
        "click_market_item": handle_click_market_item,
        "read_market_detail": handle_read_market_detail,
        "set_market_quantity": handle_set_market_quantity,
        "buy_market_item": handle_buy_market_item,
        "redeem_department_item": handle_redeem_department_item,
        "collect": handle_collect,
        "key": handle_key,
        "hold": handle_hold,
        "windows": handle_windows,
        "config": handle_config,
        "launch_status": handle_launch_status,
        "launch_wegame": handle_launch_wegame,
        "launch_direct": handle_launch_direct,
        "safe_for_automation": handle_safe_check,
        "next_action": handle_next_action,
        "sync_overview_remaining_times": handle_sync_overview_remaining_times,
        "status": handle_status,
        "refresh_qr_send": handle_refresh_qr_send,
    }
    handler = handlers.get(args.command)
    if not handler:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        sys.exit(1)
    handler(args)


if __name__ == "__main__":
    main()
