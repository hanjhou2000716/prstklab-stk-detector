import json
from datetime import UTC, datetime

import pytest

from src import scheduled_delivery
from src.market_digest import build_taiwan_holiday_notice_digest
from src.release_gate import ReleaseGateResult
from src.scheduled_delivery import (
    _briefing_delivery_event,
    _briefing_evidence_ready,
    _closed_market_slot_context,
    _creator_records_from_observations,
    _load_creator_records,
    _resolve_delivery_obligation,
)
from src.telegram_client import TextDeliveryReceipt, alert_mini_app_url

TAIFEX_SOURCE_URLS = [
    "https://www.taifex.com.tw/file/taifex/CHINESE/11/attach/%E5%8F%B0%E6%9C%9F%E4%BA%A4%E5%AD%97%E7%AC%AC1140003036%E8%99%9F%E5%87%BD.pdf",
    "https://www.taifex.com.tw/cht/11/newsDetail?idx=17137&newsType=1",
    "https://www.taifex.com.tw/file/taifex/CHINESE/11/attach/%E5%85%AC%E5%91%8A115%E5%B9%B4%E4%B8%AD%E7%A7%8B%E7%AF%80%20%E6%95%99%E5%B8%AB%E7%AF%80%E4%BC%91%E5%B8%82.pdf",
]


def _cash_calendar(is_trading_day: bool, *, next_trading_date: str | None = None) -> dict[str, object]:
    return {
        "is_trading_day": is_trading_day,
        "calendar_status": "confirmed_open" if is_trading_day else "confirmed_closed",
        "calendar": "XTAI",
        "calendar_provider": "pandas_market_calendars",
        "calendar_basis": "pandas_market_calendars:XTAI",
        "next_trading_date": next_trading_date,
    }


def _taifex_calendar(is_trading_day: bool, *, next_trading_date: str | None = None) -> dict[str, object]:
    return {
        "is_trading_day": is_trading_day,
        "calendar_status": "confirmed_open" if is_trading_day else "confirmed_closed",
        "calendar": "TAIFEX",
        "calendar_provider": "TAIFEX",
        "calendar_basis": "TAIFEX_official_annual_schedule+official_closure_notices",
        "calendar_version": "TAIFEX-2026",
        "calendar_coverage_start": "2026-01-01",
        "calendar_coverage_end": "2026-12-31",
        "calendar_source_urls": TAIFEX_SOURCE_URLS,
        "calendar_source_published_on": ["2025-10-30", "2026-07-09", "2026-09-18"],
        "calendar_source_document": "台期交字第1140003036號函",
        "calendar_verified_on": "2026-09-25",
        "next_trading_date": next_trading_date,
    }


def test_creator_observations_are_projected_into_release_records() -> None:
    rows = _creator_records_from_observations([{
        "observation_id": "jenny-1", "source": "jenny", "content_origin": "jenny",
        "episode_title": "Public episode", "public_safe": True, "parse_status": "normalized",
    }, {
        "observation_id": "private", "source": "jenny", "content_origin": "jenny",
        "public_safe": False,
    }])
    assert rows == []


def test_scheduled_brief_requires_three_factors_and_two_evidence_dimensions() -> None:
    base = {"market_assessment": {"confidence": "medium", "factor_count": 3, "evidence_dimensions": ["equity", "rates"]}}
    assert _briefing_evidence_ready(base) is True
    assert _briefing_evidence_ready({"market_assessment": {"confidence": "low", "factor_count": 5, "evidence_dimensions": ["equity", "rates"]}}) is False
    assert _briefing_evidence_ready({"market_assessment": {"confidence": "medium", "factor_count": 2, "evidence_dimensions": ["equity", "rates"]}}) is False
    assert _briefing_evidence_ready({"market_assessment": {"confidence": "medium", "factor_count": 3, "evidence_dimensions": ["equity"]}}) is False


def test_market_anchor_deadlines_use_the_slot_market_timezone():
    taiwan = {
        "effective_slot": "post_close",
        "slot_date": "2026-09-25",
        "scheduled_for_at": "2026-09-25T14:20:00+08:00",
    }
    assert scheduled_delivery._scheduled_send_window(
        "post_close", taiwan, datetime.fromisoformat("2026-09-25T14:49:00+08:00"),
    ) == (True, "within_delivery_window")
    assert scheduled_delivery._scheduled_send_window(
        "post_close", taiwan, datetime.fromisoformat("2026-09-25T14:50:00+08:00"),
    ) == (False, "delivery_deadline_passed")

    us = {
        "effective_slot": "us_premarket",
        "slot_date": "2026-09-25",
        "scheduled_for_at": "2026-09-25T09:00:00-04:00",
    }
    assert scheduled_delivery._scheduled_send_window(
        "us_premarket", us, datetime.fromisoformat("2026-09-25T09:29:00-04:00"),
    ) == (True, "within_delivery_window")
    assert scheduled_delivery._scheduled_send_window(
        "us_premarket", us, datetime.fromisoformat("2026-09-25T09:30:00-04:00"),
    ) == (False, "delivery_deadline_passed")


def test_deployment_recovery_budget_is_clamped_to_the_original_market_window():
    taiwan = {
        "effective_slot": "post_close",
        "slot_date": "2026-09-25",
        "scheduled_for_at": "2026-09-25T14:20:00+08:00",
    }
    assert scheduled_delivery.scheduled_send_window_remaining_seconds(
        "post_close", taiwan, datetime.fromisoformat("2026-09-25T14:29:00+08:00"),
    ) == 1260
    assert scheduled_delivery.scheduled_send_window_remaining_seconds(
        "post_close", taiwan, datetime.fromisoformat("2026-09-25T14:49:30+08:00"),
    ) == 30
    assert scheduled_delivery.scheduled_send_window_remaining_seconds(
        "post_close", taiwan, datetime.fromisoformat("2026-09-25T14:50:00+08:00"),
    ) == 0

    us = {
        "effective_slot": "us_premarket",
        "slot_date": "2026-09-25",
        "scheduled_for_at": "2026-09-25T09:00:00-04:00",
    }
    assert scheduled_delivery.scheduled_send_window_remaining_seconds(
        "us_premarket", us, datetime.fromisoformat("2026-09-25T09:29:30-04:00"),
    ) == 30
    assert scheduled_delivery.scheduled_send_window_remaining_seconds(
        "us_premarket", us, datetime.fromisoformat("2026-09-25T09:30:00-04:00"),
    ) == 0


def test_routine_market_report_does_not_require_an_event_candidate():
    assert scheduled_delivery._is_routine_market_report({
        "scheduled_report": True, "market_scope_key": "taiwan",
    }) is True
    assert scheduled_delivery._is_routine_market_report({
        "scheduled_report": True, "market_scope_key": "us",
    }) is True
    assert scheduled_delivery._is_routine_market_report({
        "scheduled_report": False, "market_scope_key": "us",
    }) is False


def test_closed_non_morning_anchor_is_pages_only() -> None:
    context = {"delivery_intent": "notify_candidate", "slot_date": "2026-09-07"}
    result = _closed_market_slot_context(
        {"markets": {
            "taiwan": {"is_trading_day": False, "calendar_status": "confirmed_closed", "calendar": "XTAI"},
            "taiwan_cash": _cash_calendar(False),
            "taiwan_futures": _taifex_calendar(False),
        }}, "post_close", context,
    )
    assert result["delivery_intent"] == "publish_only"
    assert result["suppression_reason"] == "closed_market_publish_only"


def test_weekend_non_morning_anchor_fails_closed_without_market_status() -> None:
    result = _closed_market_slot_context(
        {}, "post_close", {"delivery_intent": "notify_candidate", "slot_date": "2026-09-06"},
    )
    assert result["delivery_intent"] == "publish_only"
    assert result["suppression_reason"] == "closed_market_weekend_publish_only"


