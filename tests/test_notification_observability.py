from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "src" / "notification_observability.py"
SPEC = importlib.util.spec_from_file_location("notification_observability_test_module", MODULE_PATH)
assert SPEC and SPEC.loader
notification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(notification)
DECISION_FIELDS = notification.DECISION_FIELDS
decision_summary = notification.decision_summary
merge_decision_health = notification.merge_decision_health


def test_decision_summary_is_bounded_and_contains_all_safe_fields() -> None:
    summary = decision_summary(
        event={"source_key": "financialjuice", "notification_status": "eligible"},
        scan_status="completed",
        notification_expected=True,
        notification_status="dispatch_requested",
        notification_reason="vendor_priority_importance_ge_8",
        delivered_count=1,
        failed_count=2,
        last_processed_at=datetime(2026, 9, 3, 1, 2, 3, tzinfo=UTC).isoformat(),
    )
    assert tuple(summary) == DECISION_FIELDS
    assert summary["candidate_type"] == "financialjuice"
    assert summary["delivered_count"] == 1
    assert summary["failed_count"] == 2
    assert "TELEGRAM_BOT_TOKEN" not in str(summary)
    assert "chat_id" not in str(summary).casefold()


def test_merge_decision_health_keeps_lanes_separate() -> None:
    health = {"status": "healthy"}
    first = decision_summary(event=None, scan_status="completed", notification_status="no_event")
    second = decision_summary(
        event={"source_key": "official"},
        scan_status="completed",
        notification_expected=True,
        notification_status="delivered",
    )
    merged = merge_decision_health(health, "scheduled_brief", first)
    merged = merge_decision_health(merged, "official_event_monitor", second)
    assert merged["notification_observability"]["scheduled_brief"]["notification_status"] == "no_event"
    assert merged["notification_observability"]["official_event_monitor"]["notification_status"] == "delivered"


def test_gmail_reconciliation_distinguishes_duplicate_from_new_candidate() -> None:
    module_path = Path(__file__).parents[1] / "railway-monitor" / "health_contract.py"
    spec = importlib.util.spec_from_file_location("railway_health_contract_observability", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    duplicate = module.gmail_notification_health(
        {"status": "healthy", "processed": 1, "duplicate": 1, "failed": 0},
        now=datetime(2026, 9, 3, tzinfo=UTC),
    )
    assert duplicate["candidate_type"] == "none"
    assert duplicate["notification_expected"] is False
    assert duplicate["notification_status"] == "no_new_content"
    fresh = module.gmail_notification_health(
        {"status": "healthy", "processed": 1, "duplicate": 0, "failed": 0},
        now=datetime(2026, 9, 3, tzinfo=UTC),
    )
    assert fresh["candidate_type"] == "financialjuice_or_creator"
    assert fresh["notification_expected"] is True
    assert fresh["notification_status"] == "dispatch_requested"
