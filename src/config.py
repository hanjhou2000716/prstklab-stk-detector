"""Configuration loading and validation."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    dashboard_url: str

    @property
    def telegram_ready(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)


def get_settings() -> Settings:
    """Load local .env values or GitHub Actions environment variables."""
    load_dotenv()
    return Settings(
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID"),
        dashboard_url=os.getenv(
            "DASHBOARD_URL",
            "https://example.github.io/prstklab-stk-detector/",
        ),
    )

