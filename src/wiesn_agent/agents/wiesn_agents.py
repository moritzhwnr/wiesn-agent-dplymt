"""Wiesn-Agents — Monitor, Analyzer, Filler, Notifier."""

from __future__ import annotations

from typing import Any

from agent_framework import Agent
from agent_framework.openai import OpenAIChatCompletionClient

from wiesn_agent.tools import bind_tools
from wiesn_agent.tools.browser_tools import (
    click_button,
    detect_forms,
    fill_field,
    get_page_content,
    navigate,
    run_js,
    select_option,
    switch_to_iframe,
    take_screenshot,
    wait_for_element,
)
from wiesn_agent.tools.notify_tools import send_notification

# Portal types and their quirks (from scan results)
PORTAL_TYPE_HINTS = """
Portal architecture types:
1. LIVEWIRE (Filament PHP) — Löwenbräu, Fischer-Vroni, Schützen, Schützenlisl, Boandlkramerei:
   - Select fields: set .value + dispatch input/change events (bubbles: true)
   - Progressive reveal: Wait ~2.5s after select for Livewire roundtrip
   - Wizard steps: .fi-fo-wizard, .fi-fo-select, .fi-btn
   - IDs with dots: use getElementById() instead of CSS selectors

2. RATSKELLER — Festzelt Tradition:
   - External iframe (ratskeller.com), switch_to_iframe required first
   - Custom form system

3. WORDPRESS — Hacker-Festzelt, Schottenhamel, Ochsenbraterei:
   - Usually Contact Form 7 or Gravity Forms
   - Standard HTML forms

4. IFRAME-EMBED — Käfer:
   - Reservation in embedded iframe
   - switch_to_iframe required first

5. STANDARD — Armbrustschützenzelt, Augustiner, Paulaner, etc.:
   - Custom booking systems
   - Usually standard HTML forms
"""


def create_monitor_agent(client: OpenAIChatCompletionClient, page: Any = None) -> Agent:
    """Monitor booking portals for changes."""
    tools = [navigate, get_page_content, detect_forms, take_screenshot,
             wait_for_element, run_js, switch_to_iframe]
    if page is not None:
        tools = bind_tools(tools, page=page)
    return Agent(
        name="Monitor",
        client=client,
        instructions=f"""You are the Monitor agent for Oktoberfest reservation portals.

{PORTAL_TYPE_HINTS}

Your task:
1. Navigate to the given portal URL
2. Read the page content
3. Check if reservation forms or booking options are available
4. For iframes (Käfer, Festzelt Tradition): use switch_to_iframe
5. For Livewire portals: detect_forms shows the dynamic fields
6. Report the current page status

Always respond as JSON with this structure:
{{
    "portal": "<Name>",
    "url": "<URL>",
    "status": "open" | "closed" | "error",
    "portal_type": "livewire" | "ratskeller" | "wordpress" | "iframe" | "standard",
    "has_form": true/false,
    "available_dates": ["<Date>", ...],
    "summary": "<Brief description of what's visible>",
    "change_detected": true/false
}}""",
        tools=tools,
    )


def create_analyzer_agent(client: OpenAIChatCompletionClient, page: Any = None) -> Agent:
    """Analyze found forms and plan the fill strategy."""
    tools = [detect_forms, get_page_content, run_js, wait_for_element]
    if page is not None:
        tools = bind_tools(tools, page=page)
    return Agent(
        name="Analyzer",
        client=client,
        instructions=f"""You are the Analyzer agent for Oktoberfest reservation forms.

{PORTAL_TYPE_HINTS}

You receive information about a reservation portal and detected forms.

Your task:
1. Analyze the form fields and portal type
2. Map each field to the appropriate user data
3. For LIVEWIRE portals: Plan the correct event-dispatch order
4. For IFRAME portals: Ensure switch_to_iframe is in the plan
5. Check if preferred dates and time slots are available
6. Create a fill plan with the correct order

Always respond as JSON with this structure:
{{
    "portal": "<Name>",
    "portal_type": "livewire" | "ratskeller" | "wordpress" | "iframe" | "standard",
    "form_found": true/false,
    "fill_plan": [
        {{"selector": "<CSS>", "action": "fill"|"select"|"click"|"js"|"wait"|"iframe", "value": "<Value>", "field": "<Description>", "wait_after": 0}}
    ],
    "available_slots": ["morning", "afternoon", "evening"],
    "recommendation": "<What the agent recommends>"
}}

IMPORTANT for Livewire: Always set wait_after: 2500 after each select_option!""",
        tools=tools,
    )


def create_filler_agent(client: OpenAIChatCompletionClient, page: Any = None) -> Agent:
    """Fill reservation forms. NEVER submits — human-in-the-loop required."""
    tools = [fill_field, select_option, click_button, take_screenshot,
             get_page_content, run_js, wait_for_element, switch_to_iframe]
    if page is not None:
        tools = bind_tools(tools, page=page)
    return Agent(
        name="Filler",
        client=client,
        instructions=f"""You are the Form Filler agent for Oktoberfest reservations.

{PORTAL_TYPE_HINTS}

You receive a fill plan from the Analyzer agent.

Your task:
1. Fill each field according to the plan
2. For Livewire: Use run_js to dispatch events
3. For progressive reveal: wait_for_element after each step
4. Do a brief check after each filled field
5. DO NOT SUBMIT THE FORM — stop before the submit button
6. Take a screenshot of the filled form

Livewire selects — correct approach:
```js
const el = document.getElementById('field-id');
el.value = 'new-value';
el.dispatchEvent(new Event('input', {{bubbles: true}}));
el.dispatchEvent(new Event('change', {{bubbles: true}}));
```
Then wait 2.5s for the Livewire roundtrip!

Always respond as JSON:
{{
    "portal": "<Name>",
    "fields_filled": <count>,
    "status": "ready_for_review" | "error" | "incomplete",
    "screenshot": "<Path>",
    "problems": ["<Problem 1>", ...]
}}

=== HUMAN-IN-THE-LOOP ===
CRITICAL: NEVER click Submit/Send/Book. The form must be reviewed and
submitted MANUALLY by the user. Your job ends at filling + screenshot.
If you detect a submit button, report its selector but DO NOT click it.""",
        tools=tools,
    )


def create_notifier_agent(
    client: OpenAIChatCompletionClient,
    notification_config: Any = None,
) -> Agent:
    """Notify the user about available slots."""
    tools = [send_notification]
    if notification_config is not None:
        tools = bind_tools(tools, config=notification_config)
    return Agent(
        name="Notifier",
        client=client,
        instructions="""You are the Notification agent.

You receive analysis results about available reservation slots.

Your task:
1. Summarize what slots are available (dates, times, portal)
2. Send a notification via all configured channels (Desktop, ntfy, Telegram, etc.)
3. The user will then decide whether to proceed with form filling

Keep messages short and informative.
Example: "Schottenhamel: Evening slot 26.09. 18:00 available! Reply to fill the form."
""",
        tools=tools,
    )
