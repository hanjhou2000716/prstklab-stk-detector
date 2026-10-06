from __future__ import annotations

from src.notification_terminal import (
    append_summary,
    evaluate_official_terminal,
    evaluate_scheduled_terminal,
)


def official(**updates: str) -> dict[str, str]:
    values = {
        "NOTIFICATION_REQUESTED": "true",
        "NOTIFICATION_EXPECTED": "true",
        "NOTIFICATION_STATUS": "candidate_ready",
        "SCAN_STATUS": "success",
        "SHOULD_SEND": "true",
        "PREPARED_RELEASE_STATUS": "prepared_release_current",
        "DEPLOYMENT_AVAILABLE": "true",
        "RELEASE_GATE_ALLOWED": "true",
        "SEND_OUTCOME": "success",
        "SEND_STATUS": "delivered",
        "DELIVERY_STATUS": "delivered",
        "DELIVERED_COUNT": "2",
        "FAILED_COUNT": "0",
        "RECEIPT_OUTCOME": "success",
        "SEND_SENT": "true",
        "LEDGER_OUTCOME": "success",
        "RECONCILED_DEPLOYMENT_AVAILABLE": "true",
        "RECONCILED_RELEASE_GATE_OUTCOME": "success",
        "DURABLE_RECEIPT_VERIFIED": "true",
    }
    values.update(updates)
    return values


def scheduled(**updates: str) -> dict[str, str]:
    values = {
        "NOTIFICATION_REQUESTED": "true",
        "NOTIFICATION_EXPECTED": "true",
        "DELIVERY_OBLIGATION": "report_required",
        "PREPARE_OUTCOME": "success",
        "PREPARE_READY": "true",
        "PREPARED_CURRENT": "true",
        "PAGES_DEPLOYMENT_AVAILABLE": "true",
        "GATE_ALLOWED": "true",
        "SEND_OUTCOME": "success",
        "SEND_STATUS": "ready",
        "DELIVERY_STATUS": "delivered",
        "DELIVERED_COUNT": "2",
        "FAILED_COUNT": "0",
        "LEDGER_PERSIST_OUTCOME": "success",
        "RECONCILED_DEPLOYMENT_VERIFIED": "true",
        "RECONCILED_GATE_ALLOWED": "true",
        "RECEIPT_ENDPOINT_CONFIGURED": "true",
        "RECEIPT_CALLBACK_OUTCOME": "success",
        "DURABLE_RECEIPT_VERIFIED": "true",
    }
    values.update(updates)
    return values


def test_official_theme_suppression_has_a_reason_and_is_not_a_delivery() -> None:
    result = evaluate_official_terminal(official(
        SEND_STATUS="policy_suppressed",
        SEND_NOTIFICATION_EXPECTED="false",
        SEND_REASON="theme:same_theme_unchanged",
        NOTIFICATION_REASON="theme:same_theme_unchanged",
        SEND_OUTCOME="success",
        DELIVERY_STATUS="",
        DELIVERED_COUNT="0",
    ))

    assert result["status"] == "policy_suppressed"
    assert result["reason"] == "theme:same_theme_unchanged"
    assert result["expected"] is False
    assert result["failure"] is False


def test_official_preflight_policy_suppression_without_sender_is_not_a_failure() -> None:
    result = evaluate_official_terminal(official(
        SHOULD_SEND="false",
        NOTIFICATION_EXPECTED="false",
        NOTIFICATION_STATUS="policy_suppressed",
        NOTIFICATION_REASON="theme:same_theme_unchanged",
        SEND_NOTIFICATION_EXPECTED="true",
        SEND_STATUS="",
        SEND_OUTCOME="skipped",
    ))

    assert result["status"] == "policy_suppressed"
    assert result["reason"] == "theme:same_theme_unchanged"
    assert result["expected"] is False
    assert result["failure"] is False




def test_official_known_daily_budget_suppression_is_not_missing_delivery() -> None:
    result = evaluate_official_terminal(official(
        SHOULD_SEND="false",
        NOTIFICATION_EXPECTED="false",
        NOTIFICATION_STATUS="policy_suppressed",
        NOTIFICATION_REASON="event_policy:event_daily_budget_exhausted",
        SEND_STATUS="policy_suppressed",
        SEND_NOTIFICATION_EXPECTED="false",
        SEND_REASON="event_policy:event_daily_budget_exhausted",
        SEND_OUTCOME="success",
    ))
    assert result["status"] == "policy_suppressed"
    assert result["expected"] is False
    assert result["failure"] is False


