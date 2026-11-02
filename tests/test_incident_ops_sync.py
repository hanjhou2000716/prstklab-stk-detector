from __future__ import annotations

import json
from pathlib import Path

from scripts import incident_ops_sync as sync
from scripts.incident_ops_sync import build_envelopes

REPOSITORY = "hanjhou2000716/prstklab-stk-detector"
EVIDENCE = {
    "run_id": 41299999999,
    "attempt": 1,
    "sha": "a" * 40,
    "artifact_id": 13080000000,
    "artifact_digest": "b" * 64,
}


def _result(row):
    return {
        "schema_version": "incident-reconciliation-v1",
        "observed_at": "2026-11-01T10:00:00Z",
        "results": [row],
    }


def _issue(body: str, *, state="open", title="Official monitor liveness audit degraded / main"):
    return {
        "number": 1144,
        "title": title,
        "state": state,
        "body": body,
    }


def _build(row, issue):
    return build_envelopes(
        _result(row), issues={1144: issue}, repository=REPOSITORY,
        run_id=EVIDENCE["run_id"], attempt=EVIDENCE["attempt"],
        sha=EVIDENCE["sha"], artifact_id=EVIDENCE["artifact_id"],
        artifact_digest=EVIDENCE["artifact_digest"],
    )


def test_liveness_marker_becomes_verified_impact_without_using_run_as_impact_identity():
    issue = _issue(
        "official-monitor-audit-incident=official-monitor-audit:pagination_identity_invalid\n"
        "Root cause: raw URL https://private.example/path?token=secret\n"
        "Lifecycle: active\nFirst failure: 2026-11-01T09:06:51Z\n"
    )
    envelope = _build({"source_run_id": 41291664641, "source_attempt": 1, "incident_active": True,
                       "diagnostic_complete": True, "issue_number": 1144, "status": "incident_active"}, issue)[0]
    assert envelope["root_cause"] == "official-monitor-audit:pagination_identity_invalid"
    assert envelope["impact"]["identity"] == {
        "issue_number": 1144,
        "marker": "official-monitor-audit-incident=official-monitor-audit:pagination_identity_invalid",
    }
    assert envelope["evidence"][0]["run_id"] == EVIDENCE["run_id"]
    assert "private.example" not in str(envelope)
    assert "secret" not in str(envelope)
    assert envelope["new_impact"] is False


def test_opened_issue_marks_one_new_impact_and_binds_central_artifact():
    issue = _issue(
        "official-monitor-audit-incident=official-monitor-audit:pagination_identity_invalid\n"
        "Lifecycle: active\n",
    )
    envelope = _build({"opened_issue_numbers": [1144], "issue_number": 1144, "incident_opened": True,
                       "diagnostic_complete": True, "status": "incident_active"}, issue)[0]
    assert envelope["new_impact"] is True
    evidence = envelope["evidence"][0]
    assert evidence["artifact_id"] == EVIDENCE["artifact_id"]
    assert evidence["artifact_digest"] == f"sha256:{EVIDENCE['artifact_digest']}"


def test_historical_issue_slots_are_distinct_but_never_new_impacts():
    issue = _issue(
        "scheduled-brief-incident=scheduled-brief:missing_receipt\n"
        "Lifecycle: historical_diagnosed\n"
        "Affected slots: taiwan:2026-10-29:morning, taiwan:2026-10-30:morning\n",
        title="Scheduled market brief delivery degraded / morning",
    )
    envelopes = _build({"historical_diagnosed_issue_numbers": [1144], "issue_number": 1144,
                        "diagnostic_complete": True, "status": "incident_active"}, issue)
    assert len(envelopes) == 2
    assert {(row["impact"]["identity"]["slot"], row["impact"]["identity"]["date"], row["impact"]["identity"]["anchor"]) for row in envelopes} == {
        ("morning", "2026-10-29", "taiwan:2026-10-29:morning"),
        ("morning", "2026-10-30", "taiwan:2026-10-30:morning"),
    }
    assert all(row["lifecycle"] == "historical_diagnosed" and row["new_impact"] is False for row in envelopes)