def test_open_anchor_keeps_notification_intent() -> None:
    context = {"delivery_intent": "notify_candidate", "slot_date": "2026-09-07"}
    result = _closed_market_slot_context(
        {"markets": {
            "taiwan": {"is_trading_day": True, "calendar_status": "confirmed_open", "calendar": "XTAI"},
            "taiwan_cash": _cash_calendar(True),
            "taiwan_futures": _taifex_calendar(True),
        }}, "post_close", context,
    )
    assert result == context


def test_prepared_obligation_matrix_separates_holiday_report_and_expected_skip():
    holiday = {
        "markets": {
            "taiwan": {"is_trading_day": False, "calendar_status": "confirmed_closed", "calendar": "XTAI"},
            "taiwan_cash": _cash_calendar(False, next_trading_date="2026-09-29"),
            "taiwan_futures": _taifex_calendar(False, next_trading_date="2026-09-29"),
        },
    }
    context = {
        "slot_date": "2026-09-28", "delivery_intent": "notify_candidate",
        "resolution_reason": "taiwan_holiday_notice_required",
    }
    assert _resolve_delivery_obligation(
        holiday, "morning", context, notification_requested=True,
    )[:2] == ("report_required", "routine_morning_report")
    assert _resolve_delivery_obligation(
        holiday, "pre_open", context, notification_requested=True,
    )[:2] == ("holiday_notice_required", "taiwan_exchange_holiday")
    assert _resolve_delivery_obligation(
        holiday, "post_close", context, notification_requested=True,
    )[:2] == ("expected_skip", "closed_market_publish_only")
    assert _resolve_delivery_obligation(
        {}, "pre_open", {"slot_date": "2026-09-27", "delivery_intent": "publish_only"},
        notification_requested=True,
    )[:2] == ("expected_skip", "closed_market_weekend_publish_only")


def test_prepared_obligation_blocks_unverified_calendar_and_preserves_market_split():
    base_context = {"slot_date": "2026-09-28", "delivery_intent": "notify_candidate"}
    unknown = {"markets": {"taiwan": {"is_trading_day": False}}}
    assert _resolve_delivery_obligation(
        unknown, "pre_open", base_context, notification_requested=True,
    )[:2] == ("blocked", "market_calendar_unverified")
    split = {"markets": {
        "taiwan": {"is_trading_day": True, "calendar_status": "confirmed_open", "calendar": "XTAI"},
        "taiwan_cash": _cash_calendar(True),
        "taiwan_futures": _taifex_calendar(False),
    }}
    obligation, reason, states = _resolve_delivery_obligation(
        split, "pre_open", base_context, notification_requested=True,
    )
    assert (obligation, reason) == ("report_required", "routine_market_report")
    assert [row["is_trading_day"] for row in states] == [True, False]
    post_close_context = {**base_context, "resolution_reason": "taiwan_market_calendar_split"}
    post_close = _closed_market_slot_context(split, "post_close", post_close_context)
    assert post_close["delivery_intent"] == "notify_candidate"
    assert post_close["resolution_reason"] == "taiwan_market_calendar_split"
    assert _resolve_delivery_obligation(
        split, "post_close", post_close, notification_requested=True,
    )[:2] == ("report_required", "routine_market_report")


def test_prepared_obligation_rejects_shared_xtai_calendar_and_missing_futures_status():
    context = {"slot_date": "2026-09-28", "delivery_intent": "notify_candidate"}
    shared = {"markets": {
        "taiwan_cash": _cash_calendar(False, next_trading_date="2026-09-29"),
        "taiwan_futures": {
            **_cash_calendar(False, next_trading_date="2026-09-29"),
            "calendar_basis": "shared_XTAI_baseline",
        },
    }}
    assert _resolve_delivery_obligation(
        shared, "pre_open", context, notification_requested=True,
    )[:2] == ("blocked", "market_calendars_not_independent")
    assert _resolve_delivery_obligation(
        {"markets": {"taiwan_cash": _cash_calendar(False)}},
        "pre_open", context, notification_requested=True,
    )[:2] == ("blocked", "market_calendar_unavailable")

    stale_coverage = {"markets": {
        "taiwan_cash": _cash_calendar(False),
        "taiwan_futures": {**_taifex_calendar(False), "calendar_coverage_end": "2026-09-27"},
    }}
    assert _resolve_delivery_obligation(
        stale_coverage, "pre_open", context, notification_requested=True,
    )[:2] == ("blocked", "taifex_calendar_unverified")


def test_us_premarket_calendar_failure_blocks_but_confirmed_holiday_skips():
    context = {"slot_date": "2026-09-28", "delivery_intent": "notify_candidate"}
    assert _resolve_delivery_obligation(
        {"markets": {"us": {"is_trading_day": False}}},
        "us_premarket", context, notification_requested=True,
    )[:2] == ("blocked", "market_calendar_unverified")
    assert _resolve_delivery_obligation(
        {"markets": {"us": {
            "is_trading_day": False, "calendar_status": "confirmed_closed", "calendar": "NYSE",
        }}},
        "us_premarket", context, notification_requested=True,
    )[:2] == ("expected_skip", "us_market_closed_publish_only")


def test_holiday_notice_is_ready_for_the_existing_scheduled_sender_contract():
    briefing = build_taiwan_holiday_notice_digest(
        slot="pre_open", slot_date="2026-09-28", next_trading_date="2026-09-29",
        cash_is_trading_day=False, futures_is_trading_day=False,
        calendar_evidence=[
            {
                "provider": "pandas_market_calendars", "calendar_id": "XTAI",
                "calendar_basis": "pandas_market_calendars:XTAI", "source_urls": [],
                "market": "taiwan_cash", "date": "2026-09-28", "is_trading_day": False,
                "next_trading_date": "2026-09-29",
            },
            {
                "provider": "TAIFEX", "calendar_id": "TAIFEX",
                "calendar_basis": "TAIFEX_official_annual_schedule+official_closure_notices",
                "source_urls": TAIFEX_SOURCE_URLS,
                "calendar_version": "TAIFEX-2026", "coverage_start": "2026-01-01",
                "coverage_end": "2026-12-31", "source_published_on": ["2025-10-30", "2026-07-09", "2026-09-18"],
                "source_document": "台期交字第1140003036號函", "verified_on": "2026-09-25",
                "market": "taifex_taiwan_index_futures_day_session", "date": "2026-09-28",
                "is_trading_day": False, "next_trading_date": "2026-09-29",
            },
        ],
    )
    assert _briefing_evidence_ready(briefing) is True
    assert briefing["source_evidence"][0]["provider"] == "pandas_market_calendars"
    assert briefing["source_evidence"][0]["calendar_id"] == "XTAI"
    assert briefing["source_evidence"][1]["provider"] == "TAIFEX"
    assert briefing["source_evidence"][1]["source_urls"] == TAIFEX_SOURCE_URLS
    snapshot = {"briefing": {**briefing, "slot_context": {"slot_date": "2026-09-28"}}}
    event = _briefing_delivery_event(snapshot, "pre_open")
    assert event is not None
    assert event["market_scope"] == "taiwan"
    assert "次一交易日 9/29" in event["public_short_message"]


