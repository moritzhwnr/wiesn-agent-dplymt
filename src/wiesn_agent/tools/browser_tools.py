"""Browser tools for Playwright — navigation, scraping, form filling.

Tools accept an optional ``page`` keyword argument (injected via ``bind_tools``
in workflow mode, or via ``**kwargs`` for backwards compatibility).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Helper: resolve page from kwargs
# ─────────────────────────────────────────────

def _get_page(kwargs: dict[str, Any]) -> Any | None:
    """Extract the Playwright page from kwargs (supports both explicit and bound)."""
    return kwargs.get("page")


# ─────────────────────────────────────────────
# Tool functions for agents
# ─────────────────────────────────────────────

async def navigate(
    url: Annotated[str, Field(description="The URL to open.")],
    **kwargs: Any,
) -> str:
    """Navigate the browser to a URL and return the page title."""
    page = kwargs.get("page")
    if not page:
        return "Error: No browser page provided."
    await page.goto(url, wait_until="domcontentloaded")
    title = await page.title()
    return json.dumps({"url": url, "title": title, "status": "ok"})


async def get_page_content(
    selector: Annotated[str, Field(description="CSS selector for the section, e.g. 'main' or 'body'.")] = "body",
    **kwargs: Any,
) -> str:
    """Return the text content of a page section."""
    page = kwargs.get("page")
    if not page:
        return "Error: No browser page provided."
    element = await page.query_selector(selector)
    if not element:
        return f"Element '{selector}' not found."
    text = await element.inner_text()
    if len(text) > 5000:
        text = text[:5000] + "\n... (truncated)"
    return text


async def detect_forms(
    **kwargs: Any,
) -> str:
    """Detect all forms on the page and return their fields."""
    page = kwargs.get("page")
    if not page:
        return "Error: No browser page provided."

    forms = await page.evaluate("""() => {
        const results = [];
        document.querySelectorAll('form').forEach((form, fi) => {
            const fields = [];
            form.querySelectorAll('input, select, textarea').forEach(el => {
                fields.push({
                    tag: el.tagName.toLowerCase(),
                    type: el.type || '',
                    name: el.name || '',
                    id: el.id || '',
                    placeholder: el.placeholder || '',
                    required: el.required,
                    options: el.tagName === 'SELECT'
                        ? [...el.options].map(o => ({value: o.value, text: o.text}))
                        : undefined
                });
            });
            results.push({
                index: fi,
                action: form.action || '',
                method: form.method || 'get',
                fields: fields
            });
        });
        return results;
    }""")

    if not forms:
        return json.dumps({"forms": [], "message": "No forms found."})
    return json.dumps({"forms": forms, "count": len(forms)})


async def fill_field(
    selector: Annotated[str, Field(description="CSS selector of the input field.")],
    value: Annotated[str, Field(description="The value to enter.")],
    **kwargs: Any,
) -> str:
    """Fill a form field."""
    page = kwargs.get("page")
    if not page:
        return "Error: No browser page provided."
    try:
        await page.fill(selector, value)
        return json.dumps({"selector": selector, "value": value, "status": "ok"})
    except Exception as e:
        return json.dumps({"selector": selector, "error": str(e)})


async def select_option(
    selector: Annotated[str, Field(description="CSS selector of the select element.")],
    value: Annotated[str, Field(description="The value to select.")],
    **kwargs: Any,
) -> str:
    """Select an option in a dropdown menu."""
    page = kwargs.get("page")
    if not page:
        return "Error: No browser page provided."
    try:
        await page.select_option(selector, value)
        return json.dumps({"selector": selector, "value": value, "status": "ok"})
    except Exception as e:
        return json.dumps({"selector": selector, "error": str(e)})


async def click_button(
    selector: Annotated[str, Field(description="CSS selector of the button.")],
    **kwargs: Any,
) -> str:
    """Click a button or link."""
    page = kwargs.get("page")
    if not page:
        return "Error: No browser page provided."
    try:
        await page.click(selector)
        return json.dumps({"selector": selector, "status": "clicked"})
    except Exception as e:
        return json.dumps({"selector": selector, "error": str(e)})


async def wait_for_element(
    selector: Annotated[str, Field(description="CSS selector of the element to wait for.")],
    timeout: Annotated[int, Field(description="Timeout in milliseconds (default: 10000).")] = 10000,
    **kwargs: Any,
) -> str:
    """Wait until an element becomes visible on the page."""
    page = kwargs.get("page")
    if not page:
        return "Error: No browser page provided."
    try:
        await page.wait_for_selector(selector, timeout=timeout)
        return json.dumps({"selector": selector, "status": "visible"})
    except Exception as e:
        return json.dumps({"selector": selector, "error": str(e)})


async def run_js(
    script: Annotated[str, Field(description="JavaScript code to execute in the browser.")],
    **kwargs: Any,
) -> str:
    """Execute JavaScript in the browser and return the result.

    Useful for Livewire/Alpine.js interactions:
    - Set element values: document.getElementById('id').value = 'x'
    - Dispatch events: el.dispatchEvent(new Event('change', {bubbles: true}))
    - Livewire: wait ~2.5s after select change for server roundtrip
    """
    page = kwargs.get("page")
    if not page:
        return "Error: No browser page provided."
    try:
        result = await page.evaluate(script)
        return json.dumps({"status": "ok", "result": result})
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


async def switch_to_iframe(
    selector: Annotated[str, Field(description="CSS selector of the iframe element.")],
    **kwargs: Any,
) -> str:
    """Switch into an iframe (e.g. for Käfer, Festzelt Tradition).

    After switching, the bound 'page' is replaced with the iframe's content
    frame so subsequent tool calls target the iframe content.

    Note: This only works in workflow mode (with bind_tools). In MCP mode,
    use the MCP switch_to_iframe tool which handles page swapping via WiesnContext.
    """
    page = kwargs.get("page")
    if not page:
        return "Error: No browser page provided."
    try:
        frame_element = await page.wait_for_selector(selector, timeout=10000)
        frame = await frame_element.content_frame()
        if not frame:
            return json.dumps({"status": "error", "error": "No frame content found."})
        # Navigate to the iframe URL in the current page so subsequent
        # tool calls operate on the iframe content
        iframe_url = await frame_element.get_attribute("src")
        if iframe_url:
            await page.goto(iframe_url, wait_until="domcontentloaded")
            return json.dumps({
                "selector": selector,
                "status": "switched_to_iframe",
                "frame_url": iframe_url,
            })
        return json.dumps({"status": "error", "error": "iframe has no src URL."})
    except Exception as e:
        return json.dumps({"selector": selector, "error": str(e)})


async def take_screenshot(
    name: Annotated[str, Field(description="Name for the screenshot (without path/extension).")],
    screenshot_dir: str = "./screenshots",
    **kwargs: Any,
) -> str:
    """Take a screenshot of the current page."""
    page = kwargs.get("page")
    if not page:
        return "Error: No browser page provided."

    path = Path(screenshot_dir)
    path.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = path / f"{name}_{ts}.png"

    await page.screenshot(path=str(filename), full_page=True)
    return json.dumps({"file": str(filename), "status": "ok"})


# ─────────────────────────────────────────────
# Helper functions (not exposed as agent tools)
# ─────────────────────────────────────────────

async def get_page_hash(page: Any) -> str:
    """Compute a hash of the visible page content for change detection."""
    content = await page.evaluate("() => document.body.innerText")
    return hashlib.sha256(content.encode()).hexdigest()


async def check_portal_changed(
    page: Any,
    previous_hash: str | None,
) -> tuple[bool, str]:
    """Check whether a portal page has changed.

    Returns:
        (has_changed, new_hash)
    """
    current_hash = await get_page_hash(page)
    changed = previous_hash is not None and current_hash != previous_hash
    return changed, current_hash
