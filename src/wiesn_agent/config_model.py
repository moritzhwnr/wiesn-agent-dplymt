"""Pydantic models for Wiesn-Agent configuration."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class UserConfig(BaseModel):
    vorname: str
    nachname: str
    email: str
    telefon: str = ""
    personen: int = 10
    notizen: str = ""
    strasse: str = ""
    hausnummer: str = ""
    plz: str = ""
    stadt: str = ""
    firma: str = ""

    # English property aliases for internal code clarity
    @property
    def first_name(self) -> str:
        return self.vorname

    @property
    def last_name(self) -> str:
        return self.nachname

    @property
    def phone(self) -> str:
        return self.telefon

    @property
    def persons(self) -> int:
        return self.personen

    @property
    def notes(self) -> str:
        return self.notizen


class SlotConfig(BaseModel):
    enabled: bool = True
    von: str = "10:00"
    bis: str = "23:00"
    prioritaet: int = 1


class SlotsConfig(BaseModel):
    morgens: SlotConfig = Field(default_factory=lambda: SlotConfig(von="10:00", bis="12:00", prioritaet=3))
    mittags: SlotConfig = Field(default_factory=lambda: SlotConfig(von="12:00", bis="16:00", prioritaet=2))
    abends: SlotConfig = Field(default_factory=lambda: SlotConfig(von="16:00", bis="23:00", prioritaet=1))


class ReservierungConfig(BaseModel):
    wunsch_tage: list[str] = Field(default_factory=list)
    slots: SlotsConfig = Field(default_factory=SlotsConfig)
    min_personen: int = 6
    max_personen: int = 12


class PortalConfig(BaseModel):
    name: str
    url: str
    brauerei: str = ""
    plaetze: int = 0
    enabled: bool = True


class StilleZeitConfig(BaseModel):
    von: str = "22:00"
    bis: str = "08:00"

    from pydantic import field_validator

    @field_validator("von", "bis", mode="before")
    @classmethod
    def _validate_time_format(cls, v: str) -> str:
        import re
        if not re.match(r"^\d{2}:\d{2}$", v):
            raise ValueError(f"Invalid time format '{v}', expected HH:MM")
        h, m = int(v[:2]), int(v[3:])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError(f"Invalid time '{v}', hours 0-23, minutes 0-59")
        return v


VALID_DAYS = {"Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"}


class NotificationConfig(BaseModel):
    desktop: bool = True
    nur_an_tagen: list[str] = Field(default_factory=list)
    stille_zeit: StilleZeitConfig = Field(default_factory=StilleZeitConfig)
    # Apprise URLs — each entry is a notification service
    # Examples: "ntfy://wiesn-alert", "tgram://token/chat_id", "mailto://..."
    apprise_urls: list[str] = Field(default_factory=list)
    # BotBell — Push notifications to iPhone/iPad/Mac
    # Get token from BotBell app: bt_... (bot token) or pak_... (PAT)
    botbell_token: str = ""
    # Emoji in notification titles (🍺🌙 etc.)
    use_emojis: bool = True

    from pydantic import field_validator

    @field_validator("nur_an_tagen", mode="before")
    @classmethod
    def _validate_days(cls, v: list[str] | None) -> list[str]:
        if not v:
            return []
        invalid = [d for d in v if d not in VALID_DAYS]
        if invalid:
            raise ValueError(
                f"Invalid day(s): {invalid}. Allowed: {sorted(VALID_DAYS)}"
            )
        return v

    @classmethod
    def _validate_apprise_urls(cls, v: list[str] | None) -> list[str]:
        return v or []

    _fix_apprise = field_validator("apprise_urls", mode="before")(_validate_apprise_urls)


class MonitoringConfig(BaseModel):
    check_interval_minutes: int = 30
    max_retries: int = 3
    screenshot_on_change: bool = True
    screenshot_dir: str = "./screenshots"
    screenshot_retention_days: int = 7  # auto-cleanup screenshots older than this


class BrowserConfig(BaseModel):
    headless: bool = True
    slow_mo: int = 300
    timeout: int = 30000


class WiesnConfig(BaseModel):
    user: UserConfig
    reservierung: ReservierungConfig = Field(default_factory=ReservierungConfig)
    portale: list[PortalConfig] = Field(default_factory=list)
    notifications: NotificationConfig = Field(default_factory=NotificationConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> WiesnConfig:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(data)

    def enabled_portale(self) -> list[PortalConfig]:
        return [p for p in self.portale if p.enabled]

    def enabled_slots(self) -> list[tuple[str, SlotConfig]]:
        """Returns enabled slots sorted by priority."""
        slots = []
        for name in ("morgens", "mittags", "abends"):
            slot = getattr(self.reservierung.slots, name)
            if slot.enabled:
                slots.append((name, slot))
        slots.sort(key=lambda x: x[1].prioritaet)
        return slots

    def redacted_dump(self) -> dict:
        """Return config dict with PII and secrets redacted."""
        data = self.model_dump()
        # Redact PII
        if "user" in data:
            for key in ("email", "telefon", "strasse", "hausnummer", "plz", "stadt"):
                if data["user"].get(key):
                    data["user"][key] = "***"
        # Redact notification secrets
        if "notifications" in data:
            notif = data["notifications"]
            if notif.get("apprise_urls"):
                notif["apprise_urls"] = [
                    url.split("://")[0] + "://***" if "://" in url else "***"
                    for url in notif["apprise_urls"]
                ]
            if notif.get("botbell_token"):
                notif["botbell_token"] = "***"
        return data