def test_holiday_notice_rejects_missing_or_conflicting_independent_evidence():
    evidence = [
        {
            "provider": "pandas_market_calendars", "calendar_id": "XTAI",
            "market": "taiwan_cash", "date": "2026-09-28", "is_trading_day": False,
            "next_trading_date": "2026-09-29",
        },
        {
            "provider": "TAIFEX", "calendar_id": "TAIFEX", "source_urls": TAIFEX_SOURCE_URLS,
            "calendar_version": "TAIFEX-2026", "coverage_start": "2026-01-01",
            "coverage_end": "2026-12-31", "source_published_on": ["2025-10-30", "2026-07-09", "2026-09-18"],
            "source_document": "台期交字第1140003036號函", "verified_on": "2026-09-25",
            "market": "taifex_taiwan_index_futures_day_session", "date": "2026-09-28",
            "is_trading_day": False, "next_trading_date": "2026-09-29",
        },
    ]
    with pytest.raises(ValueError, match="independent official TAIFEX"):
        build_taiwan_holiday_notice_digest(
            slot="pre_open", slot_date="2026-09-28", next_trading_date="2026-09-29",
            cash_is_trading_day=False, futures_is_trading_day=False,
            calendar_evidence=[evidence[0], {**evidence[1], "calendar_id": "XTAI"}],
        )
    with pytest.raises(ValueError, match="next trading date mismatch"):
        build_taiwan_holiday_notice_digest(
            slot="pre_open", slot_date="2026-09-28", next_trading_date="2026-09-29",
            cash_is_trading_day=False, futures_is_trading_day=False,
            calendar_evidence=[evidence[0], {**evidence[1], "next_trading_date": "2026-09-30"}],
        )


def test_market_snapshot_failure_is_reported_with_sanitized_blocked_decision(monkeypatch, tmp_path):
    captured = {}

    def fail_snapshot():
        raise ValueError("provider response included sensitive detail")

    monkeypatch.setattr(scheduled_delivery, "build_market_snapshot", fail_snapshot)
    monkeypatch.setattr(
        scheduled_delivery,
        "_write_decision_output",
        lambda values, **kwargs: captured.update(values=values, kwargs=kwargs),
    )
    with pytest.raises(RuntimeError, match="market_snapshot_unavailable:ValueError"):
        scheduled_delivery.prepare("morning", tmp_path / "market.json")
    assert captured["values"]["delivery_obligation"] == "blocked"
    assert captured["values"]["source_health_status"] == "failed"
    assert "sensitive detail" not in str(captured)


def test_expected_skip_send_stops_before_release_gate_or_sender(monkeypatch, tmp_path):
    snapshot_path = tmp_path / "market.json"
    snapshot_path.write_text(json.dumps({
        "snapshot_id": "snapshot-holiday",
        "briefing": {
            "slot_context": {"delivery_intent": "publish_only", "slot_date": "2026-09-28"},
            "schedule_decision": {
                "delivery_obligation": "expected_skip",
                "obligation_reason": "closed_market_publish_only",
            },
        },
    }), encoding="utf-8")
    captured = {}
    monkeypatch.setattr(
        scheduled_delivery,
        "verify_release_for_delivery",
        lambda *args, **kwargs: pytest.fail("release gate must not run for an expected skip"),
    )
    monkeypatch.setattr(
        scheduled_delivery,
        "_write_decision_output",
        lambda values, **kwargs: captured.update(values=values, kwargs=kwargs),
    )
    scheduled_delivery.send(snapshot_path, "post_close", tmp_path / "missing-manifest.json")
    assert captured["values"]["delivery_status"] == "suppressed"
    assert captured["values"]["delivery_obligation"] == "expected_skip"


def test_manual_notify_false_is_a_public_not_requested_decision() -> None:
    status, reason = scheduled_delivery._schedule_decision_category(
        {},
        briefing={},
        decision_event=None,
        delivery_eligible=False,
        comparison_reason="",
        notification_requested=False,
    )
    assert status == "not_requested"
    assert reason == "manual_notification_opt_in_required"


def test_manual_notify_false_is_persisted_in_schedule_decision(tmp_path) -> None:
    snapshot = {
        "briefing": {"morning_analysis": {"system_analysis": {}}},
    }
    row = scheduled_delivery._attach_schedule_decision(
        snapshot,
        snapshot_path=tmp_path / "market.json",
        slot="us_premarket",
        context={
            "effective_slot": "us_premarket",
            "scheduled_slot": "us_premarket",
            "slot_date": "2026-09-08",
            "delivery_intent": "notify_candidate",
        },
        production_started_at="2026-09-08T14:00:00+00:00",
        completed_at="2026-09-08T14:01:00+00:00",
        decision_event=None,
        briefing={},
        notification_requested=False,
    )
    assert row["notification_status"] == "not_requested"
    assert row["notification_requested"] is False
    assert row["suppression_reason"] == "manual_notification_opt_in_required"
    assert snapshot["briefing"]["schedule_decision"] == row


def test_scheduled_brief_prioritises_eligible_financialjuice_event() -> None:
    event = {"source_key": "financialjuice", "notification_status": "eligible", "title": "FJ"}
    snapshot = {
        "financialjuice_priority_events": [event],
        "events": {"items": [{"kind": "market_signal", "title": "TAIEX"}]},
    }
    assert scheduled_delivery._pick_event(snapshot, "morning") == event


def test_scheduled_selection_skips_fj_without_release_alert_and_uses_next_candidate(monkeypatch) -> None:
    first = {
        "source_key": "financialjuice", "notification_status": "eligible",
        "vendor_priority_notification": True, "vendor_importance": 9,
            "notification_id": "missing-alert", "event": "First FJ event announced。",
    }
    second = {
        "source_key": "financialjuice", "notification_status": "eligible",
        "vendor_priority_notification": True, "vendor_importance": 9,
        "delivery_policy": "fj_priority", "canonical_fact_key": "financialjuice-fact:second",
        "source_identity_verified": True, "public_signal_eligible": True, "freshness_status": "fresh",
            "notification_id": "published-alert", "event": "Second FJ event announced。",
    }
    candidates = iter((first, second))
    monkeypatch.setattr(scheduled_delivery, "_pick_event", lambda *_args, **_kwargs: next(candidates, None))

    class Ledger:
        delivery_claims = {}

        @staticmethod
        def delivery_history():
            return []

        @staticmethod
        def theme_decision(_event):
            return {"allowed": True}

        @staticmethod
        def record_decision(*_args, **_kwargs):
            return None

        @staticmethod
        def save():
            return None

    event, _budget, reason = scheduled_delivery._select_scheduled_candidate(
        {"events": {"items": [first, second]}}, "morning", Ledger(),
        release_alert_ids={"published-alert"},
    )
    assert event == second
    assert reason == "candidate_ready"


def test_scheduled_selection_skips_claimed_fj_and_uses_next_candidate(monkeypatch) -> None:
    from src.alert_orchestrator import notification_key_for_event

    first = {
        "source_key": "financialjuice", "notification_status": "eligible",
        "vendor_priority_notification": True, "vendor_importance": 10,
            "notification_id": "already-delivered", "event": "First FJ event announced。",
    }
    second = {
        "source_key": "financialjuice", "notification_status": "eligible",
        "vendor_priority_notification": True, "vendor_importance": 9,
        "delivery_policy": "fj_priority", "canonical_fact_key": "financialjuice-fact:next",
        "source_identity_verified": True, "public_signal_eligible": True, "freshness_status": "fresh",
            "notification_id": "next-event", "event": "Second FJ event announced。",
    }
    candidates = iter((first, second))
    monkeypatch.setattr(scheduled_delivery, "_pick_event", lambda *_args, **_kwargs: next(candidates, None))
    monkeypatch.setattr(
        scheduled_delivery,
        "decide_alert_budget",
        lambda *_args: {"allowed": True, "reason": "budget_available", "event_key": "next-event"},
    )

    class Ledger:
        delivery_claims = {notification_key_for_event(first): {"status": "delivered"}}

        @staticmethod
        def delivery_history():
            return []

        @staticmethod
        def theme_decision(_event):
            return {"allowed": True}

        @staticmethod
        def record_decision(*_args, **_kwargs):
            return None

        @staticmethod
        def save():
            return None

    event, _budget, reason = scheduled_delivery._select_scheduled_candidate(
        {"events": {"items": [first, second]}}, "morning", Ledger(),
    )
    assert event == second
    assert reason == "candidate_ready"


