from copy import deepcopy

import pytest

from src.incident_envelope import (
    IncidentEnvelopeError,
    build_impact_key,
    make_incident_envelope,
    validate_incident_envelope,
)


def _envelope():
    identity = {"slot": "morning", "date": "2026-11-01", "anchor": "taiwan:2026-11-01:morning"}
    return make_incident_envelope(
        incident_type="scheduled_report_failure",
        component="scheduled_market_brief",
        root_cause="scheduled_anchor_claim_missing",
        impact_type="scheduled_slot",
        impact_identity=identity,
        impact={"identity": identity, "description": "The expected morning report was not delivered."},
        evidence=[{
            "repository": "hanjhou2000716/prstklab-stk-detector",
            "workflow": ".github/workflows/scheduled-market-brief.yml",
            "run_id": 41249589716,
            "attempt": 1,
            "sha": "a" * 40,
            "artifact_id": 13060935630,
            "artifact_digest": "sha256:" + "b" * 64,
        }],
        observed_at="2026-11-01T06:45:00Z",
        first_detected_at="2026-11-01T06:00:00+08:00",
        source_occurred_at=None,
        evidence_integrity="verified",
        new_impact=True,
    )


def test_envelope_v2_is_stable_and_keeps_unknown_source_time_explicit():
    envelope = _envelope()
    assert validate_incident_envelope(envelope) is envelope
    assert envelope["times"]["source_occurred_at"] is None
    assert envelope["impact_key"] == build_impact_key(
        impact_type="scheduled_slot", identity=envelope["impact"]["identity"],
    )


def test_incident_identity_uses_worker_compatible_lowercase_not_casefold():
    from src.incident_envelope import build_incident_id

    assert build_incident_id(incident_type="Straße", component="monitor", root_cause="x") != build_incident_id(
        incident_type="STRASSE", component="monitor", root_cause="x",
    )


@pytest.mark.parametrize("mutation,error", [
    (lambda row: row.update(schema_version="incident-envelope-v9"), "schema_unsupported"),
    (lambda row: row.update(generation=0), "generation_invalid"),
    (lambda row: row.update(lifecycle="historical_diagnosed", new_impact=True), "historical_new_impact_conflict"),
    (lambda row: row["evidence"][0].update(sha="short"), "evidence_sha_invalid"),
    (lambda row: row["times"].update(observed_at="2026-11-01T06:45:00"), "timezone_missing"),
    (lambda row: row["impact"].update(identity={"slot": "different"}), "impact_identity_mismatch"),
])
def test_envelope_rejects_invalid_or_conflicting_identity(mutation, error):
    value = deepcopy(_envelope())
    mutation(value)
    with pytest.raises(IncidentEnvelopeError, match=error):
        validate_incident_envelope(value)
