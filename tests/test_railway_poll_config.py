from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "railway-monitor" / "poll_config.py"
SPEC = importlib.util.spec_from_file_location("railway_poll_config", MODULE_PATH)
assert SPEC and SPEC.loader
poll_config = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = poll_config
SPEC.loader.exec_module(poll_config)


def test_poll_config_projects_bounded_defaults_and_flags():
    values = {
        "JIN10_POLL_SECONDS": "1",
        "JIN10_FLASH_LIMIT": "999",
        "GDELT_POLL_SECONDS": "30",
        "JIN10_INITIAL_BACKFILL": "TRUE",
        "GDELT_DISCOVERY_ENABLED": "false",
    }

    settings = poll_config.load_poll_settings(configured=_configured, environ=values, cooldown_seconds=1800)

    assert settings.interval == 60
    assert settings.limit == 100
    assert settings.gdelt_interval == 900
    assert settings.bootstrap is True
    assert settings.gdelt_enabled is False
    assert settings.cooldown == 1800


def test_poll_config_invalid_numbers_fall_back_to_defaults():
    values = {"JIN10_POLL_SECONDS": "bad", "JIN10_FLASH_LIMIT": "bad", "GDELT_POLL_SECONDS": "bad"}

    settings = poll_config.load_poll_settings(configured=_configured, environ=values)

    assert settings.interval == 120
    assert settings.limit == 30
    assert settings.gdelt_interval == 900


def _configured(name: str) -> str:
    return {"JIN10_MCP_TOKEN": "jin10", "GITHUB_DISPATCH_TOKEN": "github", "GITHUB_REPOSITORY": "o/r", "EXTERNAL_ALERT_SHARED_SECRET": "secret"}[name]
