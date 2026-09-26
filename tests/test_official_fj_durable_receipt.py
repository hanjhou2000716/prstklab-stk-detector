from __future__ import annotations

from pathlib import Path

import pytest

import src.official_event_monitor as monitor


def _status_for_claim(monkeypatch, tmp_path, claim_key: str, claim: dict[str, object]) -> str:
    output = tmp_path / "status.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    event = {
        "source_key": "financialjuice",
        "event_key": "canonical-event",
        "notification_id": "fj-event-1",
        "title": "Verified official event",
        "source_url": "https://example.test/event",
    }
    claims = {claim_key: claim}

    class FakeLedger:
        def __init__(self) -> None:
            self.delivery_claims = claims

    monkeypatch.setattr(monitor, "EventLedger", FakeLedger)
    monkeypatch.setattr(monitor, "event_key", lambda _event: "canonical-event")
    monkeypatch.setattr(monitor, "notification_key_for_event", lambda _event: "financialjuice:current")
    monkeypatch.setattr(
        monitor,
        "financialjuice_notification_aliases",
        lambda _event: ("financialjuice:current", "financialjuice:legacy"),
    )
    monkeypatch.setattr(monitor, "is_financialjuice_priority_event", lambda _event: True)
    monkeypatch.setattr(monitor, "build_official_event_brief", lambda _event: "Complete factual brief.")
    monkeypatch.setattr(monitor, "content_is_incomplete", lambda *_args: False)
    monkeypatch.setattr(
        monitor,
        "_observe_event",
        lambda *_args, **_kwargs: {"should_remind": True, "changed": False},
    )
    monkeypatch.setattr(monitor, "select_official_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(monitor, "write_summary", lambda *_args, **_kwargs: None)

    monitor.write_status_output(event, {"events": {"items": [event]}})
    return output.read_text(encoding="utf-8")


@pytest.mark.parametrize("claim_key", ["financialjuice:current", "financialjuice:legacy"])
def test_fj_preflight_finds_sender_key_and_alias_and_verifies_all_receipts(
    monkeypatch, tmp_path, claim_key: str
) -> None:
    output = _status_for_claim(
        monkeypatch,
        tmp_path,
        claim_key,
        {
            "status": "delivered",
            "recipient_hashes": ["recipient-a", "recipient-b"],
            "delivered_recipient_hashes": ["recipient-a", "recipient-b"],
        },
    )

    assert "should_send=false" in output
    assert "notification_expected=false" in output
    assert "notification_status=already_delivered" in output
    assert "durable_receipt_verified=true" in output
    assert "hard_failure=false" in output


@pytest.mark.parametrize(
    ("claim", "reason"),
    [
        (
            {
                "status": "delivered",
                "recipient_hashes": ["recipient-a", "recipient-b"],
                "delivered_recipient_hashes": ["recipient-a"],
            },
            "delivered_claim_missing_recipient_receipts",
        ),
        (
            {
                "status": "uncertain",
                "recipient_hashes": ["recipient-a", "recipient-b"],
                "delivered_recipient_hashes": ["recipient-a"],
            },
            "notification_claim_in_flight_or_uncertain",
        ),
    ],
)
def test_fj_partial_or_uncertain_claim_never_becomes_delivered(
    monkeypatch, tmp_path, claim: dict[str, object], reason: str
) -> None:
    output = _status_for_claim(monkeypatch, tmp_path, "financialjuice:legacy", claim)

    assert "should_send=false" in output
    assert "notification_expected=true" in output
    assert "notification_status=blocked" in output
    assert f"notification_reason={reason}" in output
    assert "durable_receipt_verified=false" in output
    assert "hard_failure=true" in output


def test_workflow_carries_durable_proof_to_both_outcome_summaries() -> None:
    workflow = (
        Path(__file__).parents[1] / ".github" / "workflows" / "official-event-monitor.yml"
    ).read_text(encoding="utf-8")

    assert workflow.count("DURABLE_RECEIPT_VERIFIED:") == 2
    assert workflow.count("steps.status.outputs.durable_receipt_verified") == 2
    assert "durable_receipt_verified: ${{ steps.status.outputs.durable_receipt_verified" in workflow
    assert "durable_recipient_receipt_verified" in workflow
    assert "Official event / price notification outcome" in workflow
