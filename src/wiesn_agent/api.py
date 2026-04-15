"""Wiesn-Agent Web API — FastAPI backend for the dashboard UI."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from wiesn_agent.config_model import WiesnConfig
from wiesn_agent.history import ScanRecord, audit_log, load_history, save_history
from wiesn_agent.scanner import (
    PortalSnapshot,
    compare_snapshots,
    deep_scan_date,
    load_snapshots,
    matches_wunsch,
    save_snapshots,
    scan_portal_availability,
)

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("config.yaml")
DATA_DIR = Path("./data")

# Resolve frontend build directory with fallbacks:
# 1. Relative to source tree (editable install / development)
# 2. /app/web/dist (Docker container)
# 3. Relative to cwd (manual setup)
_WEB_DIST_CANDIDATES = [
    Path(__file__).parent.parent.parent / "web" / "dist",  # editable install
    Path("/app/web/dist"),                                   # Docker
    Path("web/dist"),                                        # cwd-relative
]
WEB_DIST = next((p for p in _WEB_DIST_CANDIDATES if p.exists()), _WEB_DIST_CANDIDATES[0])
CHAT_LOG_FILE = DATA_DIR / "chat_history.json"
ACTIVITY_LOG_FILE = DATA_DIR / "activity_log.json"
ALERT_STATE_FILE = DATA_DIR / "alert_state.json"

# Track background scanner state
_scanner_task: asyncio.Task | None = None

# ── Scan persistence lock ─────────────────────────
# Prevents concurrent scans from overwriting each other's snapshots/history.
_scan_lock = asyncio.Lock()

# ── Activity log ──────────────────────────────────
# Ring buffer of recent activity events for the dashboard feed.
# NOTE: These are process-local globals. For multi-worker deployments,
# migrate to FastAPI app.state + a persistent backing store (SQLite/Redis).
_activity_log: deque[dict] = deque(maxlen=200)

# ── Chat log ──────────────────────────────────────
# Stores both user and agent messages for the chat panel.
_chat_log: deque[dict] = deque(maxlen=200)

# ── Monotonic event counters for SSE ──────────────
_chat_event_id: int = 0
_activity_event_id: int = 0

# ── Thinking status (broadcast to SSE clients) ───
_thinking_status: str = ""

# ── Slot alert queue (broadcast to web clients via SSE) ───
_slot_alerts: deque[dict] = deque(maxlen=50)
_slot_alert_id: int = 0

# ── Quiet-hours digest queue ─────────────────────
# Suppressed push notifications queued for delivery when quiet hours end.
_quiet_hours_queue: list[dict] = []


# ── Persistence helpers ───────────────────────────

def _save_chat_log() -> None:
    """Persist chat log to disk (excluding transient thinking entries)."""
    try:
        CHAT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        persistent = [m for m in _chat_log if m.get("role") != "thinking"]
        CHAT_LOG_FILE.write_text(
            json.dumps(persistent, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("Failed to save chat log: %s", e)


def _load_chat_log() -> None:
    """Restore chat log from disk on startup."""
    if not CHAT_LOG_FILE.exists():
        return
    try:
        data = json.loads(CHAT_LOG_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            _chat_log.extend(data[-200:])
            logger.info("Restored %d chat messages from disk", len(_chat_log))
    except Exception as e:
        logger.warning("Failed to load chat history: %s", e)


def _save_activity_log() -> None:
    """Persist activity log to disk."""
    try:
        ACTIVITY_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        ACTIVITY_LOG_FILE.write_text(
            json.dumps(list(_activity_log), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("Failed to save activity log: %s", e)


def _load_activity_log() -> None:
    """Restore activity log from disk on startup."""
    if not ACTIVITY_LOG_FILE.exists():
        return
    try:
        data = json.loads(ACTIVITY_LOG_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            _activity_log.extend(data[-200:])
            logger.info("Restored %d activity events from disk", len(_activity_log))
    except Exception as e:
        logger.warning("Failed to load activity log: %s", e)


def _log_activity(level: str, message: str, *args: Any, portal: str | None = None, **extra: Any) -> None:
    """Append an activity event and also log it normally."""
    global _activity_event_id
    formatted = message % args if args else message
    _activity_event_id += 1
    entry = {
        "event_id": _activity_event_id,
        "timestamp": datetime.now().isoformat(),
        "level": level,
        "message": formatted,
        "portal": portal,
        "role": "system",
        **extra,
    }
    _activity_log.append(entry)
    getattr(logger, level, logger.info)("[Scanner] %s", formatted)


def _push_slot_alert(portal: str, date: str, times: str, url: str) -> None:
    """Push a slot alert to the in-browser notification queue."""
    global _slot_alert_id
    _slot_alert_id += 1
    _slot_alerts.append({
        "alert_id": _slot_alert_id,
        "timestamp": datetime.now().isoformat(),
        "type": "slot_alert",
        "portal": portal,
        "date": date,
        "times": times,
        "url": url,
    })


def _chat_reply(message: str, **extra: Any) -> dict:
    """Add an agent reply to the chat log, persist, and return it."""
    global _chat_event_id
    _chat_event_id += 1
    entry = {
        "event_id": _chat_event_id,
        "timestamp": datetime.now().isoformat(),
        "role": "agent",
        "message": message,
        **extra,
    }
    _chat_log.append(entry)
    _save_chat_log()
    return entry


def _build_status_summary(snapshots: dict[str, PortalSnapshot]) -> str:
    """Build a deterministic status summary from persisted snapshots."""
    if not snapshots:
        return "Es liegen noch keine Scan-Daten vor. Starte einen Scan mit **scan all**."

    portal_names = sorted(snapshots.keys())
    with_dates = [name for name in portal_names if snapshots[name].datum_options]
    without_dates = [name for name in portal_names if not snapshots[name].datum_options]
    with_errors = [name for name in portal_names if snapshots[name].error]

    lines = [
        f"**{len(with_dates)} von {len(portal_names)} Zelten** haben aktuell Termine verfügbar: "
        f"{', '.join(with_dates)}."
    ]
    if without_dates:
        lines.append(
            f"**{len(without_dates)} Zelte** sind geschlossen oder haben keine Termine: "
            f"{', '.join(without_dates)}."
        )
    if with_errors:
        lines.append(
            f"Hinweis: Bei folgenden Zelten gab es zuletzt Scan-Fehler: {', '.join(with_errors)}."
        )
    return "\n\n".join(lines)


async def _scan_portals(portals: list, config: WiesnConfig) -> list[dict]:
    """Shared scan logic used by background scanner, chat scan, and API trigger.

    Returns a list of per-portal result dicts.
    Uses _scan_lock to prevent concurrent scans from corrupting snapshots.
    """
    from playwright.async_api import async_playwright

    async with _scan_lock:
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()

        snapshots = load_snapshots()
        history = load_history()
        results: list[dict] = []

        try:
            for portal in portals:
                try:
                    new_snap = await scan_portal_availability(page, portal, timeout=config.browser.timeout)
                    old_snap = snapshots.get(portal.name)
                    change = compare_snapshots(old_snap, new_snap)

                    # Deep-scan: check time slots for dates matching wunsch_tage
                    # Use matches_wunsch() which handles both DD.MM.YYYY and ISO formats
                    matching_dates = [
                        d for d in new_snap.datum_options
                        if matches_wunsch(d.get("text", d.get("value", "")), config)
                    ]
                    deep_results = []
                    evening_count = 0

                    if matching_dates:
                        _log_activity(
                            "info",
                            "%s: %d dates match wunsch_tage, starting deep-scan (type=%s)",
                            portal.name, len(matching_dates), new_snap.portal_type,
                            portal=portal.name,
                        )
                    if matching_dates and new_snap.portal_type not in ("no-selects", "error"):
                        for datum in matching_dates:
                            try:
                                ds = await deep_scan_date(
                                    page, portal,
                                    datum["value"], datum.get("text", datum["value"]),
                                    config.reservierung.slots,
                                    timeout=config.browser.timeout,
                                )
                                deep_results.append({
                                    "datum_value": ds.datum_value,
                                    "datum_text": ds.datum_text,
                                    "uhrzeiten": ds.uhrzeiten,
                                    "matching_slots": ds.matching_slots,
                                })
                                if ds.has_abend:
                                    evening_count += 1
                                    _log_activity(
                                        "info", "%s %s: evening slots found!",
                                        portal.name, datum["value"],
                                        portal=portal.name, event="evening_match",
                                    )
                            except Exception as e:
                                logger.warning(
                                    "Deep-scan failed for %s/%s: %s",
                                    portal.name, datum.get("value"), e,
                                )

                        # Navigate back to portal for clean state for next portal
                        try:
                            await page.goto(portal.url, timeout=config.browser.timeout)
                            await page.wait_for_timeout(2000)
                        except Exception:
                            pass

                    new_snap.deep_scan = deep_results
                    snapshots[portal.name] = new_snap

                    history.add(ScanRecord(
                        timestamp=new_snap.timestamp,
                        portal_name=portal.name,
                        portal_url=portal.url,
                        portal_type=new_snap.portal_type,
                        dates_found=len(new_snap.datum_options),
                        new_dates=len(change.new_dates),
                        evening_slots=evening_count,
                        error=new_snap.error,
                    ))

                    results.append({
                        "portal": portal.name,
                        "dates_found": len(new_snap.datum_options),
                        "new_dates": len(change.new_dates),
                        "portal_type": new_snap.portal_type,
                        "error": new_snap.error,
                        "summary": change.summary(),
                    })

                    if change.new_dates:
                        _log_activity(
                            "info", "%s: %d NEW dates found!",
                            portal.name, len(change.new_dates),
                            portal=portal.name, event="new_dates",
                        )
                except Exception as e:
                    logger.warning("Error scanning %s: %s", portal.name, e)
                    # BE-5: include error in results instead of silently dropping
                    results.append({
                        "portal": portal.name,
                        "dates_found": 0,
                        "new_dates": 0,
                        "portal_type": "error",
                        "error": str(e)[:200],
                        "summary": f"{portal.name}: scan error — {e}",
                    })

            save_snapshots(snapshots)
            save_history(history)
        finally:
            await browser.close()
            await pw.stop()

        return results


# Track already-notified evening slots to avoid repeated push notifications.
# Key: "portal_name|datum_text|time_text"
_notified_evening_slots: set[str] = set()


def _save_alert_state() -> None:
    """Persist dedupe set, recent alerts, and quiet-hours queue to disk."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        state = {
            "notified_slots": list(_notified_evening_slots),
            "alerts": list(_slot_alerts),
            "alert_id": _slot_alert_id,
            "quiet_hours_queue": _quiet_hours_queue,
        }
        ALERT_STATE_FILE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        logger.warning("Failed to save alert state: %s", e)


