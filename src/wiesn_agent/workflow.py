"""Wiesn-Agent Workflow — Graph-based agent workflow with DevUI support."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any, Callable

from agent_framework import (
    Case,
    Default,
    Executor,
    WorkflowBuilder,
    WorkflowContext,
    handler,
)

from wiesn_agent.agents.wiesn_agents import (
    create_analyzer_agent,
    create_filler_agent,
    create_monitor_agent,
)
from wiesn_agent.client import create_client
from wiesn_agent.config_model import WiesnConfig
from wiesn_agent.tools.browser_tools import check_portal_changed
from wiesn_agent.tools.notify_tools import send_notification as send_notification_direct
from wiesn_agent.tools.notify_tools import should_notify_now

logger = logging.getLogger(__name__)


# ── HITL approval strategies ─────────────────────

async def _stdin_approval(portal: str, analysis: str) -> bool:
    """Ask for approval via stdin (CLI mode)."""
    print(f"\n{'='*60}")
    print(f"🍺 Reservation slots found: {portal}")
    print(f"{'─'*60}")
    print(analysis[:500] if analysis else "(no details)")
    print(f"{'─'*60}")
    print("Do you want to pre-fill the form? (y/N): ", end="", flush=True)

    loop = asyncio.get_event_loop()
    try:
        answer = await asyncio.wait_for(
            loop.run_in_executor(None, sys.stdin.readline),
            timeout=120,
        )
        return answer.strip().lower() in ("y", "yes", "ja", "j")
    except asyncio.TimeoutError:
        print("\n⏱ Timeout — skipping form fill.")
        return False


# Type for approval callback: async (portal, analysis) -> bool
ApprovalCallback = Callable[[str, str], Any]


class MonitorExecutor(Executor):
    """Monitor all portals and forward changes."""

    def __init__(self, config: WiesnConfig, browser_page: Any, portal_hashes: dict[str, str]):
        super().__init__(id="monitor")
        self.config = config
        self.page = browser_page
        self.portal_hashes = portal_hashes

    @handler
    async def check_portals(self, _input: str, ctx: WorkflowContext[str]) -> None:
        client = create_client()
        monitor_agent = create_monitor_agent(client, page=self.page)

        for portal in self.config.enabled_portale():
            logger.info("Checking portal: %s (%s)", portal.name, portal.url)

            try:
                # Load page and check hash
                await self.page.goto(portal.url, wait_until="domcontentloaded", timeout=self.config.browser.timeout)

                old_hash = self.portal_hashes.get(portal.name)
                changed, new_hash = await check_portal_changed(self.page, old_hash)
                self.portal_hashes[portal.name] = new_hash

                if old_hash is None:
                    logger.info("First check for %s — baseline set (skipping analysis).", portal.name)
                    # First run: establish baseline only, do not trigger analysis/fill
                    await ctx.send_message(json.dumps({
                        "portal": portal.name,
                        "url": portal.url,
                        "changed": False,
                        "baseline_set": True,
                        "monitor_result": "Baseline established on first check.",
                    }))
                    continue

                # Agent analysiert die Seite
                slots_info = ", ".join(
                    f"{name} ({s.von}-{s.bis})"
                    for name, s in self.config.enabled_slots()
                )
                prompt = (
                    f"Check portal '{portal.name}' at {portal.url}. "
                    f"Preferred dates: {', '.join(self.config.reservierung.wunsch_tage)}. "
                    f"Preferred slots: {slots_info}. "
                    f"Page has {'changed' if changed else 'not changed'}."
                )
                result = await monitor_agent.run(prompt)

                await ctx.send_message(json.dumps({
                    "portal": portal.name,
                    "url": portal.url,
                    "changed": changed,
                    "monitor_result": str(result),
                }))

            except Exception as e:
                logger.error("Error checking portal %s: %s", portal.name, e)
                await ctx.send_message(json.dumps({
                    "portal": portal.name,
                    "url": portal.url,
                    "changed": False,
                    "error": str(e),
                }))


class AnalyzeExecutor(Executor):
    """Analyze portals with changes and create fill plans."""

    def __init__(self, config: WiesnConfig, browser_page: Any):
        super().__init__(id="analyzer")
        self.config = config
        self.page = browser_page

    @handler
    async def analyze(self, monitor_result: str, ctx: WorkflowContext[str]) -> None:
        try:
            data = json.loads(monitor_result)
        except json.JSONDecodeError:
            logger.warning("Invalid monitor result: %s", monitor_result)
            return

        if data.get("error") or not data.get("changed", False):
            logger.info("Portal %s: No analysis needed.", data.get("portal", "?"))
            return

        client = create_client()
        analyzer = create_analyzer_agent(client, page=self.page)

        user = self.config.user
        prompt = (
            f"Analyze portal '{data['portal']}' ({data['url']}). "
            f"Monitor result: {data.get('monitor_result', 'N/A')}. "
            f"User data: First name={user.vorname}, Last name={user.nachname}, "
            f"Email={user.email}, Phone={user.telefon}, Persons={user.personen}. "
            f"Notes: {user.notizen}"
        )
        result = await analyzer.run(prompt)

        await ctx.send_message(json.dumps({
            "portal": data["portal"],
            "url": data["url"],
            "analyze_result": str(result),
        }))


class FillExecutor(Executor):
    """Fill forms according to the analysis plan. Requires human confirmation before submit."""

    def __init__(self, config: WiesnConfig, browser_page: Any):
        super().__init__(id="filler")
        self.config = config
        self.page = browser_page

    @handler
    async def fill(self, notify_result: str, ctx: WorkflowContext[str]) -> None:
        try:
            data = json.loads(notify_result)
        except json.JSONDecodeError:
            return

        client = create_client()
        filler = create_filler_agent(client, page=self.page)

        prompt = (
            f"Fill the form on portal '{data['portal']}' ({data['url']}). "
            f"Analysis result: {data.get('analyze_result', 'N/A')}. "
            f"Screenshot directory: {self.config.monitoring.screenshot_dir}. "
            f"IMPORTANT: Do NOT submit the form. Stop before clicking submit. "
            f"The user must confirm before submission (human-in-the-loop)."
        )
        result = await filler.run(prompt)

        await ctx.send_message(json.dumps({
            "portal": data["portal"],
            "fill_result": str(result),
        }))


class NotifyExecutor(Executor):
    """Notify the user about available slots and ask whether to fill."""

    def __init__(self, config: WiesnConfig, approval_fn: ApprovalCallback | None = None):
        super().__init__(id="notifier")
        self.config = config
        self._approval_fn = approval_fn or _stdin_approval

    @handler
    async def notify(self, analyze_result: str, ctx: WorkflowContext[str]) -> None:
        try:
            data = json.loads(analyze_result)
        except json.JSONDecodeError:
            logger.warning("Invalid analyze result, skipping notification.")
            return

        portal = data.get("portal", "Unknown")
        analysis = data.get("analyze_result", "")

        if not should_notify_now(self.config.notifications):
            # Quiet hours: queue the event, do NOT auto-approve
            logger.info(
                "Quiet hours — queuing notification for %s (form fill NOT approved).",
                portal,
            )
            await ctx.send_message(json.dumps({
                **data,
                "user_approved": False,
                "reason": "quiet_hours",
            }))
            return

        # Deterministic notification — no LLM needed for structured alerts
        title = f"Reservation update: {portal}"
        message = f"{portal}\n{analysis[:500]}"
        await send_notification_direct(
            title=title,
            message=message,
            config=self.config.notifications,
            notify_type="success",
            event_type="reservation_update",
        )

        # Human-in-the-loop: ask user for approval via configured callback
        logger.info("Asking user for approval to fill form for %s...", portal)
        try:
            user_approved = await self._approval_fn(portal, analysis)
        except Exception as e:
            logger.warning("Approval callback failed for %s: %s", portal, e)
            user_approved = False

        if user_approved:
            logger.info("User APPROVED form fill for %s.", portal)
        else:
            logger.info("User DECLINED form fill for %s.", portal)

        await ctx.send_message(json.dumps({
            **data,
            "user_approved": user_approved,
            "reason": "user_response",
        }))


def _user_approved(message: str) -> bool:
    """Condition: route to Filler only if user approved."""
    try:
        data = json.loads(message)
        return data.get("user_approved", False) is True
    except (json.JSONDecodeError, TypeError):
        return False


class TerminalExecutor(Executor):
    """Terminal node — ends the workflow run cleanly."""

    def __init__(self):
        super().__init__(id="terminal")

    @handler
    async def done(self, message: str, ctx: WorkflowContext[str]) -> None:
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            data = {}
        reason = data.get("reason", "declined")
        portal = data.get("portal", "unknown")
        logger.info("Workflow terminated for %s (reason: %s)", portal, reason)


def build_workflow(
    config: WiesnConfig,
    browser_page: Any,
    portal_hashes: dict[str, str] | None = None,
    approval_fn: ApprovalCallback | None = None,
):
    """Build the Wiesn-Agent workflow graph.

    Monitor → Analyzer → Notifier → [approved?] → Filler
                                   → [declined?] → Terminal (end run)

    Args:
        approval_fn: Async callback (portal, analysis) -> bool for HITL.
                     Defaults to stdin prompt. Pass a custom callback for
                     web/API approval flows.
    """
    if portal_hashes is None:
        portal_hashes = {}

    monitor = MonitorExecutor(config, browser_page, portal_hashes)
    analyzer = AnalyzeExecutor(config, browser_page)
    filler = FillExecutor(config, browser_page)
    notifier = NotifyExecutor(config, approval_fn=approval_fn)
    terminal = TerminalExecutor()

    workflow = (
        WorkflowBuilder(start_executor=monitor)
        .add_edge(monitor, analyzer)
        .add_edge(analyzer, notifier)
        .add_switch_case_edge_group(notifier, [
            Case(condition=_user_approved, target=filler),
            Default(target=terminal),  # End workflow run if not approved
        ])
        .build()
    )

    return workflow, portal_hashes
