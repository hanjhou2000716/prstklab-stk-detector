"""P0-15 contract tests for freshness hard gates and safe degradation."""

from datetime import datetime
from zoneinfo import ZoneInfo

from src.market_data import annotate_quote_freshness
from src.release_gate import _strict_research_freshness_errors


def test_old_market_quote_remains_visible_but_is_not_alert_eligible():
    rows = annotate_quote_freshness(
        [{
            "ticker": "TAIEX",
            "market": "taiwan",
            "price": 40_000,
            "quote_date": "2026-08-10",
            "quote_time": "2026-08-10T13:30:00+08:00",
        }],
        now=datetime(2026, 8, 14, 10, 0, tzinfo=ZoneInfo("Asia/Taipei")),
    )
    assert rows[0]["freshness"] == "stale"
    assert rows[0]["alert_eligible"] is False


def test_recent_close_is_explicit_and_cannot_trigger_live_alerts():
    rows = annotate_quote_freshness(
        [{
            "ticker": "TAIEX",
            "market": "taiwan",
            "price": 40_000,
            "quote_date": "2026-08-13",
            "quote_time": "2026-08-13T13:30:00+08:00",
        }],
        now=datetime(2026, 8, 14, 10, 0, tzinfo=ZoneInfo("Asia/Taipei")),
    )
    assert rows[0]["freshness"] == "recent_close"
    assert rows[0]["alert_eligible"] is False


def test_release_gate_rejects_non_fresh_research_snapshot():
    manifest = {
        "status": "ready",
        "release_id": "release-freshness-1",
        "research_freshness": "stale_fallback",
        "artifact_paths": {},
        "artifact_hashes": {},
    }
    errors = _strict_research_freshness_errors(
        manifest,
        {"generated_at": "2026-08-13T00:00:00+00:00"},
        max_research_age_hours=24,
        public=True,
    )
    assert any("research_freshness" in error for error in errors)
