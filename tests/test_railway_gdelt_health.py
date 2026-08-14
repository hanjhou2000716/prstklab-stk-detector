from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

MODULE = Path(__file__).parents[1] / "railway-monitor" / "gdelt_health.py"
SPEC = importlib.util.spec_from_file_location("railway_gdelt_health_test", MODULE)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


NOW = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)


def test_empty_success_is_no_event_not_scan_failure():
    health = module.project_gdelt_health(
        fetch_state="live",
        fetch_error=None,
        article_count=0,
        alert_count=0,
        pending_count=0,
        pending_reasons={},
        market_sync_status="not_confirmed",
        stale_cache_used=False,
        now=NOW,
    )
    assert health["status"] == "healthy"
    assert health["event_scan"] == "no_event"
    assert health["error"] is None


def test_provider_failure_is_scan_failed():
    health = module.project_gdelt_health(
        fetch_state="failed",
        fetch_error="HTTP_503",
        article_count=0,
        alert_count=0,
        pending_count=0,
        pending_reasons={},
        market_sync_status="not_confirmed",
        stale_cache_used=False,
        now=NOW,
    )
    assert health["status"] == "failed"
    assert health["event_scan"] == "scan_failed"
    assert health["error"] == "HTTP_503"


def test_stale_cache_is_visible_but_not_live():
    health = module.project_gdelt_health(
        fetch_state="stale_cache",
        fetch_error="rate_limited",
        article_count=2,
        alert_count=0,
        pending_count=2,
        pending_reasons={"waiting_market_sync_for_warning": 2},
        market_sync_status="not_confirmed",
        stale_cache_used=True,
        now=NOW,
    )
    assert health["status"] == "fallback_active"
    assert health["event_scan"] == "has_events"
    assert health["stale_cache_used"] is True
    assert health["alert_count"] == 0