def test_financialjuice_history_flattens_redacted_recipient_receipts() -> None:
    history = scheduled_delivery._financialjuice_delivery_history([
        {
            "notification_key": "financialjuice:event-1",
            "delivery_receipts": [
                {"recipient_hash": "abc", "delivery_status": "delivered"},
                {"recipient_hash": "def", "delivery_status": "failed"},
            ],
        },
        {"notification_key": "financialjuice:event-2", "recipient_hash": "ghi", "status": "delivered"},
    ])
    assert history == [
        {"notification_key": "financialjuice:event-1", "recipient_hash": "abc", "delivery_status": "delivered"},
        {"notification_key": "financialjuice:event-1", "recipient_hash": "def", "delivery_status": "failed"},
        {"notification_key": "financialjuice:event-2", "recipient_hash": "ghi", "delivery_status": "delivered"},
    ]


def _settings():
    return type(
        "Settings",
        (),
        {
            "telegram_ready": True,
            "telegram_bot_token": "token",
            "telegram_chat_ids": ("test",),
            "dashboard_url": "https://example.test/app",
        },
    )()


def _patch_ready(monkeypatch, output):
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    # Delivery claims are durable by design; keep each test's ledger isolated
    # so an intentional uncertain-delivery case cannot affect the next case.
    monkeypatch.setenv("EVENT_LEDGER_PATH", str(output.with_name("event-ledger.json")))
    monkeypatch.setattr(
        scheduled_delivery,
        "verify_release_for_delivery",
        lambda **_kwargs: ReleaseGateResult(True, release_id="release-1", snapshot_id="market-12345678"),
    )
    monkeypatch.setattr(scheduled_delivery, "get_settings", _settings)
    monkeypatch.setattr(scheduled_delivery, "_pick_event", lambda *_args: None)
    monkeypatch.setattr(
        scheduled_delivery,
        "briefing_correlation",
        lambda *_args: {"trace_id": "trace-1", "snapshot_id": "market-12345678", "observation_id": "obs-1"},
    )
    monkeypatch.setattr(scheduled_delivery, "build_brief", lambda *_args: "測試摘要")


