from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from scripts import incident_ops_import as importer
from scripts.incident_notification_outlet import (
    CONTROL_ISSUE_TITLE,
    JOURNAL_SCHEMA,
    _default_journal,
    _journal_body,
)
from scripts.monitor_liveness import AUDIT_ISSUE_TITLE_PREFIX
from scripts.scheduled_brief_incidents import ISSUE_TITLE_PREFIX as SCHEDULED_PREFIX


def _control_issue(generation: int = 7):
    journal = _default_journal(importer.REPOSITORY)
    journal["generation"] = generation
    journal["updated_at"] = "2026-11-01T12:00:00+00:00"
    journal["recent_decisions"] = [{
        "decision_id": "d" * 64,
        "window_key": "2026-11-01T12:00:00+00:00",
        "notification_mode": "half_hour_digest",
        "status": "confirmed",
        "outlet_run_id": 123456789,
        "outlet_attempt": 1,
        "confirmed_at": "2026-11-01T12:01:00+00:00",
    }, {
        "decision_id": "e" * 64,
        "window_key": "2026-11-01T12:00:00+00:00",
        "notification_mode": "half_hour_digest",
        "status": "not_emitted",
        "outlet_run_id": 123456790,
        "outlet_attempt": 1,
        "confirmed_at": "",
    }]
    return {"title": CONTROL_ISSUE_TITLE, "body": _journal_body(journal)}


def _issue(number: int, title: str, body: str, state: str = "open"):
    return {
        "number": number, "title": title, "body": body, "state": state,
        "created_at": "2026-11-01T10:00:00Z", "updated_at": "2026-11-01T12:00:00Z",
        "closed_at": "" if state == "open" else "2026-11-01T12:00:00Z",
    }


def _issues():
    return [
        _issue(1099, "Official event delivery degraded / GDACS", "gdacs-event-evidence=ledger_source_url_invalid"),
        _issue(1120, f"{SCHEDULED_PREFIX} / morning", "Root cause: scheduled_anchor_claim_missing\nAffected slots: taiwan:2026-10-29:morning,taiwan:2026-10-30:morning,taiwan:2026-10-31:morning,taiwan:2026-11-01:morning"),
        _issue(1121, f"{SCHEDULED_PREFIX} / plan", "Root cause: natural_acceptance_pending", "closed"),
        _issue(1144, f"{AUDIT_ISSUE_TITLE_PREFIX} / main", "official-monitor-audit-incident=monitor_liveness_pagination_identity_invalid:host=api.github.com"),
        _issue(1145, "Central incident reconciliation degraded / central_reconciliation_coverage_incomplete", "Root cause: central_reconciliation_coverage_incomplete", "closed"),
    ]


def test_import_keeps_historical_slots_and_never_relabels_unproven_recovery() -> None:
    snapshot = importer.build_snapshot(
        issues=_issues(), journal_issue=_control_issue(), repository=importer.REPOSITORY,
        import_run_id=123456700, import_attempt=1, import_sha=importer.EXPECTED_BASELINE_SHA,
        recovery_proof={"status": "unverified", "issue_number": 1145, "reason": "fixture_not_verified"},
        observed_at="2026-11-01T12:30:00Z",
    )
    assert len(snapshot["confirmed_windows"]) == 1
    imported = {row["envelope"]["issue_numbers"][0]: row for row in snapshot["incidents"]}
    assert imported[1120]["envelope"]["lifecycle"] == "historical_diagnosed"
    assert imported[1120]["envelope"]["new_impact"] is False
    assert imported[1120]["envelope"]["compatibility"]["preserved_as_missed_delivery"] is True
    assert imported[1099]["envelope"]["lifecycle"] == "historical_pending_verification"
    assert imported[1144]["envelope"]["lifecycle"] == "active"
    assert imported[1145]["envelope"]["lifecycle"] == "historical_pending_verification"
    assert all(row["suppress_notification"] is True for row in snapshot["incidents"])


def test_only_verified_proof_can_mark_1145_recovered() -> None:
    verified = {"status": "verified", "issue_number": 1145}
    snapshot = importer.build_snapshot(
        issues=_issues(), journal_issue=_control_issue(), repository=importer.REPOSITORY,
        import_run_id=123456700, import_attempt=1, import_sha=importer.EXPECTED_BASELINE_SHA,
        recovery_proof=verified, observed_at="2026-11-01T12:30:00Z",
    )
    imported = {row["envelope"]["issue_numbers"][0]: row["envelope"] for row in snapshot["incidents"]}
    assert imported[1145]["lifecycle"] == "recovered"
    assert imported[1145]["evidence_integrity"] == "partial"


def test_invalid_or_conflicting_confirmed_windows_abort_import() -> None:
    control = _control_issue()
    control["body"] = control["body"].replace("2026-11-01T12:00:00+00:00", "2026-11-01T12:05:00+00:00", 1)
    with pytest.raises(importer.IncidentImportError, match="confirmed_window_evidence_invalid"):
        importer.build_snapshot(
            issues=[], journal_issue=control, repository=importer.REPOSITORY,
            import_run_id=123456700, import_attempt=1, import_sha=importer.EXPECTED_BASELINE_SHA,
            recovery_proof={"status": "unverified", "issue_number": 1145},
            observed_at="2026-11-01T12:30:00Z",
        )


def test_snapshot_bounds_before_any_worker_post() -> None:
    oversized_issues = [
        _issue(2000 + index, f"{AUDIT_ISSUE_TITLE_PREFIX} / main", "official-monitor-audit-incident=monitor_liveness_identity_mismatch")
        for index in range(101)
    ]
    with pytest.raises(importer.IncidentImportError):
        importer.build_snapshot(
            issues=oversized_issues, journal_issue=_control_issue(), repository=importer.REPOSITORY,
            import_run_id=123456700, import_attempt=1, import_sha=importer.EXPECTED_BASELINE_SHA,
            recovery_proof={"status": "unverified", "issue_number": 1145},
            observed_at=datetime(2026, 11, 1, 12, 30, tzinfo=UTC).isoformat(),
        )


def test_snapshot_identity_is_deterministic_from_journal_evidence() -> None:
    control = _control_issue(generation=14)
    body_digest = hashlib.sha256(control["body"].encode()).hexdigest()
    expected = f"journal-14-{body_digest[:32]}"
    assert importer.snapshot_identity(14, control["body"]) == expected
    assert importer.snapshot_identity(14, control["body"]) == expected
    assert JOURNAL_SCHEMA in control["body"]