def _load_alert_state() -> None:
    """Restore dedupe set, recent alerts, and quiet-hours queue from disk on startup."""
    global _slot_alert_id
    if not ALERT_STATE_FILE.exists():
        return
    try:
        data = json.loads(ALERT_STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(data.get("notified_slots"), list):
            _notified_evening_slots.update(data["notified_slots"])
            logger.info("Restored %d notified slot keys from disk", len(_notified_evening_slots))
        if isinstance(data.get("alerts"), list):
            for a in data["alerts"][-50:]:
                _slot_alerts.append(a)
            logger.info("Restored %d slot alerts from disk", len(_slot_alerts))
        if isinstance(data.get("alert_id"), int):
            _slot_alert_id = max(_slot_alert_id, data["alert_id"])
        if isinstance(data.get("quiet_hours_queue"), list):
            _quiet_hours_queue.extend(data["quiet_hours_queue"])
            if _quiet_hours_queue:
                logger.info("Restored %d queued quiet-hours alerts", len(_quiet_hours_queue))
    except Exception as e:
        logger.warning("Failed to load alert state: %s", e)


async def _notify_new_evening_slots(results: list[dict], config: WiesnConfig) -> None:
    """Detect new evening slots and notify via push + web alerts.

    Web alerts (toasts/activity log) are ALWAYS sent regardless of quiet hours.
    Push notifications (ntfy/Apprise/BotBell) respect quiet hours.
    """
    import json as _json

    from wiesn_agent.tools.notify_tools import send_notification, should_notify_now

    push_allowed = should_notify_now(config.notifications)

    snapshots = load_snapshots()
    for r in results:
        portal_name = r["portal"]
        if not r.get("error"):
            snap = snapshots.get(portal_name)
            if snap and snap.deep_scan:
                for ds in snap.deep_scan:
                    if ds.get("matching_slots", {}).get("abends"):
                        abend_list = ds["matching_slots"]["abends"]
                        datum_text = ds.get("datum_text", ds.get("datum_value", ""))

                        # Filter to only truly new slots (not yet seen)
                        new_slots = []
                        for s in abend_list:
                            slot_key = f"{portal_name}|{datum_text}|{s.get('text', s.get('value', ''))}"
                            if slot_key not in _notified_evening_slots:
                                _notified_evening_slots.add(slot_key)
                                new_slots.append(s)

                        if not new_slots:
                            continue

                        times = ", ".join(s.get("text", s.get("value", "")) for s in new_slots[:5])
                        booking_url = snap.portal_url if snap else ""

                        # ALWAYS push to web alert queue (independent of quiet hours)
                        datum_text_val = ds.get("datum_text", ds.get("datum_value", ""))
                        _push_slot_alert(portal_name, datum_text_val, times, booking_url)

                        # Push notification only if outside quiet hours (with retry)
                        push_status = "skipped_quiet_hours"
                        if push_allowed:
                            title = f"Evening slots: {portal_name}"
                            message = (
                                f"{portal_name}\n"
                                f"📅 {datum_text_val}\n"
                                f"🌙 {times}\n"
                                f"\n→ Book now: {booking_url}"
                            )
                            # Retry up to 2 times on failure
                            for attempt in range(3):
                                result_json = await send_notification(
                                    title=title,
                                    message=message,
                                    config=config.notifications,
                                    notify_type="success",
                                    event_type="evening_slot",
                                )
                                try:
                                    result_data = _json.loads(result_json)
                                    push_status = result_data.get("status", "unknown")
                                except (ValueError, TypeError):
                                    push_status = "error"
                                if push_status in ("sent", "partial"):
                                    break
                                if attempt < 2:
                                    logger.warning(
                                        "Push notification failed (attempt %d/3) for %s, retrying...",
                                        attempt + 1, portal_name,
                                    )
                                    await asyncio.sleep(2 ** attempt)
                        else:
                            # Queue for digest delivery when quiet hours end
                            _quiet_hours_queue.append({
                                "portal": portal_name,
                                "date": datum_text_val,
                                "times": times,
                                "url": booking_url,
                                "queued_at": datetime.now().isoformat(),
                            })
                            push_status = "queued_quiet_hours"

                        # Log truthfully
                        _log_activity(
                            "info",
                            "Evening slots found: %s on %s (push: %s)",
                            portal_name, datum_text_val, push_status,
                            portal=portal_name, event="slot_alert",
                        )
                        audit_log("slot_alert", f"{portal_name}: evening slots ({push_status})",
                                  portal=portal_name, datum=datum_text_val,
                                  push_status=push_status)

    # Persist alert state after processing
    _save_alert_state()


async def _flush_quiet_hours_digest(config: WiesnConfig) -> None:
    """Send a digest of queued alerts when quiet hours have ended."""
    from wiesn_agent.tools.notify_tools import send_notification, should_notify_now

    if not _quiet_hours_queue or not should_notify_now(config.notifications):
        return

    queued = list(_quiet_hours_queue)
    _quiet_hours_queue.clear()

    # Build digest message
    lines = []
    for item in queued:
        lines.append(f"🍺 {item['portal']} — 📅 {item['date']} · 🌙 {item['times']}")

    title = f"🌅 {len(queued)} evening slot{'s' if len(queued) != 1 else ''} found overnight"
    message = "\n".join(lines)
    if queued[0].get("url"):
        message += f"\n\n→ Book: {queued[0]['url']}"

    await send_notification(
        title=title,
        message=message,
        config=config.notifications,
        notify_type="success",
        event_type="evening_slot",
    )
    _log_activity(
        "info", "Quiet-hours digest sent: %d queued alerts delivered",
        len(queued), event="digest_sent",
    )
    _save_alert_state()


async def _background_scanner() -> None:
    """Periodically scan all enabled portals in the background."""
    # Wait a few seconds before first scan so the server is fully up
    await asyncio.sleep(5)

    while True:
        config = _load_config()
        interval = config.monitoring.check_interval_minutes * 60
        portals = config.enabled_portale()

        if not portals:
            _log_activity("info", "No enabled portals, sleeping %d min", config.monitoring.check_interval_minutes)
            await asyncio.sleep(interval)
            continue

        _log_activity("info", "Starting background scan of %d portals...", len(portals))
        try:
            # Flush any queued quiet-hours alerts if quiet hours have ended
            await _flush_quiet_hours_digest(config)

            results = await _scan_portals(portals, config)
            new_count = sum(r["new_dates"] for r in results)
            _log_activity(
                "info", "Scan complete: %d portals, %d new dates. Next scan in %d min.",
                len(portals), new_count, config.monitoring.check_interval_minutes,
            )
            audit_log("scan_complete", f"{len(portals)} portals, {new_count} new dates",
                      portals=len(portals), new_dates=new_count)

            # Send notifications for portals with new evening slots
            await _notify_new_evening_slots(results, config)
        except Exception as e:
            _log_activity("error", "Background scan failed: %s", e)
            audit_log("scan_error", str(e))

        # Persist activity log after each scan cycle
        _save_activity_log()

        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background scanner on startup, cancel on shutdown."""
    global _scanner_task

    # Restore persisted state
    _load_chat_log()
    _load_activity_log()
    _load_alert_state()

    _scanner_task = asyncio.create_task(_background_scanner())
    logger.info("[Scanner] Background scanner started")
    yield
    _scanner_task.cancel()
    try:
        await _scanner_task
    except asyncio.CancelledError:
        pass
    logger.info("[Scanner] Background scanner stopped")

    # Persist state before shutdown
    _save_chat_log()
    _save_activity_log()

    # Shut down MCP chat agent if running
    try:
        from wiesn_agent.chat_agent import shutdown as _chat_shutdown
        await _chat_shutdown()
    except Exception:
        pass


app = FastAPI(title="Wiesn-Agent", version="0.1.0", lifespan=lifespan)

_CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS", "http://localhost:5173,http://localhost:5001"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _CORS_ORIGINS],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)


# ── Simple bearer token auth (optional) ──────────
# Set WIESN_API_TOKEN in .env to require auth on all /api/ endpoints.
# When not set, the API is open (localhost-only use).

_API_TOKEN = os.getenv("WIESN_API_TOKEN", "")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Optional bearer token auth for API endpoints."""
    if _API_TOKEN and request.url.path.startswith("/api/"):
        # Allow health check without auth
        if request.url.path == "/api/health":
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != _API_TOKEN:
            from starlette.responses import JSONResponse
            return JSONResponse(
                {"error": "Unauthorized. Set Authorization: Bearer <token>"},
                status_code=401,
            )
    return await call_next(request)


# ═══════════════════════════════════════════════════
# Health
# ═══════════════════════════════════════════════════


@app.get("/api/health")
async def health():
    """Health check endpoint for Docker and monitoring."""
    return {"status": "ok"}


# ═══════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════


def _load_config() -> WiesnConfig:
    if CONFIG_PATH.exists():
        return WiesnConfig.from_yaml(CONFIG_PATH)
    return WiesnConfig.from_yaml(Path("config.example.yaml"))


def _snapshot_to_dict(snap: PortalSnapshot) -> dict:
    return {
        "portal_name": snap.portal_name,
        "portal_url": snap.portal_url,
        "timestamp": snap.timestamp,
        "datum_options": snap.datum_options,
        "portal_type": snap.portal_type,
        "error": snap.error,
        "deep_scan": getattr(snap, "deep_scan", []),
    }


# ═══════════════════════════════════════════════════
# API — Chat & Activity Feed
# ═══════════════════════════════════════════════════


@app.get("/api/activity")
async def get_activity():
    """Return recent activity log entries."""
    return {"events": list(_activity_log)}


@app.get("/api/chat")
async def get_chat():
    """Return full chat history (user + agent + system messages)."""
    return {"messages": list(_chat_log)}


class ChatMessage(BaseModel):
    message: str


# ── Intent recognition ────────────────────────────
# Each intent has keyword/phrase lists for both English and German.
# Phrases are checked first (multi-word), then single keywords.

_INTENT_PHRASES: dict[str, list[str]] = {
    "help": [
        "was kann ich", "was kannst du", "what can i", "what can you",
        "wie funktioniert", "how does this work", "how do i", "wie geht",
        "show me commands", "zeig mir befehle", "was geht", "kannst du mir helfen",
        "can you help", "show commands", "zeig befehle",
    ],
    "scan": [
        "scan all", "alle scannen", "alle prüfen", "check all", "start scan",
        "starte scan", "nochmal scannen", "scan starten", "los scannen",
        "fang an zu suchen", "start searching", "überprüfe alle",
    ],
    "status": [
        "wie ist der stand", "was ist der stand", "give me a summary",
        "wie sieht es aus", "wie siehts aus", "wie schaut es aus",
        "show overview", "zeig übersicht", "gib mir eine übersicht",
        "what's the status", "whats the status", "how are things",
        "wie viele zelte", "how many tents", "welche zelte haben termine",
        "which tents have dates", "offene termine", "open dates",
        "meisten termine", "most dates", "most reservations",
    ],
    "matches": [
        "was hast du gefunden", "what did you find", "show matches",
        "zeig treffer", "zeig ergebnisse", "show results", "gibt es treffer",
        "any matches", "any results", "abend slots", "evening slots",
        "passende termine", "matching dates", "freie plätze",
    ],
    "portals": [
        "welche zelte", "which tents", "show portals", "zeig portale",
        "alle zelte", "all tents", "liste der zelte", "list of tents",
        "portal liste", "portal list", "welche portale",
    ],
}

_INTENT_KEYWORDS: dict[str, list[str]] = {
    "help": ["help", "hilfe", "?"],
    "scan": ["scan", "prüf", "überprüf", "scann"],
    "status": ["status", "summary", "übersicht", "stand", "overview"],
    "matches": [
        "match", "treffer", "ergebnis", "result", "abend", "evening",
        "gefunden", "found",
    ],
    "portals": ["portal", "portale", "tent", "tents", "zelt", "zelte"],
}


_MONTH_NAMES = {
    "januar": "01", "februar": "02", "märz": "03", "april": "04",
    "mai": "05", "juni": "06", "juli": "07", "august": "08",
    "september": "09", "oktober": "10", "november": "11", "dezember": "12",
}


def _extract_date(text: str) -> str:
    """Extract a date from user text. Returns YYYY-MM-DD or DD.MM.YYYY or empty string."""
    # Match DD.MM or DD.MM.YYYY
    m = re.search(r'(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?', text)
    if m:
        day = int(m.group(1))
        month = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else 2026
        return f"{year}-{month:02d}-{day:02d}"

    # Match "DD. Monat" or "DD Monat"
    m = re.search(r'(\d{1,2})\.?\s+(januar|februar|märz|april|mai|juni|juli|august|september|oktober|november|dezember)', text.lower())
    if m:
        day = int(m.group(1))
        month = int(_MONTH_NAMES[m.group(2)])
        return f"2026-{month:02d}-{day:02d}"

    return ""


def _date_matches(iso_date: str, text: str) -> bool:
    """Check if an ISO date (YYYY-MM-DD) matches a date in text (various formats)."""
    try:
        from datetime import datetime as dt
        parsed = dt.strptime(iso_date, "%Y-%m-%d")
        # DD.MM.YYYY format
        if parsed.strftime("%d.%m.%Y") in text:
            return True
        # German month name
        months_de = ["Januar", "Februar", "März", "April", "Mai", "Juni",
                     "Juli", "August", "September", "Oktober", "November", "Dezember"]
        german = f"{parsed.day}. {months_de[parsed.month - 1]}"
        if german in text:
            return True
    except (ValueError, IndexError):
        pass
    return False


def _find_portal(text: str, config) -> str | None:
    """Find a portal name mentioned in text, with partial matching."""
    lower = text.lower()
    # Exact match first
    for portal in config.portale:
        if portal.name.lower() in lower:
            return portal.name
    # Partial match: split portal name on spaces/hyphens and check core parts
    for portal in config.portale:
        parts = re.split(r'[\s\-]+', portal.name.lower())
        # Match if any distinctive part (>3 chars, not generic) appears
        generic = {"fest", "zelt", "festzelt", "wiesn"}
        for part in parts:
            if len(part) > 3 and part not in generic and part in lower:
                return portal.name
    return None


_WEEKDAY_NAMES_DE = {
    0: "Montag", 1: "Dienstag", 2: "Mittwoch", 3: "Donnerstag",
    4: "Freitag", 5: "Samstag", 6: "Sonntag",
}

_WEEKDAY_KEYWORDS: dict[str, int] = {
    "montag": 0, "monday": 0, "mo": 0,
    "dienstag": 1, "tuesday": 1, "di": 1,
    "mittwoch": 2, "wednesday": 2, "mi": 2,
    "donnerstag": 3, "thursday": 3, "do": 3,
    "freitag": 4, "friday": 4, "fr": 4,
    "samstag": 5, "saturday": 5, "sa": 5,
    "sonntag": 6, "sunday": 6, "so": 6,
    "wochenende": -1,  # special: Sat + Sun
    "weekend": -1,
}


def _extract_weekday(text: str) -> int | None:
    """Extract a weekday from user text. Returns 0-6 (Mon-Sun), -1 for weekend, or None."""
    lower = text.lower()
    # Long keywords first (safe substring match)
    long_keywords = {
        "montag": 0, "monday": 0,
        "dienstag": 1, "tuesday": 1,
        "mittwoch": 2, "wednesday": 2,
        "donnerstag": 3, "thursday": 3,
        "freitag": 4, "friday": 4,
        "samstag": 5, "saturday": 5,
        "sonntag": 6, "sunday": 6,
        "wochenende": -1, "weekend": -1,
    }
    for keyword, day in long_keywords.items():
        if keyword in lower:
            return day
    # Short abbreviations only as whole words (avoid "meisten" → "di")
    words = set(re.split(r"[\s,;:.!?]+", lower))
    short_keywords = {"mo": 0, "di": 1, "mi": 2, "do": 3, "fr": 4, "sa": 5, "so": 6}
    for keyword, day in short_keywords.items():
        if keyword in words:
            return day
    return None


def _dates_on_weekday(datum_options: list[dict], weekday: int) -> list[str]:
    """Filter dates that fall on a specific weekday (or weekend if weekday=-1)."""
    from datetime import datetime as dt

    matching = []
    for d in datum_options:
        val = d.get("value", d.get("text", ""))
        text = d.get("text", d.get("value", ""))
        # Try to parse the date
        parsed = None
        # DD.MM.YYYY
        m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", val)
        if m:
            try:
                parsed = dt(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                pass
        # "Montag, 21. September 2026" style
        if not parsed:
            m = re.search(r"(\d{1,2})\.\s*(januar|februar|märz|april|mai|juni|juli|august|september|oktober|november|dezember)\s*(\d{4})", text.lower())
            if m:
                try:
                    month_num = int(_MONTH_NAMES.get(m.group(2), "0"))
                    parsed = dt(int(m.group(3)), month_num, int(m.group(1)))
                except (ValueError, KeyError):
                    pass

        if parsed:
            if weekday == -1:  # weekend
                if parsed.weekday() in (5, 6):
                    matching.append(text)
            elif parsed.weekday() == weekday:
                matching.append(text)

    return matching


def _classify_intent(text: str) -> str:
    """Classify user message into an intent. Returns intent name or 'unknown'."""
    lower = text.lower().strip()

    # Bare "?" is always help
    if lower in ("?", "??", "???"):
        return "help"

    # Question heuristic — check before stripping so the trailing "?" is still visible
    trailing_question = lower.endswith("?")

    # Strip punctuation for matching
    clean = re.sub(r"[?.!,;:]+", " ", lower).strip()

    # 1. Phrase matching (highest priority — multi-word patterns)
    for intent, phrases in _INTENT_PHRASES.items():
        for phrase in phrases:
            if phrase in clean:
                return intent

    # 2. Keyword matching (whole words only to avoid false positives)
    words = set(clean.split())
    for intent, keywords in _INTENT_KEYWORDS.items():
        for kw in keywords:
            if kw in words:
                return intent

    # 3. Question heuristics — if ending with "?" and no other match, show help
    if trailing_question:
        return "help"

    return "unknown"


@app.post("/api/chat")
async def post_chat(body: ChatMessage):
    """Handle a user chat message — LLM agent with keyword fallback."""
    global _thinking_status, _chat_event_id
    text = body.message.strip()
    if not text:
        raise HTTPException(400, "Empty message")

    # Store user message
    _chat_event_id += 1
    user_entry = {
        "event_id": _chat_event_id,
        "timestamp": datetime.now().isoformat(),
        "role": "user",
        "message": text,
    }
    _chat_log.append(user_entry)
    _save_chat_log()

    intent = _classify_intent(text)

    # Status answers are deterministic and history-independent by design.
    if intent == "status":
        snapshots = load_snapshots()
        reply = _chat_reply(_build_status_summary(snapshots))
        return {"user": user_entry, "reply": reply}

    # ── Deterministic date-specific answers ───────
    # Intercept date questions BEFORE the LLM to avoid session-drift
    # and ensure accurate weekday/date matching.
    config = _load_config()
    snapshots = load_snapshots()
    mentioned_date = _extract_date(text)
    mentioned_portal = _find_portal(text, config)
    weekday_query = _extract_weekday(text)

    # Weekday question (e.g. "hat Kufflers am Samstag Termine?")
    # Only when NO specific date is mentioned — date takes precedence
    if weekday_query is not None and not mentioned_date and mentioned_portal:
        snap = snapshots.get(mentioned_portal)
        if snap and snap.datum_options:
            matching = _dates_on_weekday(snap.datum_options, weekday_query)
            if matching:
                dates_str = ", ".join(matching[:5])
                reply = _chat_reply(
                    f"**{mentioned_portal}** hat **{len(matching)}** "
                    f"Termin(e) an einem {_WEEKDAY_NAMES_DE[weekday_query]}: {dates_str}."
                )
            else:
                reply = _chat_reply(
                    f"**{mentioned_portal}** hat aktuell **keine** Termine "
                    f"an einem {_WEEKDAY_NAMES_DE[weekday_query]}."
                )
        elif snap:
            reply = _chat_reply(f"**{mentioned_portal}** hat aktuell **keine** verfügbaren Termine.")
        else:
            reply = _chat_reply(f"**{mentioned_portal}** wurde noch nicht gescannt.")
        return {"user": user_entry, "reply": reply}

    # Weekday question without specific portal
    if weekday_query is not None and not mentioned_portal and not mentioned_date:
        with_dates = []
        for name, snap in snapshots.items():
            if snap.datum_options:
                matching = _dates_on_weekday(snap.datum_options, weekday_query)
                if matching:
                    with_dates.append(f"**{name}**: {', '.join(matching[:3])}")
        if with_dates:
            reply = _chat_reply(
                f"Folgende Zelte haben Termine an einem "
                f"{_WEEKDAY_NAMES_DE[weekday_query]}:\n"
                + "\n".join(f"- {d}" for d in with_dates)
            )
        else:
            reply = _chat_reply(
                f"Kein Zelt hat aktuell Termine an einem "
                f"{_WEEKDAY_NAMES_DE[weekday_query]}."
            )
        return {"user": user_entry, "reply": reply}

    # ── Try LLM agent first ───────────────────────
    try:
        from wiesn_agent.chat_agent import chat as llm_chat

        _TOOL_LABELS = {
            "monitor_availability": "Checking availability",
            "check_all_portals": "Scanning all portals",
            "check_portal": "Checking portal",
            "navigate_to": "Opening page",
            "detect_forms": "Detecting forms",
            "fill_field": "Filling form field",
            "fill_reservation_form": "Filling reservation",
            "select_option": "Selecting option",
            "click_element": "Clicking element",
            "send_notification": "Sending notification",
            "take_screenshot": "Taking screenshot",
            "get_page_content": "Reading page content",
            "switch_to_iframe": "Switching to iframe",
            "run_js": "Running script",
            "wait_for_element": "Waiting for element",
        }

        def _on_tool_progress(tool_name: str, tool_args: dict) -> None:
            global _thinking_status
            portal = tool_args.get("portal_name") or tool_args.get("name") or ""
            label = _TOOL_LABELS.get(tool_name, tool_name)
            detail = f" — {portal}" if portal else ""
            _thinking_status = f"{label}{detail}"

        history = list(_chat_log)[:-1]  # exclude current message (already in prompt)
        reply_text = await llm_chat(
            user_message=text,
            history=history,
            on_progress=_on_tool_progress,
        )

        # Clear thinking status
        _thinking_status = ""

        reply = _chat_reply(reply_text)
        return {"user": user_entry, "reply": reply}
    except ValueError as e:
        # GITHUB_TOKEN not set — fall back to keyword matching
        logger.info("LLM chat unavailable (%s), using keyword fallback", e)
    except Exception as e:
        logger.warning("LLM chat error, falling back to keywords: %s", e, exc_info=True)

    # ── Keyword fallback ──────────────────────────
    # First, check for date/portal mentions (more specific than keyword intents)
    snapshots = load_snapshots()
    config = _load_config()
    mentioned_date = _extract_date(text)
    mentioned_portal = _find_portal(text, config)

    if mentioned_portal and mentioned_date:
        snap = snapshots.get(mentioned_portal)
        has_date = False
        if snap:
            for d in snap.datum_options:
                val = d.get("value", d.get("text", ""))
                txt = d.get("text", d.get("value", ""))
                if mentioned_date in val or mentioned_date in txt or _date_matches(mentioned_date, txt):
                    has_date = True
                    break
        if has_date:
            reply = _chat_reply(
                f"**{mentioned_portal}** hat den **{mentioned_date}** als auswählbares Datum. "
                f"Abend-Slots sind nicht bestätigt (dafür ist ein Deep-Scan nötig)."
            )
        else:
            reply = _chat_reply(f"**{mentioned_portal}** hat den **{mentioned_date}** leider **nicht** verfügbar.")
        return {"user": user_entry, "reply": reply}

    if mentioned_date:
        with_date = []
        without_date = []
        for name, snap in snapshots.items():
            found = False
            for d in snap.datum_options:
                val = d.get("value", d.get("text", ""))
                txt = d.get("text", d.get("value", ""))
                if mentioned_date in val or mentioned_date in txt or _date_matches(mentioned_date, txt):
                    found = True
                    break
            if found:
                with_date.append(name)
            else:
                without_date.append(name)

        if with_date:
            reply = _chat_reply(
                f"**{len(with_date)}** Zelte haben den **{mentioned_date}** als auswählbares Datum: "
                f"{', '.join(with_date)}.\n\n"
                f"**{len(without_date)}** Zelte haben diesen Tag nicht."
            )
        else:
            reply = _chat_reply(f"Kein Zelt hat den **{mentioned_date}** verfügbar.")
        return {"user": user_entry, "reply": reply}

    if mentioned_portal:
        snap = snapshots.get(mentioned_portal)
        if snap and snap.datum_options:
            dates = [d.get("text", d.get("value", "")) for d in snap.datum_options]
            reply = _chat_reply(
                f"**{mentioned_portal}** hat **{len(dates)}** auswählbare Termine:\n"
                + ", ".join(dates)
            )
        elif snap:
            reply = _chat_reply(f"**{mentioned_portal}** hat aktuell **keine** verfügbaren Termine.")
        else:
            reply = _chat_reply(f"**{mentioned_portal}** wurde noch nicht gescannt.")
        return {"user": user_entry, "reply": reply}

    # ── Intent: Scan ──────────────────────────────
    if intent == "scan":
        config = _load_config()
        target_portal = _find_portal(text, config)

        if target_portal:
            reply = _chat_reply(f"Starting scan for **{target_portal}**...")
            asyncio.create_task(_run_chat_scan(target_portal))
        else:
            enabled = config.enabled_portale()
            reply = _chat_reply(f"Starting scan of all **{len(enabled)}** enabled portals...")
            asyncio.create_task(_run_chat_scan("all"))

        return {"user": user_entry, "reply": reply}

    # ── Intent: Show matches / evening ────────────
    if intent == "matches":
        snapshots = load_snapshots()
        config = _load_config()

        results = []
        for name, snap in snapshots.items():
            for ds in getattr(snap, "deep_scan", []) or []:
                datum_text = ds.get("datum_text", ds.get("datum_value", ""))
                if matches_wunsch(datum_text, config) and ds.get("matching_slots"):
                    slots = list(ds["matching_slots"].keys())
                    results.append(f"- **{name}** on {datum_text}: {', '.join(slots)}")

        if results:
            reply = _chat_reply("Matching slots found:\n" + "\n".join(results))
        else:
            reply = _chat_reply("No matching time slots found yet. The scanner will keep checking.")

        return {"user": user_entry, "reply": reply}

    # ── Intent: Help ──────────────────────────────
    if intent == "help":
        reply = _chat_reply(
            "Here's what I can do:\n"
            "- **scan** / **scan all** — Scan all enabled portals\n"
            "- **scan [tent name]** — Scan a specific tent\n"
            "- **status** — Show current overview\n"
            "- **matches** — Show matching time slots\n"
            "- **portals** — List all configured tents\n"
            "\nYou can write in English or German!"
        )
        return {"user": user_entry, "reply": reply}

    # ── Intent: List portals ──────────────────────
    if intent == "portals":
        config = _load_config()
        snapshots = load_snapshots()
        lines = []
        for p in config.portale:
            snap = snapshots.get(p.name)
            status = "disabled" if not p.enabled else f"{len(snap.datum_options)} dates" if snap and snap.datum_options else "no dates"
            lines.append(f"- {'✅' if p.enabled else '⬜'} **{p.name}** — {status}")
        reply = _chat_reply("Portals:\n" + "\n".join(lines))
        return {"user": user_entry, "reply": reply}

    # ── Truly unrecognized → show help ──
    reply = _chat_reply(
        "I didn't quite catch that. Here's what I can help with:\n"
        "- **scan** — Start scanning portals\n"
        "- **status** — Current overview\n"
        "- **matches** — Show found time slots\n"
        "- **portals** — List all tents\n"
        "\nYou can also ask me in German!"
    )
    return {"user": user_entry, "reply": reply}


async def _run_chat_scan(portal_name: str) -> None:
    """Run a portal scan triggered by chat and post results back."""
    try:
        config = _load_config()
        if portal_name == "all":
            portals = config.enabled_portale()
        else:
            portals = [p for p in config.portale if p.name.lower() == portal_name.lower()]

        results = await _scan_portals(portals, config)
        total_new = sum(r["new_dates"] for r in results)

        _chat_reply(
            f"Scan complete! Checked **{len(portals)}** portals. "
            f"**{total_new}** new dates found."
            + (" Check **matches** for details." if total_new else "")
        )
    except Exception as e:
        _chat_reply(f"Scan failed: {e}")


@app.get("/api/chat/stream")
async def stream_chat(request: Request):
    """SSE endpoint: streams new chat messages (user + agent + system) in real-time."""
    async def event_generator():
        last_event_id = _chat_event_id
        prev_thinking = ""
        yield f"data: {json.dumps({'type': 'connected', 'last_event_id': last_event_id})}\n\n"
        while True:
            if await request.is_disconnected():
                break
            # Broadcast thinking status changes immediately
            if _thinking_status != prev_thinking:
                prev_thinking = _thinking_status
                yield f"data: {json.dumps({'role': 'thinking', 'message': _thinking_status})}\n\n"
            # Emit any messages with event_id > last_event_id
            for item in list(_chat_log):
                eid = item.get("event_id", 0)
                if eid > last_event_id:
                    yield f"data: {json.dumps(item)}\n\n"
                    last_event_id = eid
            await asyncio.sleep(0.3)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/activity/stream")
async def stream_activity(request: Request):
    """SSE endpoint: streams new activity events in real-time."""
    async def event_generator():
        last_event_id = _activity_event_id
        yield f"data: {json.dumps({'type': 'connected', 'last_event_id': last_event_id})}\n\n"
        while True:
            if await request.is_disconnected():
                break
            for item in list(_activity_log):
                eid = item.get("event_id", 0)
                if eid > last_event_id:
                    yield f"data: {json.dumps(item)}\n\n"
                    last_event_id = eid
            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/alerts/stream")
async def stream_alerts(request: Request):
    """SSE endpoint: streams slot alerts to web clients in real-time."""
    async def event_generator():
        last_alert_id = _slot_alert_id
        yield f"data: {json.dumps({'type': 'connected', 'last_alert_id': last_alert_id})}\n\n"
        while True:
            if await request.is_disconnected():
                break
            for item in list(_slot_alerts):
                aid = item.get("alert_id", 0)
                if aid > last_alert_id:
                    yield f"data: {json.dumps(item)}\n\n"
                    last_alert_id = aid
            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/alerts")
async def get_alerts():
    """Get recent slot alerts."""
    return {"alerts": list(_slot_alerts)}


# ═══════════════════════════════════════════════════
# API — Portals & Scanning
# ═══════════════════════════════════════════════════


@app.get("/api/portals")
async def get_portals():
    """List all configured portals with latest scan data."""
    config = _load_config()
    snapshots = load_snapshots()

    portals = []
    for portal in config.portale:
        snap = snapshots.get(portal.name)
        portals.append({
            "name": portal.name,
            "url": portal.url,
            "enabled": portal.enabled,
            "snapshot": _snapshot_to_dict(snap) if snap else None,
        })
    return {"portals": portals}


@app.get("/api/snapshots")
async def get_snapshots():
    """Get all current scan snapshots."""
    snapshots = load_snapshots()
    return {
        name: _snapshot_to_dict(snap)
        for name, snap in snapshots.items()
    }


@app.post("/api/scan/{portal_name}")
async def trigger_scan(portal_name: str):
    """Trigger a scan for a specific portal (or 'all')."""
    # Validate portal name
    if portal_name != "all" and not re.match(r'^[\w\-äöüÄÖÜß .]+$', portal_name):
        raise HTTPException(400, "Invalid portal name")

    config = _load_config()

    if portal_name == "all":
        portals = config.enabled_portale()
    else:
        portals = [p for p in config.portale if p.name.lower() == portal_name.lower()]
        if not portals:
            raise HTTPException(404, f"Portal '{portal_name}' not found")

    results = await _scan_portals(portals, config)

    return {"results": results, "scanned": len(results)}


# ═══════════════════════════════════════════════════
# API — Statistics
# ═══════════════════════════════════════════════════


@app.get("/api/stats/daily")
async def get_daily_stats():
    """Get aggregated daily statistics for charts."""
    history = load_history()
    return {"stats": history.daily_stats()}


@app.get("/api/stats/portals")
async def get_portal_stats():
    """Get per-portal statistics."""
    history = load_history()
    return {"stats": history.portal_stats()}


@app.get("/api/stats/summary")
async def get_stats_summary():
    """Get overall summary statistics."""
    config = _load_config()
    snapshots = load_snapshots()
    history = load_history()

    total_dates = sum(len(s.datum_options) for s in snapshots.values())
    portals_with_dates = sum(1 for s in snapshots.values() if s.datum_options)
    errors = sum(1 for s in snapshots.values() if s.error)

    return {
        "total_portals": len(config.portale),
        "enabled_portals": len(config.enabled_portale()),
        "portals_with_dates": portals_with_dates,
        "total_dates_available": total_dates,
        "scan_errors": errors,
        "history_records": len(history.records),
        "last_scan": max((s.timestamp for s in snapshots.values()), default=None),
    }


# ═══════════════════════════════════════════════════
# API — Configuration
# ═══════════════════════════════════════════════════


@app.get("/api/config")
async def get_config():
    """Get current configuration (sanitized)."""
    config = _load_config()
    return {
        "user": {
            "vorname": config.user.vorname,
            "nachname": config.user.nachname,
            "email": config.user.email,
            "telefon": config.user.telefon,
            "personen": config.user.personen,
            "notizen": config.user.notizen,
        },
        "reservierung": {
            "wunsch_tage": config.reservierung.wunsch_tage,
            "slots": {
                "morgens": {
                    "enabled": config.reservierung.slots.morgens.enabled,
                    "von": config.reservierung.slots.morgens.von,
                    "bis": config.reservierung.slots.morgens.bis,
                    "prioritaet": config.reservierung.slots.morgens.prioritaet,
                },
                "mittags": {
                    "enabled": config.reservierung.slots.mittags.enabled,
                    "von": config.reservierung.slots.mittags.von,
                    "bis": config.reservierung.slots.mittags.bis,
                    "prioritaet": config.reservierung.slots.mittags.prioritaet,
                },
                "abends": {
                    "enabled": config.reservierung.slots.abends.enabled,
                    "von": config.reservierung.slots.abends.von,
                    "bis": config.reservierung.slots.abends.bis,
                    "prioritaet": config.reservierung.slots.abends.prioritaet,
                },
            },
        },
        "monitoring": {
            "check_interval_minutes": config.monitoring.check_interval_minutes,
            "screenshot_on_change": config.monitoring.screenshot_on_change,
        },
        "notifications": {
            "desktop": config.notifications.desktop,
            "apprise_urls": [
                url.split("://")[0] + "://***" if "://" in url else "***"
                for url in config.notifications.apprise_urls
            ],
            "botbell_token": "***" if config.notifications.botbell_token else "",
            "use_emojis": config.notifications.use_emojis,
            "nur_an_tagen": config.notifications.nur_an_tagen,
            "stille_zeit": {
                "von": config.notifications.stille_zeit.von,
                "bis": config.notifications.stille_zeit.bis,
            },
        },
    }


class ConfigUpdate(BaseModel):
    """Partial config update."""

    user: dict[str, Any] | None = None
    reservierung: dict[str, Any] | None = None
    monitoring: dict[str, Any] | None = None
    notifications: dict[str, Any] | None = None


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge overlay into base dict."""
    for key, value in overlay.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


@app.put("/api/config")
async def update_config(update: ConfigUpdate):
    """Update configuration (merges with existing), returns updated config."""
    import yaml

    if not CONFIG_PATH.exists():
        raise HTTPException(404, "config.yaml not found")

    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))

    if update.user:
        _deep_merge(raw.setdefault("user", {}), update.user)
    if update.reservierung:
        _deep_merge(raw.setdefault("reservierung", {}), update.reservierung)
    if update.monitoring:
        _deep_merge(raw.setdefault("monitoring", {}), update.monitoring)
    if update.notifications:
        _deep_merge(raw.setdefault("notifications", {}), update.notifications)

    # Validate merged config before writing to disk
    try:
        WiesnConfig.model_validate(raw)
    except Exception as e:
        raise HTTPException(422, f"Invalid config after merge: {e}")

    CONFIG_PATH.write_text(yaml.dump(raw, allow_unicode=True, default_flow_style=False), encoding="utf-8")

    # Reset Apprise cache so new notification config takes effect
    from wiesn_agent.tools.notify_tools import reset_apprise
    reset_apprise()

    # Return the full reloaded config so frontend stays in sync
    return await get_config()


class PortalToggle(BaseModel):
    enabled: bool


@app.put("/api/portals/{portal_name}/toggle")
async def toggle_portal(portal_name: str, body: PortalToggle):
    """Enable or disable a portal."""
    import yaml

    if not re.match(r'^[\w\-äöüÄÖÜß .]+$', portal_name):
        raise HTTPException(400, "Invalid portal name")

    if not CONFIG_PATH.exists():
        raise HTTPException(404, "config.yaml not found")

    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    found = False
    for portal in raw.get("portale", []):
        if portal.get("name", "").lower() == portal_name.lower():
            portal["enabled"] = body.enabled
            found = True
            break

    if not found:
        raise HTTPException(404, f"Portal '{portal_name}' not found")

    CONFIG_PATH.write_text(yaml.dump(raw, allow_unicode=True, default_flow_style=False), encoding="utf-8")
    return {"status": "ok", "portal": portal_name, "enabled": body.enabled}


# ═══════════════════════════════════════════════════
# Static files — Serve React build
# ═══════════════════════════════════════════════════


def create_app() -> FastAPI:
    """Create the FastAPI app with static file serving."""
    if WEB_DIST.exists():
        app.mount("/assets", StaticFiles(directory=str(WEB_DIST / "assets")), name="assets")

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            """Serve React SPA — all non-API routes go to index.html."""
            file_path = WEB_DIST / full_path
            if file_path.is_file():
                return FileResponse(str(file_path))
            return FileResponse(str(WEB_DIST / "index.html"))

    return app