def test_official_unknown_budget_suppression_fails_closed() -> None:
    result = evaluate_official_terminal(official(
        SHOULD_SEND="false",
        NOTIFICATION_EXPECTED="false",
        NOTIFICATION_STATUS="policy_suppressed",
        NOTIFICATION_REASON="alert_budget:unrecognized_reason",
        SEND_STATUS="policy_suppressed",
        SEND_NOTIFICATION_EXPECTED="false",
        SEND_REASON="alert_budget:unrecognized_reason",
        SEND_OUTCOME="success",
    ))
    assert result["status"] == "blocked"
    assert result["failure"] is True


def test_official_idempotency_cache_is_not_a_receipt() -> None:
    result = evaluate_official_terminal(official(IDEMPOTENCY_CACHE_HIT="true"))

    assert result["failure"] is True
    assert result["status"] == "failed"
    assert result["reason"] == "idempotency_cache_without_durable_recipient_receipt"
    assert result["no_resend"] is True


def test_official_durable_receipt_suppresses_duplicate_delivery() -> None:
    result = evaluate_official_terminal(official(
        SHOULD_SEND="false",
        NOTIFICATION_EXPECTED="false",
        NOTIFICATION_STATUS="already_delivered",
        NOTIFICATION_REASON="already_delivered",
        SEND_STATUS="",
        SEND_OUTCOME="skipped",
        IDEMPOTENCY_CACHE_HIT="true",
        DURABLE_RECEIPT_VERIFIED="true",
    ))

    assert result["status"] == "already_delivered"
    assert result["failure"] is False



def test_official_already_delivered_without_receipt_proof_fails_closed() -> None:
    result = evaluate_official_terminal(official(
        SHOULD_SEND="false",
        NOTIFICATION_EXPECTED="false",
        NOTIFICATION_STATUS="already_delivered",
        NOTIFICATION_REASON="already_delivered",
        SEND_STATUS="",
        SEND_OUTCOME="skipped",
        IDEMPOTENCY_CACHE_HIT="true",
        DURABLE_RECEIPT_VERIFIED="false",
    ))

    assert result["status"] == "failed"
    assert result["reason"] == "already_delivered_without_durable_recipient_receipt"
    assert result["expected"] is True
    assert result["failure"] is True
    assert result["no_resend"] is True


def test_official_delivery_requires_every_persistent_stage() -> None:
    complete = evaluate_official_terminal(official())
    missing_receipt = evaluate_official_terminal(official(RECEIPT_OUTCOME="failure"))
    incomplete_reconciliation = evaluate_official_terminal(
        official(RECONCILED_RELEASE_GATE_OUTCOME="skipped")
    )

    assert complete["status"] == "delivered"
    assert complete["failure"] is False
    assert missing_receipt["failure"] is True
    assert missing_receipt["no_resend"] is True
    assert incomplete_reconciliation["status"] == "delivered_reconciliation_incomplete"
    assert incomplete_reconciliation["no_resend"] is True


def test_official_queue_failure_preserves_root_cause_before_scan_failure_fallback() -> None:
    result = evaluate_official_terminal(official(
        QUEUE_STATUS="failed",
        WRITER_QUEUE_OUTCOME="failure",
        WRITER_QUEUE_ERROR_CODE="writer_queue_timeout",
        WRITER_QUEUE_BLOCKER_RUN_IDS="1234",
        SCAN_STATUS="not_run",
        SEND_OUTCOME="skipped",
        SEND_SENT="false",
        DELIVERED_COUNT="0",
    ))

    assert result["status"] == "failed"
    assert result["reason"] == "writer_queue_timeout"
    assert result["expected"] is True
    assert result["no_resend"] is False
    assert result["writer_queue_blocker_run_ids"] == "1234"


def test_official_send_requires_a_reread_durable_claim() -> None:
    result = evaluate_official_terminal(official(DURABLE_RECEIPT_VERIFIED="false"))

    assert result["status"] == "delivered_reconciliation_incomplete"
    assert result["reason"] == "durable_recipient_receipt_unverified_do_not_resend"
    assert result["no_resend"] is True


