from __future__ import annotations

from src.financialjuice_release_contract import apply_financialjuice_release_boundary
from src.release_diagnostics import build_release_preflight_diagnostic


def _incomplete_fj(*, positive: bool = False, observation_id: str = "fj-incomplete") -> dict:
    return {
        "observation_id": observation_id,
        "source": "FinancialJuice",
        "source_key": "financialjuice",
        "public_summary_version": "public-summary-v3",
        "public_summary_status": "incomplete",
        "public_short_message": "🟣 FJ 9/10｜更節能。",
        "notification_status": "eligible" if positive else "content_incomplete",
        "public_signal_eligible": positive,
        "alert_eligible": positive,
        "vendor_priority_notification": positive,
        "delivery_eligible": positive,
    }


def test_non_public_incomplete_fj_is_quarantined_before_public_projection() -> None:
    row = _incomplete_fj()
    snapshot = {
        "events": {"items": [{"source": "MOPS", "event": "官方公告"}, row]},
        "financialjuice_priority_events": [row],
        "financialjuice_observations": [row],
        "external_observations": [row],
    }

    result = apply_financialjuice_release_boundary(snapshot)

    assert result["status"] == "ready_with_quarantine"
    assert result["quarantined_alert_count"] == 1
    assert result["quarantined_alert_reasons"] == ["public_summary_not_ready"]
    assert [item["source"] for item in snapshot["events"]["items"]] == ["MOPS"]
    assert snapshot["financialjuice_priority_events"] == []
    assert snapshot["external_observations"] == []
    assert snapshot["financialjuice_observations"] == [row]


def test_public_incomplete_fj_is_fatal_and_not_downgraded() -> None:
    snapshot = {"events": {"items": [_incomplete_fj(positive=True)]}}

    result = apply_financialjuice_release_boundary(snapshot)

    assert result["status"] == "invalid"
    assert result["quarantined_alert_count"] == 0
    assert result["fatal_alert_contract_errors"] == ["events[0]:public_summary_not_ready"]


def test_preflight_diagnostic_is_redacted_and_tracks_quarantine() -> None:
    row = _incomplete_fj()
    snapshot = {"events": {"items": [row]}, "financialjuice_observations": [row]}
    boundary = apply_financialjuice_release_boundary(snapshot)
    diagnostic = build_release_preflight_diagnostic(
        snapshot,
        manifest={**boundary, "status": "ready_with_quarantine"},
        run_id="run-1",
        workflow_sha="a" * 40,
        production_sha="b" * 40,
        slot="us_premarket",
    )

    assert diagnostic["manifest_status"] == "ready_with_quarantine"
    assert diagnostic["quarantined_alert_count"] == 1
    assert len(diagnostic["quarantined_event_fingerprints"]) == 1
    assert diagnostic["financialjuice_event_count"] == 1
    assert "observation_id" not in str(diagnostic)
    assert "更節能" not in str(diagnostic)


def test_quarantine_removes_all_known_event_aliases_from_public_views() -> None:
    row = {
        **_incomplete_fj(),
        "item_id": "fj-item-incomplete",
        "event_key": "fj-event-incomplete",
        "canonical_fact_key": "fj-fact-incomplete",
    }
    snapshot = {
        "events": {"items": [row]},
        "financialjuice_priority_events": [],
        "financialjuice_observations": [{**row, "observation_id": "fj-audit-alias"}],
        "external_observations": [{**row, "observation_id": "fj-item-incomplete"}],
        "briefing": {
            "displayed_event_keys": ["fj-event-incomplete", "keep-me"],
            "themes": [{"source": "financialjuice", "observation_id": "fj-item-incomplete"}],
        },
    }

    result = apply_financialjuice_release_boundary(snapshot)

    assert result["status"] == "ready_with_quarantine"
    assert snapshot["external_observations"] == []
    assert snapshot["briefing"]["displayed_event_keys"] == ["keep-me"]
    assert snapshot["briefing"]["themes"] == []
