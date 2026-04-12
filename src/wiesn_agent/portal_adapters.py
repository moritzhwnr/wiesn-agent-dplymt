"""Portal adapters — per-portal scanning strategies.

High-value portals that use non-standard UI patterns (JS calendars,
shadow DOM, custom widgets) can register a specialized adapter here
instead of relying on the global select-dropdown heuristic.

Usage:
    adapter = get_adapter("Käfer Wiesn-Schänke")
    if adapter:
        snapshot = await adapter.scan(page, portal, timeout)
    else:
        snapshot = await scan_portal_availability(page, portal, timeout)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from wiesn_agent.config_model import PortalConfig

logger = logging.getLogger(__name__)


class PortalAdapter(ABC):
    """Base class for portal-specific scanning adapters."""

    @abstractmethod
    async def scan(self, page: Any, portal: PortalConfig, timeout: int) -> dict:
        """Scan the portal and return availability data.

        Returns a dict compatible with PortalSnapshot fields:
            portal_name, portal_url, timestamp, datum_options, portal_type
        """
        ...

    @abstractmethod
    def matches(self, portal: PortalConfig) -> bool:
        """Return True if this adapter handles the given portal."""
        ...


# ── Adapter registry ──────────────────────────────

_adapters: list[PortalAdapter] = []


def register_adapter(adapter: PortalAdapter) -> None:
    """Register a portal adapter."""
    _adapters.append(adapter)
    logger.info("Registered portal adapter: %s", type(adapter).__name__)


def get_adapter(portal: PortalConfig) -> PortalAdapter | None:
    """Find a matching adapter for the given portal, or None."""
    for adapter in _adapters:
        if adapter.matches(portal):
            return adapter
    return None
