"""Scan History — Stores historical scan data for statistics and trends."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

HISTORY_FILE = Path("./data/scan_history.json")
MAX_HISTORY_DAYS = 30


@dataclass
class ScanRecord:
    """A single scan result for history tracking."""

    timestamp: str
    portal_name: str
    portal_url: str
    portal_type: str
    dates_found: int
    new_dates: int
    evening_slots: int
    error: str | None = None


@dataclass
class ScanHistory:
    """Collection of historical scan records."""

    records: list[ScanRecord] = field(default_factory=list)

    def add(self, record: ScanRecord) -> None:
        self.records.append(record)
        self._prune()

    def _prune(self) -> None:
        """Remove records older than MAX_HISTORY_DAYS."""
        cutoff = datetime.now().timestamp() - (MAX_HISTORY_DAYS * 86400)
        self.records = [
            r for r in self.records
            if datetime.fromisoformat(r.timestamp).timestamp() > cutoff
        ]

    def by_portal(self, portal_name: str) -> list[ScanRecord]:
        return [r for r in self.records if r.portal_name == portal_name]

    def by_day(self) -> dict[str, list[ScanRecord]]:
        """Group records by date (YYYY-MM-DD)."""
        groups: dict[str, list[ScanRecord]] = {}
        for r in self.records:
            day = r.timestamp[:10]
            groups.setdefault(day, []).append(r)
        return groups

    def daily_stats(self) -> list[dict]:
        """Aggregate stats per day for charts."""
        stats = []
        for day, records in sorted(self.by_day().items()):
            stats.append({
                "date": day,
                "scans": len(records),
                "total_dates": sum(r.dates_found for r in records),
                "new_dates": sum(r.new_dates for r in records),
                "evening_slots": sum(r.evening_slots for r in records),
                "errors": sum(1 for r in records if r.error),
                "portals_scanned": len({r.portal_name for r in records}),
            })
        return stats

    def portal_stats(self) -> list[dict]:
        """Stats per portal for heatmap/overview."""
        portals: dict[str, dict] = {}
        for r in self.records:
            if r.portal_name not in portals:
                portals[r.portal_name] = {
                    "portal": r.portal_name,
                    "url": r.portal_url,
                    "type": r.portal_type,
                    "total_scans": 0,
                    "total_dates": 0,
                    "total_new": 0,
                    "total_evening": 0,
                    "last_scan": r.timestamp,
                    "errors": 0,
                }
            p = portals[r.portal_name]
            p["total_scans"] += 1
            p["total_dates"] = max(p["total_dates"], r.dates_found)
            p["total_new"] += r.new_dates
            p["total_evening"] += r.evening_slots
            p["last_scan"] = max(p["last_scan"], r.timestamp)
            if r.error:
                p["errors"] += 1
        return sorted(portals.values(), key=lambda x: x["total_new"], reverse=True)


def load_history() -> ScanHistory:
    """Load scan history from disk."""
    if not HISTORY_FILE.exists():
        return ScanHistory()
    try:
        data = json.loads(HISTORY_FILE.read_text())
        records = [ScanRecord(**r) for r in data.get("records", [])]
        return ScanHistory(records=records)
    except Exception as e:
        logger.warning("History file corrupted, starting fresh: %s", e)
        return ScanHistory()


def save_history(history: ScanHistory) -> None:
    """Save scan history to disk."""
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {"records": [asdict(r) for r in history.records]}
    HISTORY_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


# ═══════════════════════════════════════════════════
# Audit log — append-only durable event log
# ═══════════════════════════════════════════════════

AUDIT_LOG_FILE = Path("./data/audit.log")


def audit_log(event_type: str, message: str, **extra: Any) -> None:
    """Append an audit event to the durable log file.

    Unlike the UI activity feed (ring buffer, 200 entries), the audit log
    is append-only and retains all events for debugging and compliance.
    """
    AUDIT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now().isoformat(),
        "event": event_type,
        "message": message,
        **extra,
    }
    try:
        with open(AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("Failed to write audit log: %s", e)
