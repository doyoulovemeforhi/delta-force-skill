from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List


ROOT_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT_DIR / "logs"
DEFAULT_LOG_RETENTION_HOURS = 24


LOG_PATTERNS = (
    "scheduled_collect_produce_*.log",
    "watch_collect_produce_dynamic.*.log",
    "swat_product_snapshots/*.json",
    "agent_reports/*.txt",
)

PROTECTED_LOG_NAMES = {
    "analytics.sqlite3",
    "production_state.json",
}


def _candidate_files(patterns: Iterable[str]) -> List[Path]:
    files: List[Path] = []
    for pattern in patterns:
        files.extend(path for path in LOGS_DIR.glob(pattern) if path.is_file())
    return files


def cleanup_old_logs(retention_hours: int = DEFAULT_LOG_RETENTION_HOURS) -> Dict:
    cutoff = datetime.now() - timedelta(hours=retention_hours)
    deleted_files = []
    skipped_protected = []

    if not LOGS_DIR.exists():
        return {
            "success": True,
            "deletedFiles": [],
            "deletedCount": 0,
            "skippedProtected": [],
            "cutoff": cutoff.isoformat(timespec="seconds"),
        }

    for path in _candidate_files(LOG_PATTERNS):
        if path.name in PROTECTED_LOG_NAMES:
            skipped_protected.append(str(path))
            continue
        try:
            modified_at = datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            continue
        if modified_at >= cutoff:
            continue
        try:
            path.unlink()
            deleted_files.append(str(path))
        except OSError:
            continue

    deleted_dirs = []
    for path in sorted(LOGS_DIR.rglob("*"), reverse=True):
        if not path.is_dir() or path == LOGS_DIR:
            continue
        try:
            next(path.iterdir())
        except StopIteration:
            try:
                path.rmdir()
                deleted_dirs.append(str(path))
            except OSError:
                continue
        except OSError:
            continue

    return {
        "success": True,
        "retentionHours": retention_hours,
        "cutoff": cutoff.isoformat(timespec="seconds"),
        "deletedFiles": deleted_files,
        "deletedCount": len(deleted_files),
        "deletedDirs": deleted_dirs,
        "deletedDirCount": len(deleted_dirs),
        "skippedProtected": skipped_protected,
    }
