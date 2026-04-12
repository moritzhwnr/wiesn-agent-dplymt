"""Notification tools — Apprise-based (133+ services) + BotBell push.

Supported services include:
  - ntfy://wiesn-alert           → Mobile push (free, no account needed)
  - tgram://{token}/{chat_id}    → Telegram Bot
  - mailto://user:pass@gmail.com → Email
  - slack://{tokenA}/{B}/{C}     → Slack
  - discord://{id}/{token}       → Discord
  - whatsapp://{token}@{phone}/{target} → WhatsApp Business
  - json://hostname/path         → Custom Webhook
  - BotBell (botbell_token)      → iPhone/iPad/Mac push notifications

Full list: https://github.com/caronc/apprise/wiki
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import subprocess
import sys
from typing import Any

import apprise

from wiesn_agent.config_model import NotificationConfig

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════
# Emoji templates — central mapping by event type
# ═══════════════════════════════════════════════════

EMOJI_MAP: dict[str, str] = {
    "reservation_update": "🍺",
    "evening_slot": "🍺🌙",
    "morning_slot": "🍺☀️",
    "afternoon_slot": "🍺🌤️",
    "new_portal": "🎪",
    "success": "✅",
    "warning": "⚠️",
    "failure": "🚨",
    "info": "📋",
    "form_filled": "🍺📝",
    "quiet_hours": "🌙💤",
}


def format_title(event_type: str, text: str, use_emojis: bool = True) -> str:
    """Format a notification title with optional emoji prefix."""
    if not use_emojis:
        return text
    emoji = EMOJI_MAP.get(event_type, EMOJI_MAP.get("info", ""))
    return f"{emoji} {text}" if emoji else text


# ═══════════════════════════════════════════════════
# Apprise-based notifications
# ═══════════════════════════════════════════════════

_apprise_instance: apprise.Apprise | None = None
_apprise_urls_hash: str = ""


def _urls_hash(urls: list[str]) -> str:
    """Hash of configured URLs to detect config changes."""
    return hashlib.md5("|".join(sorted(urls)).encode()).hexdigest()


def get_apprise(config: NotificationConfig) -> apprise.Apprise:
    """Create or return the cached Apprise instance (rebuilds on config change)."""
    global _apprise_instance, _apprise_urls_hash

    current_hash = _urls_hash(config.apprise_urls)
    if _apprise_instance is not None and current_hash == _apprise_urls_hash:
        return _apprise_instance

    ap = apprise.Apprise()
    for url in config.apprise_urls:
        ap.add(url)
        logger.info("Apprise service added: %s://...", url.split("://")[0])

    _apprise_instance = ap
    _apprise_urls_hash = current_hash
    return ap


def reset_apprise() -> None:
    """Reset the cached instance (e.g. after config reload)."""
    global _apprise_instance, _apprise_urls_hash
    _apprise_instance = None
    _apprise_urls_hash = ""


# ═══════════════════════════════════════════════════
# Desktop notifications (cross-platform)
# ═══════════════════════════════════════════════════

def _sanitize_notification_text(s: str) -> str:
    """Sanitize text for desktop notifications — remove control chars."""
    return s.replace("\\", "").replace('"', "'").replace("\n", " ").replace("\r", "")[:200]


def _send_desktop(title: str, message: str) -> bool:
    """Send a native desktop notification. Returns True on success."""
    safe_title = _sanitize_notification_text(title[:100])
    safe_msg = _sanitize_notification_text(message)

    try:
        if sys.platform == "darwin":
            subprocess.run(
                ["osascript", "-e",
                 f'display notification "{safe_msg}" with title "{safe_title}"'],
                check=True, timeout=5,
            )
        elif sys.platform == "win32":
            # PowerShell toast notification (Windows 10+)
            ps_title = safe_title.replace("'", "''")
            ps_msg = safe_msg.replace("'", "''")
            ps_script = (
                "[Windows.UI.Notifications.ToastNotificationManager,"
                " Windows.UI.Notifications, ContentType = WindowsRuntime] > $null; "
                "$xml = [Windows.UI.Notifications.ToastNotificationManager]"
                "::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]"
                "::ToastText02); "
                "$nodes = $xml.GetElementsByTagName('text'); "
                f"$nodes.Item(0).AppendChild($xml.CreateTextNode('{ps_title}')) > $null; "
                f"$nodes.Item(1).AppendChild($xml.CreateTextNode('{ps_msg}')) > $null; "
                "$toast = [Windows.UI.Notifications.ToastNotification]::new($xml); "
                "[Windows.UI.Notifications.ToastNotificationManager]"
                "::CreateToastNotifier('Wiesn-Agent').Show($toast)"
            )
            subprocess.run(
                ["powershell", "-Command", ps_script],
                check=True, timeout=10,
            )
        else:
            subprocess.run(
                ["notify-send", safe_title, safe_msg],
                check=True, timeout=5,
            )
        return True
    except Exception as e:
        logger.warning("Desktop notification failed: %s", e)
        return False


# ═══════════════════════════════════════════════════
# Main notification sender
# ═══════════════════════════════════════════════════

async def send_notification(
    title: str,
    message: str,
    config: NotificationConfig | None = None,
    notify_type: str = "info",
    event_type: str = "",
    **kwargs: Any,
) -> str:
    """Send a notification to all configured services.

    Returns JSON with status: "sent" | "partial" | "failed" | "skipped" | "error"
    notify_type: "info", "success", "warning", "failure" (Apprise severity)
    event_type: optional key for emoji lookup (e.g. "evening_slot", "form_filled")
    """
    if not config:
        return json.dumps({"status": "error", "error": "No notification config provided."})

    # Apply emoji formatting if enabled
    use_emojis = getattr(config, "use_emojis", True)
    if event_type and use_emojis:
        title = format_title(event_type, title, use_emojis=True)

    success_count = 0
    failure_count = 0
    results = []

    # 1. Desktop notification (cross-platform)
    if config.desktop:
        ok = await asyncio.to_thread(_send_desktop, title, message)
        if ok:
            results.append("desktop:ok")
            success_count += 1
        else:
            results.append("desktop:failed")
            failure_count += 1

    # 2. Apprise services (ntfy, Telegram, Email, etc.)
    ap = get_apprise(config)
    if len(ap) > 0:
        type_map = {
            "info": apprise.NotifyType.INFO,
            "success": apprise.NotifyType.SUCCESS,
            "warning": apprise.NotifyType.WARNING,
            "failure": apprise.NotifyType.FAILURE,
        }
        try:
            ok = await asyncio.to_thread(
                ap.notify,
                title=title,
                body=message,
                notify_type=type_map.get(notify_type, apprise.NotifyType.INFO),
            )
            if ok:
                results.append(f"apprise:{len(ap)}services:ok")
                success_count += 1
            else:
                results.append(f"apprise:{len(ap)}services:partial_fail")
                failure_count += 1
        except Exception as e:
            results.append(f"apprise:error:{e}")
            failure_count += 1

    # 3. BotBell push (iPhone/iPad/Mac) — non-blocking
    if config.botbell_token:
        try:
            from botbell import BotBell

            bb = BotBell(config.botbell_token)
            await asyncio.to_thread(
                bb.send,
                message=message[:4096],
                title=title[:256],
            )
            results.append("botbell:ok")
            success_count += 1
        except Exception as e:
            results.append(f"botbell:error:{e}")
            failure_count += 1

    if not results:
        return json.dumps({"status": "skipped", "reason": "No services configured."})

    # Determine accurate overall status
    if failure_count == 0:
        status = "sent"
    elif success_count > 0:
        status = "partial"
    else:
        status = "failed"

    total_services = success_count + failure_count
    logger.info("Notification [%s]: %s → %s (%s)", notify_type, title, status, results)
    return json.dumps({
        "status": status,
        "title": title,
        "services": total_services,
        "success_count": success_count,
        "failure_count": failure_count,
        "details": results,
    })


# Legacy-compatible wrappers

async def send_desktop_notification(title: str, message: str, **kwargs: Any) -> str:
    """Desktop notification (legacy-compatible, now uses unified sender)."""
    config = kwargs.get("config") or kwargs.get("notification_config")
    if config:
        return await send_notification(title, message, config=config)

    ok = await asyncio.to_thread(_send_desktop, title, message)
    if ok:
        return json.dumps({"status": "sent", "title": title})
    return json.dumps({"status": "failed", "error": "Desktop notification failed"})


async def send_email(title: str, message: str, email_config: Any = None, **kwargs: Any) -> str:
    """Email (legacy wrapper). Use apprise_urls with mailto:// URL instead."""
    logger.warning("send_email() is deprecated. Use apprise_urls with 'mailtos://...' instead.")
    return json.dumps({"status": "skipped", "reason": "Use apprise_urls with mailto:// instead"})