def test_scheduled_delivery_blocks_when_manifest_is_not_ready(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "market.json"
    manifest_path = tmp_path / "release-manifest.json"
    snapshot_path.write_text(json.dumps({"snapshot_id": "market-12345678", "quotes": [], "indices": []}), encoding="utf-8")
    manifest_path.write_text(json.dumps({"status": "invalid", "release_id": "release-old"}), encoding="utf-8")
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    def fail_if_called(**_kwargs):
        raise AssertionError("Telegram must not be called when release gate fails")

    monkeypatch.setattr(scheduled_delivery, "send_text_briefs_audited", fail_if_called)
    scheduled_delivery.send(snapshot_path, "morning", manifest_path)
    text = output.read_text(encoding="utf-8")
    assert "sent=false" in text
    assert "reason=release_gate_blocked" in text


def test_expected_report_release_gate_failure_is_not_recorded_as_no_notification(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "market.json"
    manifest_path = tmp_path / "release-manifest.json"
    output = tmp_path / "output"
    _patch_ready(monkeypatch, output)
    snapshot_path.write_text(json.dumps({
        "snapshot_id": "market-12345678",
        "indices": [], "quotes": [],
        "briefing": {
            "slot_context": {
                "effective_slot": "post_close", "slot_date": "2026-09-25",
                "scheduled_for_at": "2026-09-25T14:20:00+08:00",
                "delivery_intent": "notify_candidate",
            },
            "schedule_decision": {"notification_requested": True},
        },
    }), encoding="utf-8")
    manifest_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(scheduled_delivery, "verify_release_for_delivery", lambda **_kwargs: ReleaseGateResult(
        False, release_id="release-older", snapshot_id="market-12345678",
        errors=("public release identity mismatch",),
    ))
    monkeypatch.setattr(
        scheduled_delivery, "send_text_briefs_audited",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("sender must not run")),
    )

    scheduled_delivery.send(snapshot_path, "post_close", manifest_path)

    text = output.read_text(encoding="utf-8")
    assert "notification_expected=true" in text
    assert "notification_status=failed" in text
    assert "last_receipt_status=not_attempted" in text


def test_scheduled_delivery_never_sends_when_public_release_is_superseded(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "market.json"
    manifest_path = tmp_path / "release-manifest.json"
    snapshot_path.write_text(
        json.dumps({"snapshot_id": "market-12345678", "quotes": [], "indices": []}),
        encoding="utf-8",
    )
    manifest_path.write_text("{}", encoding="utf-8")
    output = tmp_path / "output"
    _patch_ready(monkeypatch, output)
    monkeypatch.setattr(
        scheduled_delivery,
        "verify_release_for_delivery",
        lambda **_kwargs: ReleaseGateResult(
            False,
            release_id="release-old",
            snapshot_id="market-12345678",
            errors=("public release was superseded by a newer valid release",),
            gate_status="superseded",
            error_category="parallel_publish_superseded",
            superseded=True,
        ),
    )
    monkeypatch.setattr(
        scheduled_delivery,
        "send_text_briefs_audited",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("sender must not run for superseded release")),
    )

    scheduled_delivery.send(snapshot_path, "morning", manifest_path)

    text = output.read_text(encoding="utf-8")
    assert "sent=false" in text
    assert "delivery_status=blocked" in text
    assert "notification_status=blocked" in text


def test_scheduled_delivery_never_falls_back_to_event_on_publish_only_snapshot(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "market.json"
    manifest_path = tmp_path / "release-manifest.json"
    snapshot_path.write_text(json.dumps({
        "snapshot_id": "market-12345678",
        "quotes": [],
        "indices": [],
        "briefing": {
            "briefing_id": "briefing-publish-only",
            "notification_eligible": False,
            "notification_reason": "late_schedule_publish_only",
            "slot_context": {
                "delivery_intent": "publish_only",
                "resolution_reason": "late_schedule_publish_only",
            },
        },
    }), encoding="utf-8")
    manifest_path.write_text("{}", encoding="utf-8")
    output = tmp_path / "output"
    _patch_ready(monkeypatch, output)
    monkeypatch.setattr(
        scheduled_delivery,
        "send_text_briefs_audited",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("publish-only snapshot must not send")),
    )

    scheduled_delivery.send(snapshot_path, "post_close", manifest_path)

    text = output.read_text(encoding="utf-8")
    assert "sent=false" in text
    assert "notification_reason=late_schedule_publish_only" in text


def test_scheduled_delivery_uses_text_delivery_after_release_gate(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "market.json"
    manifest_path = tmp_path / "release-manifest.json"
    snapshot_path.write_text(
        json.dumps({"snapshot_id": "market-12345678", "quotes": [], "indices": [], "briefing": {}}),
        encoding="utf-8",
    )
    manifest_path.write_text("{}", encoding="utf-8")
    output = tmp_path / "output"
    _patch_ready(monkeypatch, output)
    event = {
        "source_key": "official",
        "event_cluster_key": "event-1",
        "observation_id": "observation-1",
        "notification_status": "eligible",
        "title": "官方事件",
        "source_url": "https://example.test/source/official-1",
    }
    monkeypatch.setattr(scheduled_delivery, "_pick_event", lambda *_args: event)
    monkeypatch.setattr(scheduled_delivery, "write_event_lock_key", lambda *_args: None)
    captured = {}

    class FakeLedger:
        def delivery_history(self):
            return []

        def record_delivery(self, payload, **_kwargs):
            return payload

        def save(self):
            return None

    monkeypatch.setattr(scheduled_delivery, "EventLedger", FakeLedger)

    def sender(**kwargs):
        captured.update(kwargs)
        return (TextDeliveryReceipt(
            kwargs["alert_id"], kwargs["release_id"], kwargs["snapshot_id"],
            "hash", "delivered", message_id=1, observation_id=kwargs.get("observation_id", ""),
        ),)

    monkeypatch.setattr(
        scheduled_delivery,
        "send_text_briefs_audited",
        sender,
    )
    scheduled_delivery.send(snapshot_path, "morning", manifest_path)
    text = output.read_text(encoding="utf-8")
    assert "sent=true" in text
    assert "delivery_mode=text" in text
    assert captured["target_url"] == alert_mini_app_url(
        "https://example.test/app",
        alert_id="event-1",
        release_id="release-1",
        snapshot_id="market-12345678",
        observation_id="obs-1",
    )


def test_scheduled_market_delivery_does_not_require_fresh_research(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "market.json"
    manifest_path = tmp_path / "release-manifest.json"
    snapshot_path.write_text(
        json.dumps({"snapshot_id": "market-12345678", "quotes": [], "indices": [], "briefing": {}}),
        encoding="utf-8",
    )
    manifest_path.write_text("{}", encoding="utf-8")
    output = tmp_path / "output"
    _patch_ready(monkeypatch, output)
    captured: dict[str, object] = {}

    def gate(**kwargs):
        captured.update(kwargs)
        return ReleaseGateResult(True, release_id="release-1", snapshot_id="market-12345678")

    monkeypatch.setattr(scheduled_delivery, "verify_release_for_delivery", gate)
    monkeypatch.setattr(
        scheduled_delivery,
        "send_text_briefs_audited",
        lambda **kwargs: (TextDeliveryReceipt(
            kwargs["alert_id"], kwargs["release_id"], kwargs["snapshot_id"],
            "hash", "delivered", message_id=3, observation_id=kwargs.get("observation_id", ""),
        ),),
    )
    scheduled_delivery.send(snapshot_path, "morning", manifest_path)
    assert captured["require_production_research"] is False
    text = output.read_text(encoding="utf-8")
    assert "notification_expected=false" in text
    assert "notification_status=suppressed" in text
    assert "notification_reason=no_eligible_candidate" in text
    assert "sent=true" not in text


def test_scheduled_market_delivery_falls_back_after_all_candidates_are_suppressed(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "market.json"
    manifest_path = tmp_path / "release-manifest.json"
    snapshot_path.write_text(
        json.dumps({"snapshot_id": "market-12345678", "quotes": [], "indices": [], "briefing": {}}),
        encoding="utf-8",
    )
    manifest_path.write_text("{}", encoding="utf-8")
    output = tmp_path / "output"
    _patch_ready(monkeypatch, output)
    candidate = {
        "source_key": "financialjuice",
        "notification_status": "eligible",
        "vendor_priority_notification": True,
        "vendor_importance": 9,
        "notification_id": "fj-already-covered",
        "event": "已送達的 FJ 事件。",
        "source_url": "https://example.test/source/fj-covered",
    }

    class FakeLedger:
        delivery_claims = {}

        @staticmethod
        def delivery_history():
            return []

        @staticmethod
        def theme_decision(_event):
            return {"allowed": False, "reason": "same_theme_within_2h"}

        @staticmethod
        def record_decision(*_args, **_kwargs):
            return None

        @staticmethod
        def claim_notification(*_args, **_kwargs):
            return {"status": "claimed", "pending_recipient_hashes": ["hash"]}

        @staticmethod
        def record_delivery(*_args, **_kwargs):
            return None

        @staticmethod
        def save():
            return None

    monkeypatch.setattr(scheduled_delivery, "EventLedger", FakeLedger)
    monkeypatch.setattr(scheduled_delivery, "_pick_event", lambda *_args, **_kwargs: candidate)
    monkeypatch.setattr(
        scheduled_delivery,
        "send_text_briefs_audited",
        lambda **kwargs: (TextDeliveryReceipt(
            kwargs["alert_id"], kwargs["release_id"], kwargs["snapshot_id"],
            "hash", "delivered", message_id=2, observation_id=kwargs.get("observation_id", ""),
        ),),
    )

    scheduled_delivery.send(snapshot_path, "us_open", manifest_path)
    text = output.read_text(encoding="utf-8")
    assert "sent=false" in text
    assert "notification_status=suppressed" in text
    assert "notification_reason=same_theme_within_2h" in text


def test_scheduled_delivery_does_not_send_generic_fallback_after_fj_already_delivered(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "market.json"
    snapshot_path.write_text(
        json.dumps({"snapshot_id": "market-12345678", "quotes": [], "indices": [], "briefing": {}}),
        encoding="utf-8",
    )


def test_scheduled_delivery_blocks_missing_source_url_before_sender(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "market.json"
    manifest_path = tmp_path / "release-manifest.json"
    snapshot_path.write_text(
        json.dumps({"snapshot_id": "market-12345678", "quotes": [], "indices": [], "briefing": {}}),
        encoding="utf-8",
    )
    manifest_path.write_text("{}", encoding="utf-8")
    output = tmp_path / "output"
    _patch_ready(monkeypatch, output)
    event = {
        "source_key": "official",
        "event_cluster_key": "event-without-source",
        "observation_id": "observation-without-source",
        "notification_status": "eligible",
        "title": "官方事件",
    }
    monkeypatch.setattr(scheduled_delivery, "_pick_event", lambda *_args: event)
    monkeypatch.setattr(
        scheduled_delivery,
        "send_text_briefs_audited",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("sender must not be called")),
    )

    scheduled_delivery.send(snapshot_path, "morning", manifest_path)

    text = output.read_text(encoding="utf-8")
    assert "sent=false" in text
    assert "notification_reason=ledger_source_url_invalid" in text
    manifest_path.write_text("{}", encoding="utf-8")
    output = tmp_path / "output"
    _patch_ready(monkeypatch, output)
    candidate = {
        "source_key": "financialjuice",
        "notification_status": "eligible",
            "vendor_priority_notification": True,
            "vendor_importance": 9,
            "delivery_policy": "fj_priority",
            "notification_id": "fj-already-delivered",
            "canonical_fact_key": "financialjuice-fact:delivered",
            "source_identity_verified": True,
            "public_signal_eligible": True,
            "freshness_status": "fresh",
        "event": "已送達的 FJ 事件。",
        "source_url": "https://example.test/source/fj-delivered",
    }

    class FakeLedger:
        delivery_claims = {}

        @staticmethod
        def delivery_history():
            return []

        @staticmethod
        def theme_decision(_event):
            return {"allowed": True}

        @staticmethod
        def record_decision(*_args, **_kwargs):
            return None

        @staticmethod
        def save():
            return None

    monkeypatch.setattr(scheduled_delivery, "EventLedger", FakeLedger)
    monkeypatch.setattr(scheduled_delivery, "_pick_event", lambda *_args, **_kwargs: candidate)
    monkeypatch.setattr(
        scheduled_delivery,
        "decide_alert_budget",
        lambda *_args: {"allowed": True, "reason": "budget_available", "event_key": "fj-already-delivered"},
    )
    monkeypatch.setattr(
        scheduled_delivery,
        "deliver_financialjuice_event",
        lambda *_args, **_kwargs: {
            "status": "already_delivered",
            "notification_key": "financialjuice:already-delivered",
            "receipts": [],
        },
    )

    def fail_if_called(**_kwargs):
        raise AssertionError("an already-delivered FJ event must not create a generic Telegram fallback")

    monkeypatch.setattr(scheduled_delivery, "send_text_briefs_audited", fail_if_called)
    scheduled_delivery.send(snapshot_path, "us_open", manifest_path)
    text = output.read_text(encoding="utf-8")
    assert "sent=false" in text
    assert "notification_reason=already_delivered" in text
    assert "市場簡報｜本輪無觸發" not in text


def test_scheduled_delivery_emits_financialjuice_release_delivery_trace(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "market.json"
    manifest_path = tmp_path / "release-manifest.json"
    snapshot_path.write_text(
        json.dumps({"snapshot_id": "market-12345678", "quotes": [], "indices": [], "briefing": {}}),
        encoding="utf-8",
    )
    manifest_path.write_text("{}", encoding="utf-8")
    output = tmp_path / "output"
    _patch_ready(monkeypatch, output)
    event = {
        "source_key": "financialjuice",
        "event_cluster_key": "cluster-1",
        "observation_id": "fj-observation-1",
        "observation_id_hash": "a" * 64,
        "item_id": "item-1",
        "title": "據《The...",
        "vendor_original_headline": "Iran says U.S. strikes telecommunications infrastructure.",
        "vendor_importance": 9,
        "notification_status": "eligible",
        "vendor_priority_notification": True,
        "delivery_policy": "fj_priority",
        "canonical_fact_key": "financialjuice-fact:trace",
        "source_identity_verified": True,
        "public_signal_eligible": True,
        "prstk_risk": {"prstk_risk_level": "R2"},
        "notification_reason": "vendor_priority_importance_ge_9",
        "parser_version": "financialjuice-compound-v1",
        "received_at": "2026-08-21T01:01:00+00:00",
        "source_published_at": datetime.now(UTC).isoformat(),
        "freshness_status": "fresh",
        "alert_eligible": True,
        "source_url": "https://example.test/source/fj-1",
    }
    monkeypatch.setattr(scheduled_delivery, "_pick_event", lambda *_args: event)
    monkeypatch.setattr(
        scheduled_delivery,
        "decide_alert_budget",
        lambda *_args: {"allowed": True, "reason": "material_change", "event_key": "cluster-1"},
    )
    captured: dict[str, object] = {}

    def sender(**kwargs):
        captured.update(kwargs)
        return (TextDeliveryReceipt(
            kwargs["alert_id"], kwargs["release_id"], kwargs["snapshot_id"],
            "hash", "delivered", message_id=2, observation_id=kwargs.get("observation_id", ""),
        ),)

    monkeypatch.setattr(scheduled_delivery, "send_text_briefs_audited", sender)
    monkeypatch.setattr(scheduled_delivery, "write_event_lock_key", lambda *_args: None)
    recorded: dict = {}

    class FakeLedger:
        def delivery_history(self):
            return []

        def record_delivery(self, payload, **_kwargs):
            recorded.update(payload)
            return payload

        def save(self):
            return None

    monkeypatch.setattr(scheduled_delivery, "EventLedger", FakeLedger)
    scheduled_delivery.send(snapshot_path, "morning", manifest_path)
    text = output.read_text(encoding="utf-8")
    assert "financialjuice_delivery_trace=" in text
    assert "release-1" in text
    assert "market-12345678" in text
    assert "delivery_status=delivered" in text
    assert "failed_recipient_hashes=\n" in text or "failed_recipient_hashes=\r\n" in text
    assert recorded["release_id"] == "release-1"
    assert recorded["snapshot_id"] == "market-12345678"
    assert recorded["delivery_status"] == "delivered"
    assert recorded["observation_id_hash"] == "a" * 64
    assert recorded["notification_key"].startswith("financialjuice:")
    assert recorded["delivery_receipts"][0]["delivery_status"] == "delivered"
    assert "據《The" not in captured["text"]
    assert "…" not in captured["text"]
    assert "..." not in captured["text"]
    assert str(captured["text"]).count("｜") == 1
    assert len(captured["text"]) <= 60


def test_scheduled_financialjuice_all_recipient_failure_is_fail_closed(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "market.json"
    manifest_path = tmp_path / "release-manifest.json"
    snapshot_path.write_text(
        json.dumps({"snapshot_id": "market-12345678", "quotes": [], "indices": [], "briefing": {}}),
        encoding="utf-8",
    )
    manifest_path.write_text("{}", encoding="utf-8")
    output = tmp_path / "output"
    _patch_ready(monkeypatch, output)
    event = {
        "source_key": "financialjuice",
        "event_cluster_key": "cluster-failed",
        "observation_id": "fj-observation-failed",
        "notification_status": "eligible",
        "vendor_priority_notification": True,
        "vendor_importance": 9,
        "title": "Oil supply risk",
        "delivery_policy": "fj_priority",
        "canonical_fact_key": "financialjuice-fact:failed",
        "source_identity_verified": True,
        "public_signal_eligible": True,
        "freshness_status": "fresh",
        "source_url": "https://example.test/source/fj-failed",
    }
    monkeypatch.setattr(scheduled_delivery, "_pick_event", lambda *_args: event)
    monkeypatch.setattr(
        scheduled_delivery,
        "decide_alert_budget",
        lambda *_args: {"allowed": True, "reason": "budget_available", "event_key": "cluster-failed"},
    )
    monkeypatch.setattr(scheduled_delivery, "deliver_financialjuice_event", lambda *_args, **_kwargs: {
        "status": "failed",
        "receipts": [{"recipient_hash": "hash", "delivery_status": "failed"}],
        "reasons": ["delivery_exception"],
    })
    monkeypatch.setattr(scheduled_delivery, "write_event_lock_key", lambda *_args: None)

    class FakeLedger:
        def delivery_history(self):
            return []

        def record_delivery(self, *_args, **_kwargs):
            raise AssertionError("failed FJ delivery must not be recorded as delivered")

        def save(self):
            return None

    monkeypatch.setattr(scheduled_delivery, "EventLedger", FakeLedger)
    monkeypatch.setattr(scheduled_delivery, "get_settings", _settings)

    with pytest.raises(RuntimeError, match="FinancialJuice delivery failed"):
        scheduled_delivery.send(snapshot_path, "morning", manifest_path)
    text = output.read_text(encoding="utf-8")
    assert "sent=false" in text
    assert "delivery_status=failed" in text
    assert "reason=all_recipients_failed" in text


def test_scheduled_delivery_records_text_delivery_failure(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "market.json"
    manifest_path = tmp_path / "release-manifest.json"
    snapshot_path.write_text(
        json.dumps({"snapshot_id": "market-12345678", "quotes": [], "indices": [], "briefing": {}}),
        encoding="utf-8",
    )
    manifest_path.write_text("{}", encoding="utf-8")
    output = tmp_path / "output"
    _patch_ready(monkeypatch, output)
    monkeypatch.setattr(
        scheduled_delivery,
        "_pick_event",
        lambda *_args: {
            "source_key": "official",
            "event_key": "official-1",
            "title": "官方事件。",
            "notification_status": "eligible",
            "source_url": "https://example.test/source/official-failure",
        },
    )
    monkeypatch.setattr(
        scheduled_delivery,
        "send_text_briefs_audited",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("text failure")),
    )
    scheduled_delivery.send(snapshot_path, "morning", manifest_path)
    text = output.read_text(encoding="utf-8")
    assert "sent=false" in text
    assert "reason=text_delivery_failed" in text


def test_scheduled_delivery_blocks_quality_ineligible_event_before_renderer(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "market.json"
    manifest_path = tmp_path / "release-manifest.json"
    snapshot_path.write_text(
        json.dumps({"snapshot_id": "market-12345678", "quotes": [], "indices": [], "briefing": {}}),
        encoding="utf-8",
    )
    manifest_path.write_text("{}", encoding="utf-8")
    output = tmp_path / "output"
    _patch_ready(monkeypatch, output)
    monkeypatch.setattr(
        scheduled_delivery,
        "_pick_event",
        lambda *_args: {
            "event_key": "stale-event",
            "title": "stale event",
            "alert_eligible": False,
            "quality_reasons": ["quote_stale"],
        },
    )
    scheduled_delivery.send(snapshot_path, "morning", manifest_path)
    text = output.read_text(encoding="utf-8")
    assert "sent=false" in text
    assert "delivery_status=suppressed" in text
    assert "reason=quote_stale" in text
def test_creator_records_are_loaded_only_from_sanitized_external_path(tmp_path, monkeypatch):
    records = tmp_path / "creator-records.json"
    records.write_text(json.dumps({"records": [{"source": "haojiao", "title": "public"}]}), encoding="utf-8")
    monkeypatch.setenv("CREATOR_RECORDS_PATH", str(records))
    assert _load_creator_records() == []


def test_creator_records_inside_site_are_rejected(tmp_path, monkeypatch):
    site = tmp_path / "site"
    site.mkdir()
    records = site / "creator.json"
    records.write_text("[]", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CREATOR_RECORDS_PATH", str(records))
    assert _load_creator_records() == []


def test_creator_records_with_private_body_or_parser_failure_are_rejected(tmp_path, monkeypatch):
    records = tmp_path / "creator-records.json"
    records.write_text(
        json.dumps({"records": [
            {"source": "gooaye", "title": "private", "body": "raw"},
            {"source": "gooaye", "title": "unsupported", "parse_status": "unsupported_template"},
            {"source": "gooaye", "title": "safe", "parse_status": "parsed"},
        ]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CREATOR_RECORDS_PATH", str(records))
    assert _load_creator_records() == []


def test_creator_input_failure_is_not_reported_as_no_event(tmp_path, monkeypatch):
    from src.scheduled_delivery import _creator_input_failures

    monkeypatch.setenv("CREATOR_NOTIFICATION_ENABLED", "true")
    monkeypatch.setenv("CREATOR_RECORDS_PATH", str(tmp_path / "missing.json"))
    assert _creator_input_failures() == {}


def test_creator_filtered_records_are_reported_as_parse_failure(tmp_path, monkeypatch):
    from src.scheduled_delivery import _creator_input_failures

    records = tmp_path / "creator-records.json"
    records.write_text(json.dumps({"records": [{
        "source": "haojiao",
        "parse_status": "unsupported_template",
    }]}), encoding="utf-8")
    monkeypatch.setenv("CREATOR_NOTIFICATION_ENABLED", "true")
    monkeypatch.setenv("CREATOR_RECORDS_PATH", str(records))
    assert _creator_input_failures() == {}


def test_prepare_binds_creator_records_to_the_published_snapshot(tmp_path, monkeypatch):
    records = tmp_path / "creator-records.json"
    records.write_text(json.dumps([{"source": "gooaye", "title": "public"}]), encoding="utf-8")
    snapshot_path = tmp_path / "market.json"
    monkeypatch.setenv("CREATOR_RECORDS_PATH", str(records))
    monkeypatch.setattr(scheduled_delivery, "build_market_snapshot", lambda: {"snapshot_id": "m-1", "quotes": [], "indices": []})
    monkeypatch.setattr(scheduled_delivery, "build_briefing_snapshot", lambda snapshot, _slot: {"creator_release": snapshot.get("creator_insights")})
    monkeypatch.setattr(scheduled_delivery, "write_snapshot", lambda snapshot, path: (path.write_text(json.dumps(snapshot), encoding="utf-8"), True)[1])
    monkeypatch.setattr(scheduled_delivery, "_pick_event", lambda *_args: None)
    monkeypatch.setattr(scheduled_delivery, "briefing_correlation", lambda *_args: {"trace_id": "t", "snapshot_id": "m-1", "observation_id": ""})
    monkeypatch.setattr(scheduled_delivery, "merge_published_metadata", lambda *_args, **_kwargs: True)
    scheduled_delivery.prepare("morning", snapshot_path)
    published = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert "creator_insights" not in published
    assert published["source_health"]["sources"] == []


def test_prepare_binds_sanitized_external_observations_to_snapshot(tmp_path, monkeypatch):
    records = tmp_path / "external.json"
    records.write_text(json.dumps({"observations": [{
        "observation_id": "fj-1", "source": "financialjuice",
        "headline": "Public headline", "source_identity_verified": True, "public_safe": True,
    }]}), encoding="utf-8")
    snapshot_path = tmp_path / "market.json"
    monkeypatch.setenv("EXTERNAL_OBSERVATIONS_PATH", str(records))
    monkeypatch.setattr(scheduled_delivery, "build_market_snapshot", lambda: {
        "snapshot_id": "m-1", "quotes": [], "indices": [],
        "source_health": {"status": "healthy", "sources": [], "data_gaps": [],
                           "missing_source_count": 0, "runtime_failure_count": 0,
                           "configuration_missing_count": 0, "state_counts": {},
                           "observability": {}},
    })
    monkeypatch.setattr(scheduled_delivery, "build_briefing_snapshot", lambda snapshot, _slot: {
        "external_observations": snapshot.get("external_observations"),
    })
    monkeypatch.setattr(scheduled_delivery, "write_snapshot", lambda snapshot, path: (path.write_text(json.dumps(snapshot), encoding="utf-8"), True)[1])
    monkeypatch.setattr(scheduled_delivery, "_pick_event", lambda *_args: None)
    monkeypatch.setattr(scheduled_delivery, "briefing_correlation", lambda *_args: {"trace_id": "t", "snapshot_id": "m-1", "observation_id": ""})
    monkeypatch.setattr(scheduled_delivery, "merge_published_metadata", lambda *_args, **_kwargs: True)
    scheduled_delivery.prepare("morning", snapshot_path)
    published = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert published["external_observations"] == []
    assert published["briefing"]["external_observations"] == []
    assert published["external_source_health"]["status"] == "healthy"


def test_prepare_projects_qualifying_financialjuice_into_release_event_lane(tmp_path, monkeypatch):
    records = tmp_path / "external.json"
    records.write_text(json.dumps({"observations": [{
        "observation_id": "fj-9", "item_id": "item-9", "source": "financialjuice",
        "original_headline": "Oil supply risk", "event_type": "energy", "vendor_importance": 9,
        "source_url": "https://financialjuice.com/item/9", "source_identity_verified": True, "public_safe": True,
        "source_published_at": datetime.now(UTC).isoformat(),
    }]}), encoding="utf-8")
    snapshot_path = tmp_path / "market.json"
    monkeypatch.setenv("EXTERNAL_OBSERVATIONS_PATH", str(records))
    monkeypatch.setattr(scheduled_delivery, "build_market_snapshot", lambda: {
        "snapshot_id": "m-1", "quotes": [], "indices": [], "events": {"items": []},
        "source_health": {"status": "healthy", "sources": [], "data_gaps": [],
                           "missing_source_count": 0, "runtime_failure_count": 0,
                           "configuration_missing_count": 0, "state_counts": {},
                           "observability": {}},
    })
    monkeypatch.setattr(scheduled_delivery, "build_briefing_snapshot", lambda snapshot, _slot: {
        "external_event_notifications": snapshot.get("financialjuice_priority_decisions"),
    })
    def write_snapshot(snapshot, path):
        path.write_text(json.dumps(snapshot), encoding="utf-8")
        return True
    monkeypatch.setattr(scheduled_delivery, "write_snapshot", write_snapshot)
    monkeypatch.setattr(scheduled_delivery, "_pick_event", lambda *_args: None)
    monkeypatch.setattr(scheduled_delivery, "briefing_correlation", lambda *_args: {"trace_id": "t", "snapshot_id": "m-1", "observation_id": ""})
    monkeypatch.setattr(scheduled_delivery, "merge_published_metadata", lambda *_args, **_kwargs: True)
    scheduled_delivery.prepare("morning", snapshot_path)
    published = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert published["financialjuice_priority_decisions"][0]["vendor_priority_notification"] is True
    assert published["financialjuice_priority_events"][0]["notification_status"] == "eligible"
    assert published["events"]["items"][0]["source_key"] == "financialjuice"


def test_prepare_removes_stale_blocked_financialjuice_event_rows(tmp_path, monkeypatch):
    records = tmp_path / "external.json"
    records.write_text(json.dumps({"observations": []}), encoding="utf-8")
    snapshot_path = tmp_path / "market.json"
    monkeypatch.setenv("EXTERNAL_OBSERVATIONS_PATH", str(records))
    monkeypatch.setattr(scheduled_delivery, "build_market_snapshot", lambda: {
        "snapshot_id": "m-clean-1", "quotes": [], "indices": [],
        "events": {"items": [
            {"kind": "external_event", "source": "FinancialJuice", "source_key": "financialjuice",
             "observation_id": "stale-fj", "public_signal_eligible": False,
             "title": "PR run failed: FinancialJuice semantics"},
            {"kind": "market_signal", "title": "Keep official signal"},
        ]},
        "source_health": {"status": "healthy", "sources": [], "data_gaps": [],
                           "missing_source_count": 0, "runtime_failure_count": 0,
                           "configuration_missing_count": 0, "state_counts": {},
                           "observability": {}},
    })
    monkeypatch.setattr(scheduled_delivery, "build_briefing_snapshot", lambda snapshot, _slot: {
        "external_event_notifications": snapshot.get("financialjuice_priority_decisions"),
    })
    monkeypatch.setattr(scheduled_delivery, "write_snapshot", lambda snapshot, path: path.write_text(json.dumps(snapshot), encoding="utf-8") or True)
    monkeypatch.setattr(scheduled_delivery, "_pick_event", lambda *_args: None)
    monkeypatch.setattr(scheduled_delivery, "briefing_correlation", lambda *_args: {"trace_id": "t", "snapshot_id": "m-clean-1", "observation_id": ""})
    monkeypatch.setattr(scheduled_delivery, "merge_published_metadata", lambda *_args, **_kwargs: True)
    scheduled_delivery.prepare("morning", snapshot_path)
    published = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert published["events"]["items"] == [{"kind": "market_signal", "title": "Keep official signal"}]


def test_prepare_fetches_sanitized_railway_observations_into_release(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "market.json"
    monkeypatch.delenv("EXTERNAL_OBSERVATIONS_PATH", raising=False)
    monkeypatch.setenv("RAILWAY_STATUS_URL", "https://railway.example/status")
    monkeypatch.setenv("RAILWAY_STATUS_SHARED_SECRET", "test-secret")
    monkeypatch.setattr(scheduled_delivery, "load_railway_observations", lambda: ([{
        "observation_id": "fj-remote", "source": "financialjuice", "content_origin": "financialjuice",
        "headline": "Public remote headline", "public_safe": True,
    }, {
        "observation_id": "jenny-remote", "source": "jenny", "content_origin": "jenny",
        "headline": "Public creator headline", "public_safe": True,
    }], {"status": "ready", "count": 2, "rejected_count": 0}))
    monkeypatch.setattr(scheduled_delivery, "build_market_snapshot", lambda: {
        "snapshot_id": "m-1", "quotes": [], "indices": [],
        "source_health": {"status": "healthy", "sources": [], "data_gaps": [],
                           "missing_source_count": 0, "runtime_failure_count": 0,
                           "configuration_missing_count": 0, "state_counts": {},
                           "observability": {}},
    })
    monkeypatch.setattr(scheduled_delivery, "build_briefing_snapshot", lambda snapshot, _slot: {
        "external_observations": snapshot.get("external_observations"),
    })
    monkeypatch.setattr(scheduled_delivery, "write_snapshot", lambda snapshot, path: (path.write_text(json.dumps(snapshot), encoding="utf-8"), True)[1])
    monkeypatch.setattr(scheduled_delivery, "_pick_event", lambda *_args: None)
    monkeypatch.setattr(scheduled_delivery, "briefing_correlation", lambda *_args: {"trace_id": "t", "snapshot_id": "m-1", "observation_id": ""})
    monkeypatch.setattr(scheduled_delivery, "merge_published_metadata", lambda *_args, **_kwargs: True)
    scheduled_delivery.prepare("morning", snapshot_path)
    published = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert [row["observation_id"] for row in published["external_observations"]] == ["jenny-remote"]
    assert [row["observation_id"] for row in published["financialjuice_observations"]] == ["fj-remote"]
    assert published["external_source_health"]["provider_status"] == "ready"
    assert published["external_source_health"]["status"] == "healthy"


def test_prepare_keeps_local_fallback_when_railway_export_fails(tmp_path, monkeypatch):
    records = tmp_path / "external.json"
    records.write_text(json.dumps({"observations": [{
        "observation_id": "fj-local", "source": "financialjuice", "original_headline": "Local oil update", "source_identity_verified": True, "public_safe": True,
    }]}), encoding="utf-8")
    snapshot_path = tmp_path / "market.json"
    monkeypatch.setenv("EXTERNAL_OBSERVATIONS_PATH", str(records))
    monkeypatch.setenv("RAILWAY_STATUS_URL", "https://railway.example/status")
    monkeypatch.setenv("RAILWAY_STATUS_SHARED_SECRET", "test-secret")
    monkeypatch.setattr(scheduled_delivery, "load_railway_observations", lambda: ([], {"status": "failed", "reason": "http_503", "rejected_count": 0}))
    monkeypatch.setattr(scheduled_delivery, "build_market_snapshot", lambda: {
        "snapshot_id": "m-1", "quotes": [], "indices": [],
        "source_health": {"status": "healthy", "sources": [], "data_gaps": [],
                           "missing_source_count": 0, "runtime_failure_count": 0,
                           "configuration_missing_count": 0, "state_counts": {},
                           "observability": {}},
    })
    monkeypatch.setattr(scheduled_delivery, "build_briefing_snapshot", lambda snapshot, _slot: {
        "external_observations": snapshot.get("external_observations"),
    })
    monkeypatch.setattr(scheduled_delivery, "write_snapshot", lambda snapshot, path: (path.write_text(json.dumps(snapshot), encoding="utf-8"), True)[1])
    monkeypatch.setattr(scheduled_delivery, "_pick_event", lambda *_args: None)
    monkeypatch.setattr(scheduled_delivery, "briefing_correlation", lambda *_args: {"trace_id": "t", "snapshot_id": "m-1", "observation_id": ""})
    monkeypatch.setattr(scheduled_delivery, "merge_published_metadata", lambda *_args, **_kwargs: True)
    scheduled_delivery.prepare("morning", snapshot_path)
    published = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert published["external_observations"] == []
    assert published["external_source_health"]["status"] == "partial"
    assert published["external_source_health"]["issues"] == ["http_503"]
