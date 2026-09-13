"""Configuration loading and validation."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from src.telegram_subscriptions import fetch_active_chat_ids


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str | None
    telegram_chat_ids: tuple[str, ...]
    dashboard_url: str
    telegram_subscriptions_enabled: bool = False

    @property
    def telegram_ready(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_ids)


def parse_chat_ids(*values: str | None) -> tuple[str, ...]:
    """Read comma/newline-separated recipients while preserving their order."""
    recipients: list[str] = []
    for value in values:
        for chat_id in (value or "").replace("\n", ",").split(","):
            normalized = chat_id.strip()
            if normalized and normalized not in recipients:
                recipients.append(normalized)
    return tuple(recipients)


def get_settings() -> Settings:
    """Load local .env values or GitHub Actions environment variables."""
    load_dotenv()
    subscriptions_enabled = os.getenv("TELEGRAM_SUBSCRIPTIONS_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
    legacy_chat_ids = parse_chat_ids(os.getenv("TELEGRAM_CHAT_IDS"))
    chat_ids = fetch_active_chat_ids() if subscriptions_enabled else legacy_chat_ids
    return Settings(
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
        # Broadcast recipients are managed exclusively through the plural
        # secret.  A stale singular secret must not silently re-enter the list.
        # Production workflows opt into the private Supabase subscription
        # table; dry-runs and scoped acceptance keep using their explicit IDs.
        telegram_chat_ids=chat_ids,
        dashboard_url=os.getenv(
            "DASHBOARD_URL",
            "https://example.github.io/prstklab-stk-detector/",
        ),
        telegram_subscriptions_enabled=subscriptions_enabled,
    )