async def send_webhook(payload: str, **kwargs: Any) -> str:
    """Webhook (legacy wrapper). Use apprise_urls with json:// URL instead."""
    logger.warning("send_webhook() is deprecated. Use apprise_urls with 'json://...' instead.")
    return json.dumps({"status": "skipped", "reason": "Use apprise_urls with json:// instead"})


# ═══════════════════════════════════════════════════
# Time filters
# ═══════════════════════════════════════════════════

VALID_DAYS = {"Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"}


def should_notify_now(config: NotificationConfig) -> bool:
    """Check whether notifications are currently allowed (quiet hours + day filter)."""
    from datetime import datetime

    now = datetime.now()

    # Day filter
    if config.nur_an_tagen:
        tag_map = {"Mo": 0, "Di": 1, "Mi": 2, "Do": 3, "Fr": 4, "Sa": 5, "So": 6}
        erlaubte_tage = {tag_map.get(t, -1) for t in config.nur_an_tagen}
        if now.weekday() not in erlaubte_tage:
            return False

    # Quiet hours
    von = datetime.strptime(config.stille_zeit.von, "%H:%M").time()
    bis = datetime.strptime(config.stille_zeit.bis, "%H:%M").time()
    jetzt = now.time()

    if von > bis:  # e.g. 22:00 - 08:00 (over midnight)
        if jetzt >= von or jetzt < bis:
            return False
    else:
        if von <= jetzt <= bis:
            return False

    return True
