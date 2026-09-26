"""Shared, fail-closed terminal classification for scheduled and official notifications."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_TRUE = {"1", "true", "yes", "on"}
_SAFE_SUPPRESSIONS = {"theme:same_theme_unchanged", "theme:same_theme_within_2h"}


def _text(values: Mapping[str, str], key: str, default: str = "") -> str:
    return str(values.get(key, default) or default).replace("\r", " ").replace("\n", " ").strip()[:200]


def _flag(values: Mapping[str, str], key: str, default: bool = False) -> bool:
    raw = _text(values, key, "true" if default else "false").casefold()
    return raw in _TRUE


def _count(values: Mapping[str, str], key: str) -> int | None:
    raw = _text(values, key)
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _result(
    values: Mapping[str, str],
    workflow: str,
    *,
    status: str,
    reason: str,
    expected: bool,
    failure: bool = False,
    no_resend: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": "notification-terminal-v1",
        "workflow": workflow,
        "run_id": _text(values, "GITHUB_RUN_ID"),
        "workflow_sha": _text(values, "GITHUB_SHA"),
        "slot": _text(values, "SCHEDULED_SLOT", _text(values, "SLOT", _text(values, "CANDIDATE_TYPE", "unknown"))),
        "scheduled_for_at": _text(values, "SCHEDULED_FOR_AT"),
        "expected": expected,
        "status": status,
        "reason": reason[:200],
        "failure": failure,
        "no_resend": no_resend,
        "sender_status": _text(values, "SEND_STATUS", "not_attempted") or "not_attempted",
        "receipt_status": _text(values, "RECEIPT_OUTCOME", _text(values, "RECEIPT_CALLBACK_OUTCOME", "not_attempted")) or "not_attempted",
        "delivered_count": _count(values, "DELIVERED_COUNT"),
        "failed_count": _count(values, "FAILED_COUNT"),
        "stages": {
            "prepare": _text(values, "PREPARE_OUTCOME", _text(values, "SCAN_STATUS", "unknown")),
            "deployment": _text(values, "DEPLOYMENT_AVAILABLE", _text(values, "PAGES_DEPLOYMENT_AVAILABLE", "unknown")),
            "public_gate": _text(values, "RELEASE_GATE_ALLOWED", _text(values, "GATE_ALLOWED", "unknown")),
            "receipt": _text(values, "RECEIPT_OUTCOME", _text(values, "RECEIPT_CALLBACK_OUTCOME", "not_attempted")),
            "ledger": _text(values, "LEDGER_OUTCOME", _text(values, "LEDGER_PERSIST_OUTCOME", "not_attempted")),
        },
    }


def evaluate_official_terminal(values: Mapping[str, str]) -> dict[str, Any]:
    """Classify the final official-event outcome from workflow evidence."""
    requested = _flag(values, "NOTIFICATION_REQUESTED")
    should_send = _flag(values, "SHOULD_SEND")
    expected = _flag(values, "NOTIFICATION_EXPECTED")
    status = _text(values, "SEND_STATUS", _text(values, "NOTIFICATION_STATUS", "not_attempted"))
    reason = _text(values, "NOTIFICATION_REASON", _text(values, "HARD_FAILURE_REASON", ""))
    hard_failure = _flag(values, "HARD_FAILURE")
    scan_outcome = _text(values, "SCAN_STATUS")

    if requested and scan_outcome != "success":
        return _result(
            values, "official", status="failed",
            reason=f"official_preflight_{scan_outcome or 'not_run'}",
            expected=expected, failure=True,
        )
    if hard_failure:
        return _result(
            values, "official", status="blocked", reason=reason or "official_preflight_blocked",
            expected=expected, failure=True,
        )
    if status == "policy_suppressed" and not _flag(values, "SEND_NOTIFICATION_EXPECTED", expected):
        if reason in _SAFE_SUPPRESSIONS:
            return _result(
                values, "official", status="policy_suppressed", reason=reason,
                expected=False,
            )
        return _result(
            values, "official", status="blocked", reason="unrecognized_policy_suppression",
            expected=expected, failure=True,
        )
    if status == "already_delivered" and not should_send:
        return _result(
            values, "official", status="already_delivered",
            reason=reason or "durable_recipient_receipt_verified", expected=False,
        )
    if not requested:
        return _result(
            values, "official", status="not_requested",
            reason="manual_notification_opt_in_required", expected=False,
        )
    if not should_send:
        if status in {"no_event", "suppressed", "not_attempted"} and not expected:
            return _result(
                values, "official", status="no_notification",
                reason=reason or "no_new_eligible_candidate", expected=False,
            )
        if status in {"summary_pending", "summary_timeout", "summary_pending_timeout"}:
            timed_out = status != "summary_pending"
            return _result(
                values, "official", status="pending_timeout" if timed_out else "summary_pending",
                reason=reason or status, expected=expected, failure=timed_out,
            )
        if status == "content_incomplete" or status == "contract_mismatch" or expected:
            return _result(
                values, "official", status="blocked",
                reason=reason or "expected_candidate_not_sendable", expected=expected, failure=True,
            )
        return _result(
            values, "official", status="unresolved",
            reason=reason or "notification_decision_unresolved", expected=expected,
            failure=True,
        )

    send_reason = _text(values, "SEND_REASON", reason)
    send_status = _text(values, "SEND_STATUS", status)
    if send_status == "policy_suppressed" and not _flag(values, "SEND_NOTIFICATION_EXPECTED", True):
        if send_reason in _SAFE_SUPPRESSIONS:
            return _result(
                values, "official", status="policy_suppressed", reason=send_reason,
                expected=False,
            )
        return _result(
            values, "official", status="blocked", reason="sender_policy_disagreed_with_preflight",
            expected=True, failure=True,
        )

    if _flag(values, "IDEMPOTENCY_CACHE_HIT"):
        return _result(
            values, "official", status="failed",
            reason="idempotency_cache_without_durable_recipient_receipt",
            expected=True, failure=True, no_resend=True,
        )
    if _text(values, "QUEUE_STATUS") == "superseded":
        return _result(
            values, "official", status="failed",
            reason="expected_notification_superseded_without_durable_receipt",
            expected=True, failure=True,
        )
    if _text(values, "PREPARED_RELEASE_STATUS") != "prepared_release_current":
        return _result(
            values, "official", status="failed", reason="prepared_release_not_current",
            expected=True, failure=True,
        )
    if _text(values, "DEPLOYMENT_AVAILABLE") != "true":
        code = _text(values, "DEPLOYMENT_ERROR_CODE", "unavailable")
        return _result(
            values, "official", status="failed", reason=f"pages_deployment_{code}",
            expected=True, failure=True,
        )
    if _text(values, "RELEASE_GATE_ALLOWED") != "true":
        return _result(
            values, "official", status="failed", reason="public_release_gate_blocked",
            expected=True, failure=True,
        )

    delivered = _count(values, "DELIVERED_COUNT")
    failed = _count(values, "FAILED_COUNT")
    if (
        _text(values, "SEND_OUTCOME") != "success"
        or _text(values, "DELIVERY_STATUS") != "delivered"
        or delivered is None
        or delivered < 1
        or failed is None
        or failed != 0
        or _text(values, "RECEIPT_OUTCOME") != "success"
    ):
        return _result(
            values, "official", status="failed",
            reason="expected_delivery_or_persistent_recipient_receipt_missing",
            expected=True, failure=True, no_resend=_flag(values, "SEND_SENT"),
        )
    if _flag(values, "SEND_SENT") and (
        _text(values, "LEDGER_OUTCOME") != "success"
        or _text(values, "RECONCILED_DEPLOYMENT_AVAILABLE") != "true"
        or _text(values, "RECONCILED_RELEASE_GATE_OUTCOME") != "success"
    ):
        return _result(
            values, "official", status="delivered_reconciliation_incomplete",
            reason="post_send_public_release_not_reconciled_do_not_resend",
            expected=True, failure=True, no_resend=True,
        )
    return _result(
        values, "official", status="delivered",
        reason="recipient_receipt_and_public_release_reconciled", expected=True,
    )


def evaluate_scheduled_terminal(values: Mapping[str, str]) -> dict[str, Any]:
    """Classify a scheduled brief after sender, receipt, and release reconciliation."""
    requested = _flag(values, "NOTIFICATION_REQUESTED")
    obligation = _text(values, "DELIVERY_OBLIGATION", "undetermined")
    reason = _text(values, "OBLIGATION_REASON", _text(values, "SEND_REASON", ""))
    expected = _flag(values, "NOTIFICATION_EXPECTED")
    send_status = _text(values, "SEND_STATUS")
    send_reason = _text(values, "SEND_REASON")
    prepare_outcome = _text(values, "PREPARE_OUTCOME", "unknown")

    if obligation in {"expected_skip", "late_publish_only"}:
        publication_ok = (
            _text(values, "PAGES_DEPLOYMENT_AVAILABLE") == "true"
            and _text(values, "GATE_ALLOWED") == "true"
        )
        return _result(
            values, "scheduled",
            status="policy_not_required" if publication_ok else "policy_not_required_publication_unverified",
            reason=reason or obligation, expected=False,
        )
    if obligation == "blocked":
        return _result(
            values, "scheduled", status="blocked",
            reason=reason or "market_calendar_or_slot_evidence_unverified",
            expected=expected, failure=True,
        )
    if _text(values, "HANDOFF_STATUS") == "delivered":
        return _result(
            values, "scheduled", status="completed_by_handoff",
            reason="validated_child_run_completed_successfully",
            expected=True,
        )
    if not requested:
        return _result(
            values, "scheduled", status="not_requested",
            reason="notification_not_requested", expected=False,
        )
    if obligation == "undetermined":
        if prepare_outcome == "success" or _text(values, "WINDOW_DELIVERY_INTENT") == "notify_candidate":
            return _result(
                values, "scheduled", status="failed",
                reason="prepared_run_missing_canonical_delivery_obligation",
                expected=expected, failure=True,
            )
        return _result(
            values, "scheduled", status="not_required",
            reason="no_scheduled_notification_obligation", expected=False,
        )
    if obligation != "report_required":
        return _result(
            values, "scheduled", status="failed",
            reason=f"unknown_delivery_obligation_{obligation or 'empty'}",
            expected=expected, failure=True,
        )
    if send_status == "already_delivered" and send_reason == "already_delivered":
        return _result(
            values, "scheduled", status="already_delivered",
            reason="durable_recipient_receipt_verified", expected=False,
        )
    if not expected:
        return _result(
            values, "scheduled", status="failed",
            reason="report_required_but_notification_expectation_false",
            expected=True, failure=True,
        )
    if prepare_outcome != "success" or not _flag(values, "PREPARE_READY"):
        return _result(
            values, "scheduled", status="failed",
            reason="required_report_preparation_failed",
            expected=True, failure=True,
        )
    if _text(values, "WRITER_QUEUE_STATUS") == "superseded":
        return _result(
            values, "scheduled", status="failed",
            reason="expected_report_superseded_without_handoff_receipt",
            expected=True, failure=True,
        )
    if _text(values, "PREPARED_CURRENT") != "true":
        return _result(
            values, "scheduled", status="failed", reason="prepared_release_not_current",
            expected=True, failure=True,
        )
    if _text(values, "PAGES_DEPLOYMENT_AVAILABLE") != "true":
        return _result(
            values, "scheduled", status="failed",
            reason=f"pages_deployment_{_text(values, 'PAGES_DEPLOYMENT_ERROR_CODE', 'unavailable')}",
            expected=True, failure=True,
        )
    if _text(values, "GATE_ALLOWED") != "true":
        return _result(
            values, "scheduled", status="failed", reason="public_release_gate_blocked",
            expected=True, failure=True,
        )
    delivered = _count(values, "DELIVERED_COUNT")
    failed = _count(values, "FAILED_COUNT")
    if (
        _text(values, "SEND_OUTCOME") != "success"
        or send_status != "ready"
        or _text(values, "DELIVERY_STATUS") != "delivered"
        or delivered is None
        or delivered < 1
        or failed is None
        or failed != 0
    ):
        partial_or_uncertain = bool(delivered and delivered > 0) or _flag(values, "SEND_SENT")
        return _result(
            values, "scheduled", status="failed",
            reason=f"required_report_not_delivered:{send_status or 'not_run'}:{send_reason or 'no_sender_result'}",
            expected=True, failure=True, no_resend=partial_or_uncertain,
        )
    if _text(values, "LEDGER_PERSIST_OUTCOME") != "success":
        return _result(
            values, "scheduled", status="delivered_reconciliation_incomplete",
            reason="recipient_receipt_ledger_not_persisted_do_not_resend",
            expected=True, failure=True, no_resend=True,
        )
    if (
        _text(values, "RECONCILED_DEPLOYMENT_VERIFIED") != "true"
        or _text(values, "RECONCILED_GATE_ALLOWED") != "true"
    ):
        return _result(
            values, "scheduled", status="delivered_reconciliation_incomplete",
            reason="post_send_public_release_not_reconciled_do_not_resend",
            expected=True, failure=True, no_resend=True,
        )
    if (
        _flag(values, "RECEIPT_ENDPOINT_CONFIGURED")
        and _text(values, "RECEIPT_CALLBACK_OUTCOME") != "success"
    ):
        return _result(
            values, "scheduled", status="delivered_reconciliation_incomplete",
            reason="configured_receipt_callback_failed_do_not_resend",
            expected=True, failure=True, no_resend=True,
        )
    return _result(
        values, "scheduled", status="delivered",
        reason="recipient_receipt_and_public_release_reconciled", expected=True,
    )


def append_summary(path: str, terminal: Mapping[str, Any]) -> None:
    if not path:
        return
    lines = [
        "\n## Notification final state\n",
        f"- workflow: {terminal.get('workflow', 'unknown')}\n",
        f"- run_id / tested_sha: {terminal.get('run_id', '')} / {terminal.get('workflow_sha', '')}\n",
        f"- slot: {terminal.get('slot', 'unknown')}\n",
        f"- scheduled_for_at: {terminal.get('scheduled_for_at', '') or 'not_applicable'}\n",
        f"- notification_expected: {str(bool(terminal.get('expected'))).lower()}\n",
        f"- notification_status: {terminal.get('status', 'unresolved')}\n",
        f"- notification_reason: {terminal.get('reason', 'terminal_state_unresolved')}\n",
        f"- sender_status / receipt_status: {terminal.get('sender_status', 'unknown')} / {terminal.get('receipt_status', 'unknown')}\n",
        f"- delivered / failed recipients: {terminal.get('delivered_count', 'unknown')} / {terminal.get('failed_count', 'unknown')}\n",
        f"- no_resend: {str(bool(terminal.get('no_resend'))).lower()}\n",
    ]
    with Path(path).open("a", encoding="utf-8") as summary:
        summary.writelines(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", choices=("official", "scheduled"), required=True)
    args = parser.parse_args()
    values = os.environ
    terminal = (
        evaluate_official_terminal(values)
        if args.workflow == "official"
        else evaluate_scheduled_terminal(values)
    )
    append_summary(os.environ.get("GITHUB_STEP_SUMMARY", ""), terminal)
    print(json.dumps(terminal, ensure_ascii=False, sort_keys=True))
    return 1 if terminal["failure"] else 0


__all__ = [
    "append_summary",
    "evaluate_official_terminal",
    "evaluate_scheduled_terminal",
]


if __name__ == "__main__":
    raise SystemExit(main())
