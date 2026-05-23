import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "logs" / "analytics.sqlite3"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS event_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            occurred_at TEXT NOT NULL,
            event_type TEXT NOT NULL,
            success INTEGER NOT NULL,
            game TEXT,
            station_name TEXT,
            department_name TEXT,
            item_name TEXT,
            quantity INTEGER,
            total_cost REAL,
            unit_expected_revenue REAL,
            expected_revenue REAL,
            expected_profit REAL,
            currency TEXT,
            metadata_json TEXT
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_event_log_occurred_at ON event_log(occurred_at)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_event_log_type ON event_log(event_type)"
    )
    return connection


def _insert_event(
    event_type: str,
    success: bool,
    game: Optional[str] = None,
    station_name: Optional[str] = None,
    department_name: Optional[str] = None,
    item_name: Optional[str] = None,
    quantity: Optional[int] = None,
    total_cost: Optional[float] = None,
    unit_expected_revenue: Optional[float] = None,
    expected_revenue: Optional[float] = None,
    expected_profit: Optional[float] = None,
    currency: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    occurred_at = datetime.now().isoformat(timespec="seconds")
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO event_log (
                occurred_at, event_type, success, game, station_name, department_name,
                item_name, quantity, total_cost, unit_expected_revenue, expected_revenue,
                expected_profit, currency, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                occurred_at,
                event_type,
                1 if success else 0,
                game,
                station_name,
                department_name,
                item_name,
                quantity,
                total_cost,
                unit_expected_revenue,
                expected_revenue,
                expected_profit,
                currency,
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )


def record_production(result: Dict[str, Any]) -> None:
    if not result.get("success") or result.get("dryRun") or result.get("skipped"):
        return
    report = result.get("productionReport") or {}
    evaluation = result.get("productionEvaluation") or {}
    _insert_event(
        event_type="produce",
        success=True,
        game=result.get("game"),
        station_name=result.get("station"),
        item_name=result.get("itemName"),
        quantity=report.get("outputQuantity"),
        total_cost=evaluation.get("estimatedCost"),
        unit_expected_revenue=evaluation.get("unitExpectedRevenue"),
        expected_revenue=evaluation.get("expectedRevenue"),
        expected_profit=evaluation.get("expectedProfit"),
        currency=evaluation.get("currency"),
        metadata={
            "action": result.get("action"),
            "nextCollectAt": report.get("nextCollectAt"),
            "durationSeconds": report.get("durationSeconds"),
            "materialsFilled": result.get("materialsFilled"),
        },
    )


def record_purchase(result: Dict[str, Any]) -> None:
    if not result.get("success"):
        return
    _insert_event(
        event_type="buy",
        success=True,
        game=result.get("game"),
        item_name=result.get("itemName"),
        quantity=result.get("completedQuantity") or result.get("targetQuantity"),
        total_cost=result.get("totalPrice"),
        metadata={
            "action": result.get("action"),
            "batchLimit": result.get("batchLimit"),
            "batches": result.get("batches", []),
        },
    )


def record_redemption(result: Dict[str, Any]) -> None:
    completed = int(result.get("completedTimes") or 0)
    if completed <= 0:
        return
    total_cost = result.get("totalCost")
    _insert_event(
        event_type="redeem",
        success=True,
        game=result.get("game"),
        department_name=result.get("departmentName"),
        item_name=result.get("itemName"),
        quantity=completed,
        total_cost=total_cost,
        metadata={
            "action": result.get("action"),
            "requestedTimes": result.get("requestedTimes"),
            "rounds": result.get("rounds", []),
        },
    )


def record_collection(result: Dict[str, Any]) -> None:
    collected = result.get("collected") or []
    for station_name in collected:
        _insert_event(
            event_type="collect",
            success=True,
            game=result.get("game"),
            station_name=station_name,
            quantity=1,
            metadata={"action": result.get("action")},
        )


def get_summary(limit: int = 20) -> Dict[str, Any]:
    with _connect() as connection:
        totals = connection.execute(
            """
            SELECT
                COUNT(*) AS total_events,
                COALESCE(SUM(CASE WHEN event_type = 'buy' THEN total_cost ELSE 0 END), 0) AS total_buy_cost,
                COALESCE(SUM(CASE WHEN event_type = 'produce' THEN total_cost ELSE 0 END), 0) AS total_production_cost,
                COALESCE(SUM(CASE WHEN event_type = 'produce' THEN expected_revenue ELSE 0 END), 0) AS total_expected_revenue,
                COALESCE(SUM(CASE WHEN event_type = 'produce' THEN expected_profit ELSE 0 END), 0) AS total_expected_profit
            FROM event_log
            """
        ).fetchone()

        by_type = connection.execute(
            """
            SELECT event_type, COUNT(*) AS count, COALESCE(SUM(quantity), 0) AS quantity
            FROM event_log
            GROUP BY event_type
            ORDER BY event_type
            """
        ).fetchall()

        recent_rows = connection.execute(
            """
            SELECT occurred_at, event_type, station_name, department_name, item_name,
                   quantity, total_cost, expected_revenue, expected_profit
            FROM event_log
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return {
        "databasePath": str(DB_PATH),
        "totals": dict(totals) if totals else {},
        "byType": [dict(row) for row in by_type],
        "recentEvents": [dict(row) for row in recent_rows],
    }


def get_dashboard_data(limit: int = 100) -> Dict[str, Any]:
    with _connect() as connection:
        totals = connection.execute(
            """
            SELECT
                COUNT(*) AS total_events,
                COALESCE(SUM(CASE WHEN event_type = 'buy' THEN total_cost ELSE 0 END), 0) AS total_buy_cost,
                COALESCE(SUM(CASE WHEN event_type = 'redeem' THEN total_cost ELSE 0 END), 0) AS total_redeem_cost,
                COALESCE(SUM(CASE WHEN event_type = 'produce' THEN total_cost ELSE 0 END), 0) AS total_production_cost,
                COALESCE(SUM(CASE WHEN event_type = 'produce' THEN expected_revenue ELSE 0 END), 0) AS total_expected_revenue,
                COALESCE(SUM(CASE WHEN event_type = 'produce' THEN expected_profit ELSE 0 END), 0) AS total_expected_profit
            FROM event_log
            """
        ).fetchone()

        by_type = connection.execute(
            """
            SELECT
                event_type,
                COUNT(*) AS count,
                COALESCE(SUM(quantity), 0) AS quantity,
                COALESCE(SUM(total_cost), 0) AS total_cost,
                COALESCE(SUM(expected_revenue), 0) AS expected_revenue,
                COALESCE(SUM(expected_profit), 0) AS expected_profit
            FROM event_log
            GROUP BY event_type
            ORDER BY event_type
            """
        ).fetchall()

        by_item = connection.execute(
            """
            SELECT
                event_type,
                COALESCE(item_name, station_name, department_name, '(unknown)') AS subject_name,
                COUNT(*) AS count,
                COALESCE(SUM(quantity), 0) AS quantity,
                COALESCE(SUM(total_cost), 0) AS total_cost,
                COALESCE(SUM(expected_revenue), 0) AS expected_revenue,
                COALESCE(SUM(expected_profit), 0) AS expected_profit
            FROM event_log
            GROUP BY event_type, subject_name
            ORDER BY count DESC, quantity DESC, subject_name ASC
            """
        ).fetchall()

        recent_rows = connection.execute(
            """
            SELECT
                occurred_at,
                event_type,
                success,
                station_name,
                department_name,
                item_name,
                quantity,
                total_cost,
                unit_expected_revenue,
                expected_revenue,
                expected_profit,
                currency,
                metadata_json
            FROM event_log
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    recent_events: List[Dict[str, Any]] = []
    for row in recent_rows:
        item = dict(row)
        metadata_json = item.get("metadata_json")
        try:
            item["metadata"] = json.loads(metadata_json) if metadata_json else {}
        except json.JSONDecodeError:
            item["metadata"] = {}
        item.pop("metadata_json", None)
        recent_events.append(item)

    return {
        "databasePath": str(DB_PATH),
        "totals": dict(totals) if totals else {},
        "byType": [dict(row) for row in by_type],
        "byItem": [dict(row) for row in by_item],
        "recentEvents": recent_events,
    }