def test_official_failed_scan_cannot_be_reported_as_no_event() -> None:
    result = evaluate_official_terminal(official(
        SCAN_STATUS="failure",
        SHOULD_SEND="false",
        NOTIFICATION_EXPECTED="false",
        NOTIFICATION_STATUS="not_attempted",
    ))

    assert result["status"] == "failed"
    assert result["failure"] is True
    assert result["reason"] == "official_preflight_failure"


def test_official_incomplete_candidate_remains_blocked() -> None:
    result = evaluate_official_terminal(official(
        HARD_FAILURE="true",
        HARD_FAILURE_REASON="content_incomplete_quarantined",
        NOTIFICATION_STATUS="content_incomplete",
    ))

    assert result["status"] == "blocked"
    assert result["failure"] is True
    assert result["reason"] == "content_incomplete_quarantined"


def test_scheduled_publish_only_slots_do_not_become_delivery_failures() -> None:
    for obligation in ("expected_skip", "late_publish_only"):
        result = evaluate_scheduled_terminal(scheduled(
            DELIVERY_OBLIGATION=obligation,
            NOTIFICATION_EXPECTED="false",
            SEND_OUTCOME="skipped",
            PAGES_DEPLOYMENT_AVAILABLE="false",
        ))
        assert result["failure"] is False
        assert result["expected"] is False
        assert result["status"] == "policy_not_required_publication_unverified"


def test_scheduled_unverified_calendar_fails_closed() -> None:
    result = evaluate_scheduled_terminal(scheduled(
        DELIVERY_OBLIGATION="blocked",
        OBLIGATION_REASON="market_calendar_unavailable",
    ))

    assert result["failure"] is True
    assert result["reason"] == "market_calendar_unavailable"


def test_scheduled_delivery_requires_receipt_and_public_reconciliation() -> None:
    delivered = evaluate_scheduled_terminal(scheduled())
    callback_missing = evaluate_scheduled_terminal(scheduled(RECEIPT_CALLBACK_OUTCOME="failure"))
    receipt_endpoint_optional = evaluate_scheduled_terminal(scheduled(
        RECEIPT_ENDPOINT_CONFIGURED="false",
        RECEIPT_CALLBACK_OUTCOME="skipped",
    ))
    partial = evaluate_scheduled_terminal(scheduled(FAILED_COUNT="1"))

    assert delivered["status"] == "delivered"
    assert delivered["failure"] is False
    assert callback_missing["status"] == "delivered_reconciliation_incomplete"
    assert callback_missing["no_resend"] is True
    assert receipt_endpoint_optional["failure"] is False
    assert partial["failure"] is True
    assert partial["no_resend"] is True


def test_holiday_notice_obligation_is_a_required_deliverable() -> None:
    result = evaluate_scheduled_terminal(scheduled(
        DELIVERY_OBLIGATION="holiday_notice_required",
    ))

    assert result["status"] == "delivered"
    assert result["expected"] is True
    assert result["failure"] is False


def test_holiday_notice_partial_delivery_remains_failed_without_resend() -> None:
    result = evaluate_scheduled_terminal(scheduled(
        DELIVERY_OBLIGATION="holiday_notice_required",
        FAILED_COUNT="1",
    ))

    assert result["status"] == "failed"
    assert result["failure"] is True
    assert result["no_resend"] is True


def test_scheduled_preparation_and_expectation_mismatch_is_not_green() -> None:
    missing_obligation = evaluate_scheduled_terminal(scheduled(
        DELIVERY_OBLIGATION="undetermined",
        PREPARE_OUTCOME="success",
    ))
    missing_expectation = evaluate_scheduled_terminal(scheduled(
        NOTIFICATION_EXPECTED="false",
    ))

    assert missing_obligation["failure"] is True
    assert missing_expectation["failure"] is True


def test_scheduled_prepare_race_keeps_the_actionable_failure_reason() -> None:
    result = evaluate_scheduled_terminal(scheduled(
        DELIVERY_OBLIGATION="undetermined",
        PREPARE_OUTCOME="failure",
        PREPARE_READY="false",
        PREPARE_FAILURE_REASON="base_changed_twice_during_prepare",
        WINDOW_DELIVERY_INTENT="notify_candidate",
    ))

    assert result["status"] == "failed"
    assert result["reason"] == "base_changed_twice_during_prepare"
    assert result["expected"] is True
    assert result["failure"] is True


