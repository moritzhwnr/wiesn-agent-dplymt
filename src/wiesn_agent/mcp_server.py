"""Wiesn-Agent MCP Server — Oktoberfest reservation tools as MCP Server.

Other agents (Copilot, Claude, etc.) can connect to this server and use
all tools directly: check portals, detect forms, fill reservations, send notifications.

Start:
    python -m wiesn_agent.mcp_server              # stdio (default)
    python -m wiesn_agent.mcp_server --http        # Streamable HTTP on :8080
    uv run mcp dev src/wiesn_agent/mcp_server.py   # MCP Inspector
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from playwright.async_api import Browser, Page, async_playwright

from wiesn_agent.config_model import WiesnConfig

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════
# Lifespan — Initialize browser & config on startup
# ═══════════════════════════════════════════════════


@dataclass
class WiesnContext:
    """Shared state for all MCP tools."""

    config: WiesnConfig
    browser: Browser
    page: Page
    portal_hashes: dict[str, str] = field(default_factory=dict)
    page_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _main_page: Page | None = None


@asynccontextmanager
async def wiesn_lifespan(server: FastMCP) -> AsyncIterator[WiesnContext]:
    """Start Playwright and load config on server startup."""
    # Load config
    config_path = Path("config.yaml")
    if config_path.exists():
        config = WiesnConfig.from_yaml(config_path)
    else:
        # Minimal config if no file found
        config = WiesnConfig.from_yaml(Path("config.example.yaml"))

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=config.browser.headless,
        slow_mo=config.browser.slow_mo,
    )
    page = await browser.new_page()

    logger.info("Wiesn MCP Server started — browser ready.")
    try:
        yield WiesnContext(config=config, browser=browser, page=page)
    finally:
        await browser.close()
        await pw.stop()
        logger.info("Wiesn MCP Server stopped.")


# ═══════════════════════════════════════════════════
# FastMCP Server
# ═══════════════════════════════════════════════════

mcp = FastMCP(
    "Wiesn-Agent",
    instructions=(
        "You are the Wiesn-Agent — an assistant for Oktoberfest reservations. "
        "You can monitor booking portals, detect and fill forms, "
        "and notify the user. Use the available tools. "
        "IMPORTANT: Never submit a reservation form without explicit user confirmation."
    ),
    lifespan=wiesn_lifespan,
    json_response=True,
)


# ═══════════════════════════════════════════════════
# Resources — Configuration data
# ═══════════════════════════════════════════════════


@mcp.resource("wiesn://config")
def get_config(ctx: Context[ServerSession, WiesnContext]) -> str:
    """Current Wiesn-Agent configuration (portals, slots — PII redacted)."""
    config = ctx.request_context.lifespan_context.config
    return json.dumps(config.redacted_dump(), indent=2, default=str)


@mcp.resource("wiesn://portale")
def list_portale(ctx: Context[ServerSession, WiesnContext]) -> str:
    """List of all configured Oktoberfest booking portals."""
    config = ctx.request_context.lifespan_context.config
    portale = [
        {"name": p.name, "url": p.url, "enabled": p.enabled}
        for p in config.portale
    ]
    return json.dumps(portale, indent=2)


@mcp.resource("wiesn://slots")
def list_slots(ctx: Context[ServerSession, WiesnContext]) -> str:
    """Configured time slots (morning, afternoon, evening) with priorities."""
    config = ctx.request_context.lifespan_context.config
    slots = []
    for name, slot in config.enabled_slots():
        slots.append({
            "name": name,
            "von": slot.von,
            "bis": slot.bis,
            "prioritaet": slot.prioritaet,
        })
    return json.dumps(slots, indent=2)


# ═══════════════════════════════════════════════════
# Tools — Portal monitoring
# ═══════════════════════════════════════════════════


@mcp.tool()
async def check_portal(
    url: Annotated[str, "URL of the booking portal"],
    name: Annotated[str, "Name of the tent/portal"] = "",
    ctx: Context[ServerSession, WiesnContext] = None,  # type: ignore[assignment]
) -> str:
    """Navigate to a booking portal and check if it has changed.

    Returns the page title, whether the page changed, and the page content.
    """
    wiesn = ctx.request_context.lifespan_context
    async with wiesn.page_lock:
        page = wiesn.page

        await ctx.info(f"Navigating to {name or url}...")
        await page.goto(url, wait_until="domcontentloaded", timeout=wiesn.config.browser.timeout)
        title = await page.title()

        # Hash comparison
        content = await page.evaluate("() => document.body.innerText")
        current_hash = hashlib.sha256(content.encode()).hexdigest()
        old_hash = wiesn.portal_hashes.get(url)
        changed = old_hash is not None and current_hash != old_hash
        wiesn.portal_hashes[url] = current_hash

        # Page content (truncated)
        text = content[:3000] + "..." if len(content) > 3000 else content

        await ctx.info(f"{'Change detected!' if changed else 'No change.'}")

        return json.dumps({
            "portal": name or url,
            "url": url,
            "title": title,
            "changed": changed,
            "first_check": old_hash is None,
            "content_preview": text,
        }, ensure_ascii=False)


@mcp.tool()
async def check_all_portals(
    ctx: Context[ServerSession, WiesnContext],
) -> str:
    """Check ALL configured portals for changes.

    Goes through each enabled portal and reports its status.
    """
    wiesn = ctx.request_context.lifespan_context
    config = wiesn.config
    results = []

    portale = config.enabled_portale()
    await ctx.info(f"Checking {len(portale)} portals...")

    for i, portal in enumerate(portale):
        await ctx.report_progress(progress=i, total=len(portale), message=f"Checking {portal.name}...")
        try:
            result_str = await check_portal(url=portal.url, name=portal.name, ctx=ctx)
            results.append(json.loads(result_str))
        except Exception as e:
            results.append({
                "portal": portal.name,
                "url": portal.url,
                "error": str(e),
            })

    await ctx.report_progress(progress=len(portale), total=len(portale), message="Done!")
    changed_portals = [r for r in results if r.get("changed")]

    return json.dumps({
        "total": len(results),
        "changed": len(changed_portals),
        "results": results,
    }, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════
# Tools — Form detection & filling
# ═══════════════════════════════════════════════════


@mcp.tool()
async def detect_forms(
    ctx: Context[ServerSession, WiesnContext],
) -> str:
    """Detect all forms and interactive fields on the current page.

    Supports:
    - Classic HTML forms
    - Filament/Livewire-based wizard forms (FestZelt OS)
    - Progressive-reveal selects (Livewire: empty first, populate after selection)
    - Ratskeller.com-style booking forms (appvars[...] fields)
    - Iframes with embedded forms
    - Fields outside <form> tags (wire:model bound)
    """
    page = ctx.request_context.lifespan_context.page

    result = await page.evaluate("""() => {
        const data = {forms: [], wizard: null, fields: [], iframes: [], portal_type: 'unknown'};

        // --- 1) Filament Wizard erkennen ---
        const wizard = document.querySelector('.fi-fo-wizard');
        if (wizard) {
            const stepsInput = wizard.querySelector('input[x-ref="stepsData"]')
                || wizard.querySelector('input[type="hidden"]');
            let stepIds = [];
            try { stepIds = stepsInput ? JSON.parse(stepsInput.value || '[]') : []; } catch(e) {}
            const headers = [...wizard.querySelectorAll('.fi-fo-wizard-header-step')]
                .map(el => el.querySelector('.fi-fo-wizard-header-step-label')?.innerText?.trim() || '');
            const activeIdx = headers.findIndex((_, i) =>
                wizard.querySelectorAll('.fi-fo-wizard-header-step')[i]
                    ?.classList?.contains('fi-active')
            );
            data.wizard = {
                steps: Math.max(stepIds.length, headers.length),
                step_labels: headers,
                active_step: activeIdx >= 0 ? activeIdx : 0,
                has_next: !!wizard.querySelector('button:not(.hidden) .fi-btn-label'),
            };
            data.portal_type = 'festzelt-os';
        }

        // --- 2) Alle Felder (sichtbar + sr-only Radios + Livewire-managed) ---
        document.querySelectorAll('input, select, textarea').forEach(el => {
            if (el.type === 'hidden') return;
            // Include sr-only radios (Filament Radio Cards) and visible elements
            const isSrOnly = el.classList.contains('sr-only');
            const isVisible = el.offsetParent !== null;
            if (!isVisible && !isSrOnly) return;

            const wireModel = el.getAttribute('wire:model')
                || el.getAttribute('wire:model.live')
                || el.getAttribute('wire:model.blur') || '';
            const field = {
                tag: el.tagName.toLowerCase(),
                type: el.type || '',
                name: el.name || '',
                id: el.id || '',
                placeholder: el.placeholder || '',
                required: el.required,
                label: el.labels?.[0]?.innerText?.trim() || '',
                wire_model: wireModel,
                value: el.value || '',
                visible: isVisible,
            };
            // Fallback label: check parent or preceding sibling for label text
            if (!field.label) {
                const parent = el.closest('.form-group, .field, [class*="form"]');
                const sibLabel = parent?.querySelector('label, .label, [class*="label"]');
                if (sibLabel) field.label = sibLabel.innerText?.trim() || '';
                // Also check preceding text node / element
                if (!field.label && el.previousElementSibling) {
                    const prev = el.previousElementSibling;
                    if (prev.tagName === 'LABEL' || prev.tagName === 'SPAN' || prev.tagName === 'DIV') {
                        field.label = prev.innerText?.trim()?.substring(0, 50) || '';
                    }
                }
            }
            if (el.tagName === 'SELECT') {
                field.options = [...el.options]
                    .filter(o => o.value)
                    .map(o => ({value: o.value, text: o.text.trim()}));
                field.option_count = field.options.length;
                // Livewire progressive select: leer = wartet auf vorherigen Select
                field.awaiting_input = field.option_count === 0 && isVisible;
            }
            if (el.type === 'radio') {
                field.checked = el.checked;
                field.sr_only = isSrOnly;
            }
            data.fields.push(field);
        });

        // --- 3) Klassische <form>-Tags ---
        document.querySelectorAll('form').forEach((form, fi) => {
            const allFields = form.querySelectorAll('input:not([type=hidden]), select, textarea');
            data.forms.push({
                index: fi,
                action: form.action || '',
                method: form.method || 'get',
                id: form.id || '',
                field_count: allFields.length,
                has_wire: !![...form.querySelectorAll('*')].find(el => el.hasAttribute('wire:model') || el.hasAttribute('wire:id')),
            });
        });

        // --- 4) Detect iframes (for embedded booking portals) ---
        document.querySelectorAll('iframe').forEach(f => {
            const src = f.src || '';
            if (src && !src.includes('cookie') && !src.includes('consent') && !src.includes('recaptcha')) {
                data.iframes.push({src: src, id: f.id || '', name: f.name || ''});
            }
        });

        // --- 5) Portal-Typ klassifizieren ---
        if (!data.wizard) {
            const hasLivewire = !![...document.querySelectorAll('*')].find(el => el.hasAttribute('wire:id'));
            if (hasLivewire) data.portal_type = 'livewire';
            else if (data.iframes.length > 0) data.portal_type = 'iframe-embed';
            else if (data.forms.length > 0 && data.fields.some(f => f.name.includes('appvars'))) data.portal_type = 'ratskeller';
            else if (data.forms.length > 0) data.portal_type = 'standard-form';
            else if (data.fields.length > 0) data.portal_type = 'fields-no-form';
            else data.portal_type = 'info-only';
        }

        return data;
    }""")

    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def fill_field(
    selector: Annotated[str, "CSS selector of the input field (e.g. '#email' or 'input[name=vorname]')"],
    value: Annotated[str, "The value to enter"],
    ctx: Context[ServerSession, WiesnContext],
) -> str:
    """Fill a single form field on the current page."""
    page = ctx.request_context.lifespan_context.page
    try:
        await page.fill(selector, value)
        await ctx.info(f"Field '{selector}' filled with '{value}'")
        return json.dumps({"selector": selector, "value": value, "status": "ok"})
    except Exception as e:
        return json.dumps({"selector": selector, "error": str(e)})


@mcp.tool()
async def select_option(
    selector: Annotated[str, "CSS selector or index (e.g. '#myselect', 'select:nth-of-type(2)', or '0' for first select)"],
    value: Annotated[str, "The value to select (option value)"],
    ctx: Context[ServerSession, WiesnContext],
) -> str:
    """Select an option in a dropdown — Livewire/Filament-compatible.

    Automatically dispatches input+change events with {bubbles: true} so
    Livewire wire:model bindings detect the change. Also supports
    select-by-index when the selector is a number.
    """
    page = ctx.request_context.lifespan_context.page
    try:
        result = await page.evaluate(r"""([sel, val]) => {
            let el;
            if (/^\d+$/.test(sel)) {
                el = document.querySelectorAll('select')[parseInt(sel)];
            } else {
                el = document.querySelector(sel);
            }
            if (!el) return {error: 'Element not found: ' + sel};
            if (el.tagName !== 'SELECT') return {error: 'Element is not a <select>: ' + sel};

            // Set value
            el.value = val;
            // Livewire needs input + change events with bubbles
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));

            const selected = el.options[el.selectedIndex];
            return {
                status: 'ok',
                selector: sel,
                value: val,
                selected_text: selected ? selected.text.trim() : '',
            };
        }""", [selector, value])
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"selector": selector, "error": str(e)})


@mcp.tool()
async def click_element(
    selector: Annotated[str, "CSS selector of the element (button, link, etc.)"],
    force: Annotated[bool, "Force click via JS (for sr-only/hidden elements like Radio-Cards)"] = False,
    ctx: Context[ServerSession, WiesnContext] = None,  # type: ignore[assignment]
) -> str:
    """Click on an element — with JS fallback for Filament Radio-Cards and sr-only inputs.

    With force=True the click is executed directly via JavaScript, which is needed
    for Filament Radio-Cards (the real input is sr-only/hidden).
    """
    page = ctx.request_context.lifespan_context.page
    try:
        if force:
            result = await page.evaluate("""(sel) => {
                const el = document.querySelector(sel);
                if (!el) return {error: 'Element not found: ' + sel};
                if (el.type === 'radio' || el.type === 'checkbox') {
                    el.checked = true;
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                } else {
                    el.click();
                }
                return {status: 'clicked', selector: sel, method: 'js-force'};
            }""", selector)
            return json.dumps(result, ensure_ascii=False)
        else:
            await page.click(selector)
            return json.dumps({"selector": selector, "status": "clicked", "method": "playwright"})
    except Exception as e:
        return json.dumps({"selector": selector, "error": str(e)})


@mcp.tool()
async def fill_reservation_form(
    ctx: Context[ServerSession, WiesnContext],
) -> str:
    """Automatically fill a reservation form with user data from the config.

    Supports both classic HTML forms and Filament/Livewire-based forms
    (FestZelt OS). Detects fields globally on the page (not just in <form>).
    Uses Livewire-compatible events for field filling.

    DOES NOT SUBMIT THE FORM — the user must do that manually!
    """
    wiesn = ctx.request_context.lifespan_context
    page = wiesn.page
    user = wiesn.config.user

    await ctx.info("Finding form fields and filling with user data...")

    # Mapping: Typical field names/IDs → User data
    # Covers: FestZelt OS, WordPress forms, ratskeller.com (appvars[...])
    field_mapping = {
        # Vorname
        "vorname": user.vorname,
        "first_name": user.vorname,
        "firstname": user.vorname,
        "travelerforename": user.vorname,  # ratskeller.com
        # Nachname
        "nachname": user.nachname,
        "last_name": user.nachname,
        "lastname": user.nachname,
        "travelername": user.nachname,  # ratskeller.com
        # Name (kombiniert)
        "name": f"{user.vorname} {user.nachname}",
        # Email
        "email": user.email,
        "e-mail": user.email,
        "mail": user.email,
        "traveleremail": user.email,  # ratskeller.com
        # Telefon
        "telefon": user.telefon,
        "phone": user.telefon,
        "tel": user.telefon,
        "travelerphone": user.telefon,  # ratskeller.com
        # Personen
        "personen": str(user.personen),
        "persons": str(user.personen),
        "guests": str(user.personen),
        "gaeste": str(user.personen),
        "anzahl": str(user.personen),
        # Notizen
        "bemerkung": user.notizen,
        "notizen": user.notizen,
        "notes": user.notizen,
        "comment": user.notizen,
        "kommentar": user.notizen,
        # Address fields (FestZelt OS + ratskeller.com)
        "street": user.strasse,
        "travelerstreet": user.strasse,
        "house_number": user.hausnummer,
        "postcode": user.plz,
        "travelerzip": user.plz,
        "city": user.stadt,
        "travelercity": user.stadt,
        "travelercompany": user.firma,
    }

    filled = []
    errors = []

    # All visible fields on the page (including Livewire-managed)
    fields = await page.evaluate("""() => {
        const fields = [];
        document.querySelectorAll('input, select, textarea').forEach(el => {
            if (el.type === 'hidden' || !el.offsetParent) return;
            if (el.type === 'radio' || el.type === 'checkbox') return;
            fields.push({
                tag: el.tagName.toLowerCase(),
                type: el.type || '',
                name: (el.name || '').toLowerCase(),
                id: (el.id || '').toLowerCase(),
                placeholder: (el.placeholder || '').toLowerCase(),
                label: (el.labels?.[0]?.innerText || '').toLowerCase().trim(),
            });
        });
        return fields;
    }""")

    for f in fields:
        field_key = None
        # Extract the meaningful part of the name (handle appvars[travelername] → travelername)
        f_name = f["name"]
        if "[" in f_name:
            f_name = f_name.split("[")[-1].rstrip("]")
        f_name = f_name.lower()
        f_id = f["id"].lower()
        f_ph = f.get("placeholder", "").lower()
        f_label = f.get("label", "").lower()

        for key in field_mapping:
            if (key in f_name or key in f_id
                    or key in f_ph or key in f_label):
                field_key = key
                break

        if field_key and field_mapping[field_key]:
            # Filament IDs contain dots → use getElementById instead of CSS selector
            field_id = f["id"]
            field_name = f["name"]
            value = field_mapping[field_key]
            try:
                await page.evaluate("""([id, name, tag, val]) => {
                    let el = id ? document.getElementById(id) : null;
                    if (!el && name) el = document.querySelector('[name="' + name + '"]');
                    if (!el) return;
                    if (tag === 'select') {
                        el.value = val;
                    } else {
                        // Simulate keyboard input for Livewire
                        el.focus();
                        el.value = val;
                        el.dispatchEvent(new Event('input', {bubbles: true}));
                    }
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                }""", [field_id, field_name, f["tag"], value])
                filled.append({"field": field_key, "id": field_id, "value": value})
            except Exception as e:
                errors.append({"field": field_key, "id": field_id, "error": str(e)})

    return json.dumps({
        "fields_filled": len(filled),
        "fields_failed": len(errors),
        "filled": filled,
        "errors": errors,
        "notice": "Form NOT submitted — please confirm and submit manually!",
    }, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════
# Tools — Screenshots & page content
# ═══════════════════════════════════════════════════


@mcp.tool()
async def switch_to_iframe(
    selector: Annotated[str, "CSS selector of the iframe (e.g. 'iframe', 'iframe[src*=\"booking\"]', '#booking-frame')"],
    ctx: Context[ServerSession, WiesnContext],
) -> str:
    """Switch the browser context into an iframe.

    Needed for portals like Festzelt Tradition that embed an external booking form
    (e.g. ratskeller.com) via iframe. After switching, all other tools
    (detect_forms, fill_field, etc.) operate in the iframe context.

    To switch back to the main frame, use selector='main' or 'parent'.
    """
    wiesn = ctx.request_context.lifespan_context
    page = wiesn.page

    try:
        if selector in ("main", "parent", "top"):
            # Back to main frame — restore original page and close iframe page
            if hasattr(wiesn, '_main_page') and wiesn._main_page:
                iframe_page = wiesn.page
                wiesn.page = wiesn._main_page
                wiesn._main_page = None
                # Close the iframe page to free resources
                if iframe_page != wiesn.page:
                    try:
                        await iframe_page.close()
                    except Exception:
                        pass
            return json.dumps({"status": "ok", "frame": "main", "url": wiesn.page.url})

        frame_element = await page.wait_for_selector(selector, timeout=10000)
        if not frame_element:
            return json.dumps({"error": f"iframe '{selector}' not found."})

        frame = await frame_element.content_frame()
        if not frame:
            return json.dumps({"error": f"Could not access frame content of '{selector}'."})

        # Store the main page so we can restore it later
        wiesn._main_page = page

        # Navigate to the iframe URL so all tools operate on it
        iframe_url = await frame_element.get_attribute("src")
        if iframe_url:
            new_page = await wiesn.browser.new_page()
            await new_page.goto(iframe_url, wait_until="domcontentloaded",
                                timeout=wiesn.config.browser.timeout)
            wiesn.page = new_page
            title = await new_page.title()
            return json.dumps({
                "status": "ok",
                "frame_url": iframe_url,
                "title": title,
                "hint": "All tools now operate on the iframe content. "
                        "Use switch_to_iframe with selector='main' to go back.",
            })

        return json.dumps({"error": "iframe has no src URL."})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def run_js(
    script: Annotated[str, "JavaScript code to execute in the browser. Access to 'document', 'window' etc."],
    ctx: Context[ServerSession, WiesnContext],
) -> str:
    """Execute arbitrary JavaScript on the current page.

    ⚠️ EXPERT TOOL — This executes raw JavaScript. Use only when no other
    tool can accomplish the task (e.g. Livewire wire:click events, Alpine.js state).
    The script should return a value (will be JSON serialized).
    """
    page = ctx.request_context.lifespan_context.page
    # Log the script for audit trail
    logger.warning("run_js executed: %s", script[:200])
    try:
        result = await page.evaluate(script)
        return json.dumps({"status": "ok", "result": result}, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


@mcp.tool()
async def wait_for_element(
    selector: Annotated[str, "CSS selector of the element to wait for"],
    timeout: Annotated[int, "Maximum wait time in milliseconds"] = 10000,
    state: Annotated[str, "State: 'visible', 'attached', 'hidden', 'detached'"] = "visible",
    ctx: Context[ServerSession, WiesnContext] = None,  # type: ignore[assignment]
) -> str:
    """Wait until an element appears/disappears on the page.

    Essential for Livewire/Filament where DOM elements are only rendered
    after a server roundtrip (e.g. second select after date selection).
    """
    page = ctx.request_context.lifespan_context.page
    try:
        await page.wait_for_selector(selector, timeout=timeout, state=state)  # type: ignore[arg-type]
        return json.dumps({"selector": selector, "state": state, "status": "found"})
    except Exception as e:
        return json.dumps({"selector": selector, "state": state, "error": str(e)})


@mcp.tool()
async def navigate_to(
    url: Annotated[str, "URL to navigate to"],
    wait_until: Annotated[str, "Wait until: 'domcontentloaded', 'load', 'networkidle'"] = "domcontentloaded",
    ctx: Context[ServerSession, WiesnContext] = None,  # type: ignore[assignment]
) -> str:
    """Navigate to a URL and return the page title.

    Useful to navigate directly to a reservation portal without
    triggering the hash-check from check_portal.
    """
    page = ctx.request_context.lifespan_context.page
    try:
        await page.goto(url, wait_until=wait_until, timeout=ctx.request_context.lifespan_context.config.browser.timeout)  # type: ignore[arg-type]
        title = await page.title()
        current_url = page.url
        return json.dumps({"url": current_url, "title": title, "status": "ok"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"url": url, "error": str(e)})


@mcp.tool()
async def take_screenshot(
    name: Annotated[str, "Name for the screenshot (e.g. 'schottenhamel_form')"] = "screenshot",
    ctx: Context[ServerSession, WiesnContext] = None,  # type: ignore[assignment]
) -> str:
    """Take a screenshot of the current page."""
    wiesn = ctx.request_context.lifespan_context
    page = wiesn.page

    from datetime import datetime
    screenshot_dir = Path(wiesn.config.monitoring.screenshot_dir)
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = screenshot_dir / f"{name}_{ts}.png"
    await page.screenshot(path=str(filepath), full_page=True)

    await ctx.info(f"Screenshot saved: {filepath}")
    return json.dumps({"file": str(filepath), "status": "ok"})


@mcp.tool()
async def get_page_content(
    selector: Annotated[str, "CSS selector for the area (e.g. 'main', 'body', '.content')"] = "body",
    ctx: Context[ServerSession, WiesnContext] = None,  # type: ignore[assignment]
) -> str:
    """Return the text content of a page section."""
    page = ctx.request_context.lifespan_context.page
    element = await page.query_selector(selector)
    if not element:
        return json.dumps({"error": f"Element '{selector}' not found."})
    text = await element.inner_text()
    if len(text) > 5000:
        text = text[:5000] + "\n... (truncated)"
    return text


# ═══════════════════════════════════════════════════
# Tools — Monitoring
# ═══════════════════════════════════════════════════


def _select_effective_snapshot(
    old_snap: Any | None,
    new_snap: Any,
) -> tuple[Any, bool, bool]:
    """Resolve which snapshot should be used after a portal scan.

    Returns: (effective_snapshot, persist_new_snapshot, used_cached_snapshot)
    """
    has_error = bool(getattr(new_snap, "error", None))
    if has_error and old_snap is not None:
        return old_snap, False, True
    if has_error:
        return new_snap, False, False
    return new_snap, True, False


@mcp.tool()
async def monitor_availability(
    portal_name: Annotated[str, "Portal name (or 'all' for all enabled portals)"] = "all",
    check_date: Annotated[str, "Deep-scan a specific date (YYYY-MM-DD) to check time slots. Leave empty for normal scan."] = "",
    notify: Annotated[bool, "Send notification immediately when new dates found?"] = True,
    ctx: Context[ServerSession, WiesnContext] = None,  # type: ignore[assignment]
) -> str:
    """Scan portals for new reservation dates and report changes.

    Compares the current select options (date, time) with the last saved
    snapshot. When new dates are found, optionally triggers a notification.

    Use check_date to deep-scan a specific date across portals — this will
    check actual time slot availability for that date.

    This is the core feature: As soon as a tent releases new dates,
    you'll be the first to know!
    """
    from wiesn_agent.scanner import (
        compare_snapshots,
        deep_scan_date,
        filter_relevant_changes,
        load_snapshots,
        save_snapshots,
        scan_portal_availability,
    )
    from wiesn_agent.tools.notify_tools import send_notification as _send_notify
    from wiesn_agent.tools.notify_tools import should_notify_now

    wiesn = ctx.request_context.lifespan_context
    config = wiesn.config
    page = wiesn.page

    # Determine portals to scan
    if portal_name == "all":
        portale = config.enabled_portale()
    else:
        portale = [p for p in config.enabled_portale() if p.name.lower() == portal_name.lower()]
        if not portale:
            return json.dumps({"error": f"Portal '{portal_name}' not found or not enabled."})

    # Use page_lock for the entire scan to prevent concurrent page mutations
    async with wiesn.page_lock:

        # Load saved snapshots
        saved = load_snapshots()
        results = []
        new_slots_found = []

        await ctx.info(f"Scanning {len(portale)} portal(s) for new dates...")

        for portal in portale:
            await ctx.info(f"  → {portal.name}...")
            new_snap = await scan_portal_availability(page, portal, timeout=config.browser.timeout)
            old_snap = saved.get(portal.name)

            effective_snap, persist_new_snapshot, used_cached_snapshot = _select_effective_snapshot(
                old_snap, new_snap
            )
            if used_cached_snapshot:
                await ctx.info("  ⚠ Live scan failed — using last known snapshot")
                change = compare_snapshots(old_snap, old_snap)  # type: ignore[arg-type]
            else:
                change = compare_snapshots(old_snap, new_snap)

            if persist_new_snapshot:
                saved[portal.name] = new_snap

            result = {
                "portal": portal.name,
                "datum_count": len(effective_snap.datum_options),
                "dates": [d.get("value", d.get("text", "")) for d in effective_snap.datum_options],
                "portal_type": effective_snap.portal_type,
                "is_first_scan": change.is_first_scan,
                "new_dates": change.new_dates,
                "removed_dates": change.removed_dates,
                "summary": change.summary(),
                "snapshot_source": "cached" if used_cached_snapshot else ("live" if persist_new_snapshot else "live_error"),
            }

            if new_snap.error:
                result["error"] = new_snap.error
                if used_cached_snapshot:
                    result["summary"] = f"{change.summary()} | Live scan failed, using last known snapshot"

            # Deep-Scan: Check time slots for new dates
            if change.has_new and not change.is_first_scan:
                relevant = filter_relevant_changes(change, config)
                if relevant.has_new:
                    await ctx.info(f"  🔍 Deep-scan: checking time slots for {len(relevant.new_dates)} dates...")
                    deep_results = []
                    for date_info in relevant.new_dates:
                        ds = await deep_scan_date(
                            page, portal,
                            datum_value=date_info["value"],
                            datum_text=date_info["text"],
                            slots=config.reservierung.slots,
                            timeout=config.browser.timeout,
                        )
                        deep_results.append(ds)
                        await ctx.info(f"    {ds.summary()}")

                    relevant.deep_scan_results = deep_results
                    result["deep_scan"] = [
                        {"datum": ds.datum_text, "uhrzeiten": len(ds.uhrzeiten),
                         "abend_slots": [u["text"] for u in ds.abend_slots]}
                        for ds in deep_results
                    ]

                    if relevant.has_abend_slots:
                        new_slots_found.append(relevant)
                        await ctx.info("  🌙 Evening slots found!")
                    else:
                        await ctx.info("  ⚠ No evening slots — no alert")

                    if config.monitoring.screenshot_on_change:
                        from datetime import datetime as dt
                        screenshot_dir = Path(config.monitoring.screenshot_dir)
                        screenshot_dir.mkdir(parents=True, exist_ok=True)
                        ts = dt.now().strftime("%Y%m%d_%H%M%S")
                        safe_name = portal.name.replace(" ", "_").replace("/", "_")
                        fp = screenshot_dir / f"monitor_{safe_name}_{ts}.png"
                        try:
                            await page.screenshot(path=str(fp), full_page=True)
                        except Exception:
                            pass

                    try:
                        await page.goto(portal.url, timeout=config.browser.timeout)
                        await page.wait_for_timeout(2000)
                    except Exception:
                        pass

            results.append(result)

        # Save snapshots
        save_snapshots(saved)

        # ── On-demand deep-scan for a specific date ──
        if check_date:
            await ctx.info(f"Deep-scanning time slots for {check_date}...")
            for i, result in enumerate(results):
                portal = portale[i]
                snap = saved.get(portal.name)
                if not snap:
                    continue
                matching_date = None
                check_dd_mm = ""
                try:
                    from datetime import datetime as dt
                    parsed = dt.strptime(check_date, "%Y-%m-%d")
                    check_dd_mm = parsed.strftime("%d.%m.%Y")
                    check_short = f"{parsed.day}. {['Januar','Februar','März','April','Mai','Juni','Juli','August','September','Oktober','November','Dezember'][parsed.month-1]}"
                except (ValueError, IndexError):
                    check_short = ""

                for d in snap.datum_options:
                    val = d.get("value", d.get("text", ""))
                    text = d.get("text", d.get("value", ""))
                    if check_date in val or check_date in text:
                        matching_date = d
                        break
                    if check_dd_mm and (check_dd_mm in val or check_dd_mm in text):
                        matching_date = d
                        break
                    if check_short and check_short in text:
                        matching_date = d
                        break

                if matching_date:
                    await ctx.info(f"  🔍 {portal.name}: deep-scanning {matching_date.get('text', check_date)}...")
                    try:
                        await page.goto(portal.url, wait_until="domcontentloaded",
                                        timeout=config.browser.timeout)
                        await page.wait_for_timeout(3000)
                        ds = await deep_scan_date(
                            page, portal,
                            datum_value=matching_date.get("value", ""),
                            datum_text=matching_date.get("text", ""),
                            slots=config.reservierung.slots,
                            timeout=config.browser.timeout,
                        )
                        result["deep_scan"] = [
                            {"datum": ds.datum_text, "uhrzeiten": len(ds.uhrzeiten),
                             "abend_slots": [u["text"] for u in ds.abend_slots]}
                        ]
                        await ctx.info(f"    {ds.summary()}")
                    except Exception as e:
                        await ctx.info(f"    Error: {e}")

        # Send notifications
        if notify and new_slots_found and should_notify_now(config.notifications):
            for change in new_slots_found:
                title = f"🍺🌙 Evening slots: {change.portal_name}"
                body_parts = [change.portal_name, change.portal_url, ""]
                for ds in change.deep_scan_results:
                    if ds.has_abend:
                        body_parts.append(f"📅 {ds.datum_text}")
                        for u in ds.abend_slots:
                            body_parts.append(f"  🌙 {u['text']}")
                body_parts.append(f"\n→ Book now: {change.portal_url}")
                message = "\n".join(body_parts)
                await _send_notify(title=title, message=message, config=config.notifications, notify_type="success")
                await ctx.info("🔔 Notification sent")

        total_new = sum(len(r["new_dates"]) for r in results if not r["is_first_scan"])
        summary = {
            "portals_scanned": len(results),
            "total_new_dates": total_new,
            "relevant_alerts": len(new_slots_found),
            "results": results,
        }
        return json.dumps(summary, indent=2, ensure_ascii=False)


# ═══════════════════════════════════════════════════
# Tools — Notifications
# ═══════════════════════════════════════════════════


@mcp.tool()
async def send_notification(
    title: Annotated[str, "Notification title"],
    message: Annotated[str, "Message text"],
    notify_type: Annotated[str, "Type: 'info', 'success', 'warning', 'failure'"] = "info",
    event_type: Annotated[str, "Emoji category: 'evening_slot', 'reservation_update', 'success', etc."] = "info",
    ctx: Context[ServerSession, WiesnContext] = None,  # type: ignore[assignment]
) -> str:
    """Send notification to all configured services (Desktop, Telegram, Email, ntfy, etc.).

    Uses Apprise — supports 130+ services. Configured in config.yaml under notifications.apprise_urls.
    Fun emojis (🍺🌙🎪) are automatically added based on event_type when enabled.
    """
    from wiesn_agent.tools.notify_tools import send_notification as _send
    config = ctx.request_context.lifespan_context.config
    result = await _send(
        title=title, message=message, config=config.notifications,
        notify_type=notify_type, event_type=event_type,
    )
    await ctx.info(f"Notification sent: {title}")
    return result


# ═══════════════════════════════════════════════════
# Prompts — Pre-built workflows
# ═══════════════════════════════════════════════════


@mcp.prompt(title="Check all portals")
def prompt_check_all() -> str:
    """Standard workflow: Check all configured portals and notify on changes."""
    return (
        "Check all configured Oktoberfest booking portals for changes. "
        "Use the 'check_all_portals' tool. "
        "If a portal has changed, check if a reservation form exists (detect_forms). "
        "If so, fill it with user data (fill_reservation_form) and take a screenshot. "
        "Send a summary notification at the end. "
        "IMPORTANT: Do NOT submit any form — human confirmation required."
    )


@mcp.prompt(title="Monitor availability")
def prompt_monitor() -> str:
    """Scan portals for new reservation dates and notify on changes."""
    return (
        "Start availability monitoring: Use 'monitor_availability' to scan all "
        "enabled portals for new reservation dates. "
        "The tool automatically compares with the last scan and reports new dates.\n\n"
        "On new dates:\n"
        "1. Desktop notification is sent automatically\n"
        "2. Show me a summary of all changes\n"
        "3. For the most relevant new dates: navigate to the portal, "
        "   detect the form (detect_forms), and pre-fill it (fill_reservation_form)\n"
        "4. Take a screenshot of the pre-filled form\n\n"
        "IMPORTANT: Do NOT submit any form — only pre-fill and screenshot!"
    )


@mcp.prompt(title="Check single portal")
def prompt_check_single(portal_url: str, portal_name: str = "Unknown") -> str:
    """Check a single portal and fill form if found."""
    return (
        f"Check the booking portal '{portal_name}' at {portal_url}. "
        "Navigate there (check_portal), look for forms (detect_forms). "
        "If a reservation form exists, fill it with user data (fill_reservation_form). "
        "Take screenshots before and after. "
        "IMPORTANT: Do NOT submit the form!"
    )


@mcp.prompt(title="FestZelt OS Wizard")
def prompt_festzelt_wizard(portal_url: str, portal_name: str = "Festzelt") -> str:
    """Workflow for FestZelt-OS-based portals (multi-step wizard)."""
    return (
        f"Navigate to portal '{portal_name}' ({portal_url}). "
        "This portal uses FestZelt OS (Filament/Livewire). Here's how to proceed:\n\n"
        "**Step 1 — Date selection:**\n"
        "1. navigate_to the portal\n"
        "2. detect_forms → Detect wizard and selects\n"
        "3. select_option for Date (Index '0'), then wait_for_element for next select\n"
        "4. select_option for Shift (Index '1'), wait_for_element\n"
        "5. select_option for Area (Index '2'), wait_for_element\n"
        "6. select_option for Persons (Index '3')\n"
        "7. click_element on 'button:has-text(\"Next\")'\n\n"
        "**Step 2 — Consumption selection:**\n"
        "8. detect_forms → Find radio buttons\n"
        "9. click_element with force=True on the radio input (sr-only)\n"
        "10. click_element on Next\n\n"
        "**Step 3 — Personal data:**\n"
        "11. detect_forms → Find all text fields\n"
        "12. fill_reservation_form → Automatically fill user data\n"
        "13. take_screenshot → Document the result\n\n"
        "IMPORTANT: Wait 2-3 seconds after each select_option (Livewire server roundtrip). "
        "DO NOT SUBMIT THE FORM!"
    )


# ═══════════════════════════════════════════════════
# Entrypoint
# ═══════════════════════════════════════════════════

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Wiesn-Agent MCP Server")
    parser.add_argument("--http", action="store_true", help="Streamable HTTP instead of stdio")
    parser.add_argument("--port", type=int, default=8080, help="HTTP port (default: 8080)")
    args = parser.parse_args()

    if args.http:
        mcp.run(transport="streamable-http", host="0.0.0.0", port=args.port)  # type: ignore[call-arg]
    else:
        mcp.run()


if __name__ == "__main__":
    main()