def test_one_opened_incident_with_multiple_slots_claims_one_generation_alert():
    issue = _issue(
        "scheduled-brief-incident=scheduled-brief:missing_receipt\n"
        "Lifecycle: active\n"
        "Affected slots: morning:2026-10-31 (taiwan:2026-10-31:morning), "
        "morning:2026-11-01 (taiwan:2026-11-01:morning)\n",
        title="Scheduled market brief delivery degraded / morning",
    )
    envelopes = _build({"opened_issue_numbers": [1144], "issue_number": 1144,
                        "diagnostic_complete": True, "status": "incident_active"}, issue)
    assert len(envelopes) == 2
    assert sum(row["new_impact"] for row in envelopes) == 1
    assert {row["impact"]["identity"]["date"] for row in envelopes} == {"2026-10-31", "2026-11-01"}


def test_new_scheduled_slot_marks_only_its_matching_impact_identity():
    issue = _issue(
        "scheduled-brief-incident=scheduled-brief:missing_receipt\n"
        "Lifecycle: active\n"
        "Affected slots: morning:2026-10-31 (taiwan:2026-10-31:morning), "
        "morning:2026-11-01 (taiwan:2026-11-01:morning)\n",
        title="Scheduled market brief delivery degraded / morning",
    )
    envelopes = _build({
        "issue_number": 1144, "diagnostic_complete": True, "status": "incident_active",
        "new_impact_identities": [{
            "issue_number": 1144, "slot": "morning", "date": "2026-11-01",
            "anchor": "taiwan:2026-11-01:morning",
        }],
    }, issue)
    assert len(envelopes) == 2
    newly_added = [row for row in envelopes if row["new_impact"]]
    assert len(newly_added) == 1
    assert newly_added[0]["impact"]["identity"]["date"] == "2026-11-01"


def test_closed_issue_without_explicit_recovery_is_not_reported_recovered():
    issue = _issue(
        "official-monitor-audit-incident=official-monitor-audit:pagination_identity_invalid\n"
        "Lifecycle: active\n",
        state="closed",
    )
    envelope = _build({"issue_number": 1144, "diagnostic_complete": True, "status": "no_notification"}, issue)[0]
    assert envelope["lifecycle"] == "historical_pending_verification"


def test_recovery_requires_explicit_recovered_issue_evidence():
    issue = _issue(
        "official-monitor-audit-incident=official-monitor-audit:pagination_identity_invalid\n"
        "Lifecycle: active\n",
        state="closed",
    )
    envelope = _build({"recovered_issue_numbers": [1144], "issue_number": 1144,
                       "diagnostic_complete": True, "status": "recovered"}, issue)[0]
    assert envelope["lifecycle"] == "recovered"


def test_sync_binds_producer_mode_to_the_durable_coordinator(tmp_path: Path, monkeypatch):
    result_path = tmp_path / "central.json"
    result_path.write_text(json.dumps(_result({
        "opened_issue_numbers": [1144], "issue_number": 1144, "incident_opened": True,
        "diagnostic_complete": True, "status": "incident_active",
    })), encoding="utf-8")
    issue = _issue(
        "official-monitor-audit-incident=official-monitor-audit:pagination_identity_invalid\n"
        "Lifecycle: active\n",
    )
    monkeypatch.setattr(sync, "_fetch_issue", lambda *args, **kwargs: issue)
    monkeypatch.setattr(sync, "_token", lambda: "oidc")
    posted = {}

    def capture_post(url, payload, token):
        posted.update(url=url, payload=payload, token=token)
        return {"accepted_count": 1}

    monkeypatch.setattr(sync, "_post", capture_post)
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    monkeypatch.setenv("GITHUB_RUN_ID", str(EVIDENCE["run_id"]))
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", str(EVIDENCE["attempt"]))
    monkeypatch.setenv("GITHUB_SHA", EVIDENCE["sha"])
    monkeypatch.setenv("GITHUB_TOKEN", "read-token")
    monkeypatch.setenv("INCIDENT_RESULT_ARTIFACT_ID", str(EVIDENCE["artifact_id"]))
    monkeypatch.setenv("INCIDENT_RESULT_ARTIFACT_DIGEST", EVIDENCE["artifact_digest"])
    monkeypatch.setenv("INCIDENT_OPS_URL", "https://prstk.account.workers.dev")
    monkeypatch.setenv("INCIDENT_OPS_MODE", "live")

    outcome = sync.sync_file(result_path)

    assert outcome["status"] == "accepted_live"
    assert posted["payload"]["producer_mode"] == "live"
    assert len(posted["payload"]["envelopes"]) == 1