def test_scheduled_release_manifest_failure_is_not_misreported_as_pages_failure() -> None:
    result = evaluate_scheduled_terminal(scheduled(
        RELEASE_MANIFEST_OUTCOME="failure",
        PREPARE_OUTCOME="success",
        PAGES_DEPLOYMENT_AVAILABLE="false",
        GATE_ALLOWED="false",
    ))

    assert result["status"] == "failed"
    assert result["reason"] == "release_manifest_failed_before_pages_deployment"
    assert result["stages"]["release_manifest"] == "failure"
    assert result["stages"]["deployment"] == "not_run"
    assert result["stages"]["public_gate"] == "not_run"


def test_scheduled_queue_timeout_keeps_root_cause_and_unrun_stages() -> None:
    result = evaluate_scheduled_terminal(scheduled(
        DELIVERY_OBLIGATION="undetermined",
        WINDOW_DELIVERY_INTENT="notify_candidate",
        WRITER_QUEUE_STATUS="failed",
        WRITER_QUEUE_OUTCOME="failure",
        WRITER_QUEUE_ERROR_CODE="writer_queue_timeout",
        WRITER_QUEUE_BLOCKER_RUN_IDS="37349718666",
        PREPARE_OUTCOME="skipped",
        SEND_OUTCOME="skipped",
        SEND_STATUS="not_attempted",
        DELIVERED_COUNT="0",
    ))

    assert result["status"] == "failed"
    assert result["reason"] == "writer_queue_timeout"
    assert result["expected"] is True
    assert result["no_resend"] is False
    assert result["writer_queue_blocker_run_ids"] == "37349718666"
    for stage in ("prepare", "deployment", "public_gate", "sender", "receipt", "ledger"):
        assert result["stages"][stage] == "not_run"


def test_scheduled_queue_failure_cannot_be_hidden_by_non_delivery_policy() -> None:
    result = evaluate_scheduled_terminal(scheduled(
        DELIVERY_OBLIGATION="late_publish_only",
        NOTIFICATION_EXPECTED="false",
        WRITER_QUEUE_STATUS="failed",
        WRITER_QUEUE_OUTCOME="failure",
        WRITER_QUEUE_ERROR_CODE="writer_queue_timeout",
        WRITER_QUEUE_BLOCKER_RUN_IDS="37349718666",
        PREPARE_OUTCOME="skipped",
        SEND_OUTCOME="skipped",
        SEND_SENT="false",
        DELIVERED_COUNT="0",
    ))

    assert result["status"] == "failed"
    assert result["failure"] is True
    assert result["expected"] is False
    assert result["reason"] == "writer_queue_timeout"
    assert result["writer_queue_blocker_run_ids"] == "37349718666"
    assert result["stages"]["writer_queue"] == "failed"
    for stage in ("prepare", "deployment", "public_gate", "sender", "receipt", "ledger"):
        assert result["stages"][stage] == "not_run"


def test_expired_schedule_is_explicit_noop_with_original_slot_context() -> None:
    result = evaluate_scheduled_terminal(scheduled(
        SCHEDULE_EXPIRY_STATUS="true",
        SCHEDULE_EXPIRY_REASON="expired_scheduled_occurrence",
        SCHEDULE_EXPIRY_SLOT_DATE="2026-10-06",
        SCHEDULE_EXPIRY_ANCHOR="2026-10-06T06:00:00+08:00",
        SCHEDULE_EXPIRY_DEADLINE="2026-10-06T06:30:00+08:00",
        SCHEDULE_EXPIRY_DETECTED_AT="2026-10-06T10:00:00+08:00",
        DELIVERY_OBLIGATION="report_required",
        NOTIFICATION_EXPECTED="true",
        WRITER_QUEUE_STATUS="not_run",
        PREPARE_OUTCOME="not_run",
    ))

    assert result["status"] == "expired_not_attempted"
    assert result["failure"] is False
    assert result["expected"] is False
    assert result["schedule_expiry"]["slot_date"] == "2026-10-06"
    assert result["schedule_expiry"]["anchor"] == "2026-10-06T06:00:00+08:00"
    assert result["schedule_expiry"]["deadline"] == "2026-10-06T06:30:00+08:00"
    assert all(stage == "not_run" for stage in result["stages"].values())


