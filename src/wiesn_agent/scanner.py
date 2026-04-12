"""Availability Scanner — Detects new reservation dates on Oktoberfest portals.

Core logic: Reads select dropdowns (date, time, area), stores snapshots,
and reports when new options appear.

Deep-Scan: Selects new dates in the dropdown, waits for time slot options,
and filters to desired time slots (e.g. evening only).

Used by:
- MCP tool `monitor_availability` (single scan)
- Agent workflow `MonitorExecutor` (automated loop)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from playwright.async_api import Page

from wiesn_agent.config_model import PortalConfig, SlotsConfig, WiesnConfig

logger = logging.getLogger(__name__)

SNAPSHOT_FILE = Path("./data/availability_snapshots.json")


# ═══════════════════════════════════════════════════
# Data model
# ═══════════════════════════════════════════════════


@dataclass
class SlotInfo:
    """A single available time slot."""
    datum_value: str       # option value
    datum_text: str        # "Montag, 21.09.2026"
    uhrzeiten: list[str] = field(default_factory=list)   # ["16:00", "18:00"]
    bereiche: list[str] = field(default_factory=list)     # ["Innen", "Aussen"]
    tischgroessen: list[str] = field(default_factory=list)


@dataclass
class PortalSnapshot:
    """Snapshot of all available dates for a portal."""
    portal_name: str
    portal_url: str
    timestamp: str
    datum_options: list[dict]  # [{value, text}]
    portal_type: str = "unknown"
    error: str | None = None
    deep_scan: list[dict] = field(default_factory=list)  # [{datum_value, datum_text, uhrzeiten, matching_slots}]

    def datum_values(self) -> set[str]:
        return {d["value"] for d in self.datum_options}

    def datum_texts(self) -> dict[str, str]:
        return {d["value"]: d["text"] for d in self.datum_options}


# ═══════════════════════════════════════════════════
# Snapshot persistence
# ═══════════════════════════════════════════════════


def load_snapshots() -> dict[str, PortalSnapshot]:
    """Load saved snapshots from disk."""
    if not SNAPSHOT_FILE.exists():
        return {}
    try:
        data = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
        result = {}
        for name, snap_data in data.items():
            try:
                result[name] = PortalSnapshot(**snap_data)
            except TypeError as e:
                logger.warning(f"Snapshot '{name}' has invalid fields, skipping: {e}")
                continue
        return result
    except Exception as e:
        logger.warning(f"Snapshot file corrupted, starting fresh: {e}")
        return {}


def save_snapshots(snapshots: dict[str, PortalSnapshot]) -> None:
    """Save snapshots to disk atomically.

    Writes to a temp file first, then renames — prevents corruption
    from concurrent writes or crashes mid-write.
    """
    import tempfile
    from dataclasses import asdict

    SNAPSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {name: asdict(snap) for name, snap in snapshots.items()}
    content = json.dumps(data, indent=2, ensure_ascii=False)

    # Atomic write: write to temp file in same directory, then rename
    fd, tmp_path = tempfile.mkstemp(
        dir=str(SNAPSHOT_FILE.parent),
        suffix=".tmp",
        prefix=".snapshots_",
    )
    try:
        with open(fd, "w", encoding="utf-8") as f:
            f.write(content)
        # On Windows, target must not exist for rename
        if SNAPSHOT_FILE.exists():
            SNAPSHOT_FILE.unlink()
        Path(tmp_path).rename(SNAPSHOT_FILE)
    except Exception:
        # Clean up temp file on failure
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass
        raise


# ═══════════════════════════════════════════════════
# Portal scanning — Extract select options
# ═══════════════════════════════════════════════════

EXTRACT_SELECTS_JS = """() => {
    const result = {datum: [], uhrzeiten: [], bereiche: [], tischgroessen: [], portal_type: 'unknown'};

    const selects = [...document.querySelectorAll('select')].filter(el => el.offsetParent !== null);

    // Heuristic: First select = date, second = time, third = area/table size
    // Additional label-based detection
    selects.forEach((sel, i) => {
        const label = (sel.labels?.[0]?.innerText || '').toLowerCase().trim();
        // Fallback: parent label
        const parentLabel = (sel.closest('[class*="form"]')?.querySelector('label')?.innerText || '').toLowerCase().trim();
        const combinedLabel = label || parentLabel;
        // Name-based (ratskeller.com)
        const name = (sel.name || '').toLowerCase();

        const options = [...sel.options]
            .filter(o => o.value && !o.disabled)
            .map(o => ({value: o.value, text: o.text.trim()}));

        // Detect date
        if (combinedLabel.includes('datum') || combinedLabel.includes('date')
            || name.includes('arrivaldate') || name.includes('datum')
            || (i === 0 && options.some(o => /\\d{2}[./]\\d{2}[./]\\d{4}|september|oktober|october/i.test(o.text)))) {
            result.datum = options;
        }
        // Detect time
        else if (combinedLabel.includes('uhrzeit') || combinedLabel.includes('zeit') || combinedLabel.includes('time')
            || name.includes('strtime') || name.includes('uhrzeit')
            || options.some(o => /^\\d{1,2}[:.:]\\d{2}$/.test(o.value))) {
            result.uhrzeiten = options;
        }
        // Area
        else if (combinedLabel.includes('bereich') || combinedLabel.includes('area') || combinedLabel.includes('section')
            || name.includes('bereich')) {
            result.bereiche = options;
        }
        // Table size / persons
        else if (combinedLabel.includes('tisch') || combinedLabel.includes('person') || combinedLabel.includes('gäste')
            || name.includes('persons') || name.includes('tisch')
            || (options.length > 0 && options.every(o => /^\\d+$/.test(o.value)))) {
            result.tischgroessen = options;
        }
        // Fallback: first unknown = date
        else if (i === 0 && result.datum.length === 0 && options.length > 0) {
            result.datum = options;
        }
    });

    // Portal type
    if ([...document.querySelectorAll('*')].find(el => el.hasAttribute('wire:id'))) result.portal_type = 'livewire';
    else if (document.querySelector('.fi-fo-wizard')) result.portal_type = 'festzelt-os';
    else if (selects.some(s => (s.name || '').includes('appvars'))) result.portal_type = 'ratskeller';
    else if (selects.length > 0) result.portal_type = 'select-portal';
    else result.portal_type = 'no-selects';

    return result;
}"""


FIND_RESERVATION_LINK_JS = """() => {
    // Find links that point to an external reservation portal
    const links = [...document.querySelectorAll('a[href]')];
    const currentHost = location.hostname;

    for (const a of links) {
        const href = a.href || '';
        const text = (a.innerText || '').trim().toLowerCase();
        if (!href || href.startsWith('javascript:') || href.startsWith('mailto:')
            || href.startsWith('tel:') || href === '#') continue;

        // Skip same-page anchors and cookie/consent links
        try { if (new URL(href).pathname === location.pathname && new URL(href).hash) continue; } catch(e) {}

        // Match reservation-related links
        const isReservLink = text.includes('reservier') || text.includes('buchen')
            || text.includes('anfrage') || text.includes('booking')
            || text.includes('jetzt reservieren') || text.includes('zum reservierungsportal')
            || text.includes('reservierungsanfrage')
            || href.includes('reservierung') || href.includes('reservation')
            || href.includes('booking') || href.includes('anfrage');

        // Prefer links to a different host (external booking portal)
        if (isReservLink) {
            try {
                const linkHost = new URL(href).hostname;
                if (linkHost !== currentHost) return href;
            } catch(e) {}
        }
    }

    // Second pass: same-host reservation links (subpages)
    for (const a of links) {
        const href = a.href || '';
        const text = (a.innerText || '').trim().toLowerCase();
        if (!href || href.startsWith('javascript:') || href === '#') continue;
        try { if (new URL(href).pathname === location.pathname) continue; } catch(e) {}

        if (text.includes('reservier') || text.includes('anfrage')
            || href.includes('/reservation') || href.includes('/reservierung')
            || href.includes('/booking')) {
            return href;
        }
    }
    return null;
}"""


async def scan_portal_availability(page: Page, portal: PortalConfig, timeout: int = 30000) -> PortalSnapshot:
    """Scan a portal and return a snapshot of available dates.

    If the landing page has no <select> dropdowns, follows reservation links
    to find the actual booking form (many portals have a landing page that
    links to an external or separate booking system).
    """
    now = datetime.now().isoformat(timespec="seconds")

    try:
        await page.goto(portal.url, wait_until="domcontentloaded", timeout=timeout)
        await page.wait_for_timeout(4000)  # Wait for JS / Livewire to load

        data = await page.evaluate(EXTRACT_SELECTS_JS)

        # Track effective URL (may differ from portal.url after link-follow)
        effective_url = portal.url

        # If no selects found, try to follow a reservation link
        if data.get("portal_type") == "no-selects":
            reservation_link = await page.evaluate(FIND_RESERVATION_LINK_JS)
            if reservation_link:
                logger.info(f"  → Following reservation link: {reservation_link}")
                try:
                    await page.goto(reservation_link, wait_until="domcontentloaded", timeout=timeout)
                    await page.wait_for_timeout(4000)
                    data = await page.evaluate(EXTRACT_SELECTS_JS)
                    # Update portal_type if we found something
                    if data.get("portal_type") != "no-selects":
                        effective_url = page.url
                        logger.info(f"  → Booking portal found: {data.get('portal_type')}")
                except Exception as e:
                    logger.warning(f"  → Link-follow failed: {e}")

        return PortalSnapshot(
            portal_name=portal.name,
            portal_url=effective_url,
            timestamp=now,
            datum_options=data.get("datum", []),
            portal_type=data.get("portal_type", "unknown"),
        )

    except Exception as e:
        return PortalSnapshot(
            portal_name=portal.name,
            portal_url=portal.url,
            timestamp=now,
            datum_options=[],
            portal_type="error",
            error=str(e)[:200],
        )


# ═══════════════════════════════════════════════════
# Deep-Scan — Select date → Read time slots
# ═══════════════════════════════════════════════════

SELECT_DATE_AND_READ_TIMES_JS = """([dateValue]) => {
    // Find the date select (same heuristic as EXTRACT_SELECTS_JS)
    const selects = [...document.querySelectorAll('select')].filter(el => el.offsetParent !== null);
    let datumSelect = null;
    selects.forEach((sel, i) => {
        const label = (sel.labels?.[0]?.innerText || '').toLowerCase();
        const name = (sel.name || '').toLowerCase();
        if (label.includes('datum') || label.includes('date')
            || name.includes('arrivaldate') || name.includes('datum')
            || (i === 0 && [...sel.options].some(o => /\\d{2}[./]\\d{2}[./]\\d{4}|september|oktober/i.test(o.text)))) {
            datumSelect = sel;
        } else if (i === 0 && !datumSelect) {
            datumSelect = sel;
        }
    });
    if (!datumSelect) return {error: 'No date select found'};

    // Select the date
    datumSelect.value = dateValue;
    datumSelect.dispatchEvent(new Event('input', {bubbles: true}));
    datumSelect.dispatchEvent(new Event('change', {bubbles: true}));
    return {status: 'selected', value: dateValue};
}"""

EXTRACT_TIMES_JS = """() => {
    // Find the time select (should be populated after date selection)
    const selects = [...document.querySelectorAll('select')].filter(el => el.offsetParent !== null);
    let uhrzeiten = [];
    selects.forEach((sel, i) => {
        const label = (sel.labels?.[0]?.innerText || '').toLowerCase();
        const name = (sel.name || '').toLowerCase();
        const options = [...sel.options].filter(o => o.value && !o.disabled).map(o => ({value: o.value, text: o.text.trim()}));
        if (label.includes('uhrzeit') || label.includes('zeit') || label.includes('time') || label.includes('schicht')
            || name.includes('strtime') || name.includes('uhrzeit') || name.includes('schicht')
            || options.some(o => /^\\d{1,2}[:.:]\\d{2}/.test(o.value) || /^\\d{1,2}[:.:]\\d{2}/.test(o.text))) {
            uhrzeiten = options;
        }
    });
    return {uhrzeiten: uhrzeiten};
}"""


def parse_time(text: str) -> tuple[int, int] | None:
    """Extract hour:minute from time text. Returns (h, m) or None."""
    m = re.search(r"(\d{1,2})[:.:](\d{2})", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


def time_in_slot(time_text: str, slots: SlotsConfig) -> list[str]:
    """Check which active slots a time falls into. Returns list of slot names.

    Recognizes both numeric times ("18:00") and textual descriptions
    ("Mittag", "Abend", "Abendveranstaltung", "Mittagstisch").
    """
    # Text-based detection first (portal shows e.g. "Mittag", "Abend")
    text_lower = time_text.lower().strip()
    text_matches = []

    abend_keywords = ("abend", "evening", "nacht", "night", "dinner", "ab 16:", "ab 17:", "ab 18:", "ab 16 uhr", "ab 17 uhr", "ab 18 uhr")
    mittags_keywords = ("mittag", "lunch", "noon", "12:", "13:", "14:", "15:")
    morgens_keywords = ("morgen", "früh", "morning", "brunch", "10:", "11:")

    for kw in abend_keywords:
        if kw in text_lower:
            text_matches.append("abends")
            break
    for kw in mittags_keywords:
        if kw in text_lower:
            text_matches.append("mittags")
            break
    for kw in morgens_keywords:
        if kw in text_lower:
            text_matches.append("morgens")
            break

    if text_matches:
        return [s for s in text_matches if getattr(slots, s).enabled]

    # Parse numeric time
    parsed = parse_time(time_text)
    if not parsed:
        return []

    h, m = parsed
    minutes = h * 60 + m
    matching = []

    for slot_name in ("morgens", "mittags", "abends"):
        slot = getattr(slots, slot_name)
        if not slot.enabled:
            continue
        von_h, von_m = map(int, slot.von.split(":"))
        bis_h, bis_m = map(int, slot.bis.split(":"))
        von_min = von_h * 60 + von_m
        bis_min = bis_h * 60 + bis_m
        if von_min <= minutes < bis_min:
            matching.append(slot_name)

    return matching


@dataclass
class DateDeepScanResult:
    """Result of a deep-scan for a single date."""
    datum_value: str
    datum_text: str
    uhrzeiten: list[dict]         # [{value, text}]
    abend_slots: list[dict]       # nur Uhrzeit-Optionen die in "abends" fallen
    matching_slots: dict[str, list[dict]]  # {"abends": [...], "mittags": [...]}
    scan_error: str | None = None  # None = success, str = scan failed

    @property
    def has_abend(self) -> bool:
        return len(self.abend_slots) > 0

    @property
    def scan_succeeded(self) -> bool:
        return self.scan_error is None

    def summary(self) -> str:
        if self.scan_error:
            return f"{self.datum_text}: SCAN FAILED — {self.scan_error}"
        if not self.uhrzeiten:
            return f"{self.datum_text}: no time slots loaded"
        parts = [f"{self.datum_text}: {len(self.uhrzeiten)} time slots"]
        if self.abend_slots:
            times = ", ".join(d["text"] for d in self.abend_slots[:4])
            parts.append(f"evening: {times}")
        return " | ".join(parts)


async def deep_scan_date(
    page: Page,
    portal: PortalConfig,
    datum_value: str,
    datum_text: str,
    slots: SlotsConfig,
    timeout: int = 30000,
) -> DateDeepScanResult:
    """Select a date in the dropdown, wait for time options, classify by slots."""
    try:
        # Select the date
        await page.evaluate(SELECT_DATE_AND_READ_TIMES_JS, [datum_value])

        # Wait for time options to populate (replaces fixed 3s sleep).
        # Poll up to `timeout` ms for the time select to gain options.
        deadline_ms = min(timeout, 15000)
        poll_interval = 500
        elapsed = 0
        uhrzeiten: list[dict] = []
        while elapsed < deadline_ms:
            await page.wait_for_timeout(poll_interval)
            elapsed += poll_interval
            data = await page.evaluate(EXTRACT_TIMES_JS)
            uhrzeiten = data.get("uhrzeiten", [])
            if uhrzeiten:
                break
        if not uhrzeiten:
            # Final attempt after full wait
            data = await page.evaluate(EXTRACT_TIMES_JS)
            uhrzeiten = data.get("uhrzeiten", [])

        # Classify by slots
        matching_slots: dict[str, list[dict]] = {}
        abend_slots: list[dict] = []

        for uz in uhrzeiten:
            text = uz.get("text", uz.get("value", ""))
            slot_names = time_in_slot(text, slots)
            for sn in slot_names:
                matching_slots.setdefault(sn, []).append(uz)
            if "abends" in slot_names:
                abend_slots.append(uz)

        return DateDeepScanResult(
            datum_value=datum_value,
            datum_text=datum_text,
            uhrzeiten=uhrzeiten,
            abend_slots=abend_slots,
            matching_slots=matching_slots,
        )

    except Exception as e:
        logger.warning(f"Deep-scan failed for {datum_text}: {e}")
        return DateDeepScanResult(
            datum_value=datum_value,
            datum_text=datum_text,
            uhrzeiten=[],
            abend_slots=[],
            matching_slots={},
            scan_error=str(e)[:200],
        )


# ═══════════════════════════════════════════════════
# Comparison — Detect new dates
# ═══════════════════════════════════════════════════


@dataclass
class AvailabilityChange:
    """Describes a change detected for a portal."""
    portal_name: str
    portal_url: str
    new_dates: list[dict]         # [{value, text}] — completely new dates
    removed_dates: list[dict]     # dates that disappeared (sold out?)
    is_first_scan: bool = False   # first scan — everything is "new"
    deep_scan_results: list[DateDeepScanResult] = field(default_factory=list)

    @property
    def has_new(self) -> bool:
        return len(self.new_dates) > 0

    @property
    def has_abend_slots(self) -> bool:
        return any(r.has_abend for r in self.deep_scan_results)

    def summary(self) -> str:
        if self.is_first_scan:
            return f"{self.portal_name}: First scan — {len(self.new_dates)} dates found"
        parts = []
        if self.new_dates:
            dates = ", ".join(d["text"] for d in self.new_dates[:5])
            parts.append(f"NEW {len(self.new_dates)} dates: {dates}")
        if self.deep_scan_results:
            abend_count = sum(len(r.abend_slots) for r in self.deep_scan_results)
            if abend_count:
                parts.append(f"{abend_count} evening slots available!")
            else:
                parts.append("No evening slots found")
        if self.removed_dates:
            dates = ", ".join(d["text"] for d in self.removed_dates[:3])
            parts.append(f"{len(self.removed_dates)} sold out: {dates}")
        return f"{self.portal_name}: {' | '.join(parts)}" if parts else f"{self.portal_name}: No change"


def compare_snapshots(old: PortalSnapshot | None, new: PortalSnapshot) -> AvailabilityChange:
    """Compare old and new snapshots to detect changes."""
    if old is None:
        return AvailabilityChange(
            portal_name=new.portal_name,
            portal_url=new.portal_url,
            new_dates=new.datum_options,
            removed_dates=[],
            is_first_scan=True,
        )

    old_values = old.datum_values()
    new_values = new.datum_values()
    new_texts = new.datum_texts()
    old_texts = old.datum_texts()

    added = new_values - old_values
    removed = old_values - new_values

    return AvailabilityChange(
        portal_name=new.portal_name,
        portal_url=new.portal_url,
        new_dates=[{"value": v, "text": new_texts.get(v, v)} for v in sorted(added)],
        removed_dates=[{"value": v, "text": old_texts.get(v, v)} for v in sorted(removed)],
    )


# ═══════════════════════════════════════════════════
# Preference filter — Only report relevant dates
# ═══════════════════════════════════════════════════


def matches_wunsch(date_text: str, config: WiesnConfig) -> bool:
    """Check if a date text matches the user's preferred dates.

    Returns True if:
    - No preferred dates configured (all are relevant)
    - The date text contains one of the preferred dates
    """
    if not config.reservierung.wunsch_tage:
        return True

    # Try to extract date from text
    # Formats: "Montag, 21.09.2026" or "Mo. 21.09.2026" or "2026-09-21"
    import re

    # Check DD.MM.YYYY format
    date_match = re.search(r"(\d{2})[./](\d{2})[./](\d{4})", date_text)
    if date_match:
        day, month, year = date_match.groups()
        iso_date = f"{year}-{month}-{day}"
        return iso_date in config.reservierung.wunsch_tage

    # Check YYYY-MM-DD format (ISO)
    iso_match = re.search(r"(\d{4})-(\d{2})-(\d{2})", date_text)
    if iso_match:
        return iso_match.group(0) in config.reservierung.wunsch_tage

    # Fallback: direct string match
    for wunsch in config.reservierung.wunsch_tage:
        if wunsch in date_text:
            return True

    return False


def filter_relevant_changes(change: AvailabilityChange, config: WiesnConfig) -> AvailabilityChange:
    """Filter changes to only the user's preferred dates."""
    if not config.reservierung.wunsch_tage:
        return change  # No filter

    return AvailabilityChange(
        portal_name=change.portal_name,
        portal_url=change.portal_url,
        new_dates=[d for d in change.new_dates if matches_wunsch(d["text"], config)],
        removed_dates=change.removed_dates,  # Always report removed dates
        is_first_scan=change.is_first_scan,
        deep_scan_results=change.deep_scan_results,
    )