def test_expiry_marker_does_not_mask_a_real_queue_failure() -> None:
    result = evaluate_scheduled_terminal(scheduled(
        SCHEDULE_EXPIRY_STATUS="true",
        SCHEDULE_EXPIRY_REASON="expired_scheduled_occurrence",
        WRITER_QUEUE_STATUS="failed",
        WRITER_QUEUE_OUTCOME="failure",
        WRITER_QUEUE_ERROR_CODE="writer_queue_timeout",
        WRITER_QUEUE_BLOCKER_RUN_IDS="42",
        PREPARE_OUTCOME="skipped",
    ))

    assert result["status"] == "failed"
    assert result["failure"] is True
    assert result["reason"] == "writer_queue_timeout"
    assert result["stages"]["writer_queue"] == "failed"


def test_scheduled_already_sent_without_persisted_receipt_is_no_resend() -> None:
    result = evaluate_scheduled_terminal(scheduled(DURABLE_RECEIPT_VERIFIED="false"))

    assert result["status"] == "delivered_reconciliation_incomplete"
    assert result["reason"] == "durable_recipient_receipt_unverified_do_not_resend"
    assert result["no_resend"] is True


def test_scheduled_handoff_reports_child_completion_without_resending() -> None:
    result = evaluate_scheduled_terminal(scheduled(HANDOFF_STATUS="delivered", HANDOFF_RUN_ID="42"))

    assert result["status"] == "completed_by_handoff"
    assert result["failure"] is False


def test_summary_renders_the_classifier_result_as_the_final_state(tmp_path) -> None:
    result = evaluate_scheduled_terminal(scheduled(DELIVERY_OBLIGATION="late_publish_only"))
    destination = tmp_path / "summary.md"

    append_summary(str(destination), result)

    summary = destination.read_text(encoding="utf-8")
    assert "notification_status: policy_not_required" in summary
    assert "notification_expected: false" in summary
    assert "recipient_receipt" not in summary


def test_summary_identifies_release_failure_before_pages_and_public_gate(tmp_path) -> None:
    result = evaluate_scheduled_terminal(scheduled(RELEASE_MANIFEST_OUTCOME="failure"))
    destination = tmp_path / "summary.md"

    append_summary(str(destination), result)

    summary = destination.read_text(encoding="utf-8")
    assert "release_manifest / deployment / public_gate: failure / not_run / not_run" in summary


def test_queue_timeout_summary_names_blocker_and_unrun_delivery_stages(tmp_path) -> None:
    result = evaluate_scheduled_terminal(scheduled(
        DELIVERY_OBLIGATION="undetermined",
        WINDOW_DELIVERY_INTENT="notify_candidate",
        WRITER_QUEUE_STATUS="failed",
        WRITER_QUEUE_OUTCOME="failure",
        WRITER_QUEUE_ERROR_CODE="writer_queue_timeout",
        WRITER_QUEUE_BLOCKER_RUN_IDS="37349718666",
        PREPARE_OUTCOME="skipped",
        SEND_OUTCOME="skipped",
        SEND_SENT="false",
        DELIVERED_COUNT="0",
    ))
    destination = tmp_path / "summary.md"

    append_summary(str(destination), result)

    summary = destination.read_text(encoding="utf-8")
    assert "writer_queue: failed (schema=unknown; entered=unknown; error=writer_queue_timeout; blockers=37349718666" in summary
    assert "not_run / not_run / not_run / not_run / not_run / not_run" in summary


def test_expired_summary_includes_the_original_anchor_and_deadline(tmp_path) -> None:
    result = evaluate_scheduled_terminal(scheduled(
        SCHEDULE_EXPIRY_STATUS="true",
        SCHEDULE_EXPIRY_REASON="expired_scheduled_occurrence",
        SCHEDULE_EXPIRY_SLOT_DATE="2026-10-06",
        SCHEDULE_EXPIRY_ANCHOR="2026-10-06T06:00:00+08:00",
        SCHEDULE_EXPIRY_DEADLINE="2026-10-06T06:30:00+08:00",
    ))
    destination = tmp_path / "summary.md"

    append_summary(str(destination), result)

    summary = destination.read_text(encoding="utf-8")
    assert "schedule_expiry: expired_scheduled_occurrence" in summary
    assert "anchor=2026-10-06T06:00:00+08:00" in summary
    assert "deadline=2026-10-06T06:30:00+08:00" in summary
