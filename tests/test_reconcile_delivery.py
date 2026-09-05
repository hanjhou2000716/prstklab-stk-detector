from src.event_ledger import EventLedger
from src.reconcile_delivery import reconcile_delivery


def _receipt(**overrides):
    payload = {
        "trace_id": "brief-33966136743",
        "release_id": "release-brief-1",
        "snapshot_id": "snapshot-brief-1",
        "alert_id": "briefing-morning-1",
        "observation_id": "briefing-observation-1",
        "delivery_status": "delivered",
        "sent_at": "2026-09-05T06:01:02+00:00",
        "source_url": "https://hanjhou2000716.github.io/prstklab-stk-detector/?alert=briefing-morning-1",
        "public_short_message": "📊 晨報｜隔夜市場與今日重點。",
        "worker_receipt_status": "accepted",
    }
    payload.update(overrides)
    return payload


def test_reconcile_persists_existing_delivery_without_sender_or_new_attempt(tmp_path):
    ledger = EventLedger(tmp_path / "ledger.json")

    result = reconcile_delivery(_receipt(), ledger)

    assert result["reconciled"] is True
    assert result["sender_attempts"] == 0
    rows = ledger.delivery_history()
    assert len(rows) == 1
    assert rows[0]["trace_id"] == "brief-33966136743"
    assert rows[0]["sent_at"].startswith("2026-09-05T06:01:02")
    assert rows[0]["reason"] == "reconcile_delivery"


def test_reconcile_is_idempotent_and_does_not_add_a_second_attempt(tmp_path):
    ledger = EventLedger(tmp_path / "ledger.json")

    first = reconcile_delivery(_receipt(), ledger)
    second = reconcile_delivery(_receipt(), ledger)

    assert first["reconciled"] is True
    assert second["delivery_status"] == "already_recorded"
    assert len(ledger.delivery_history()) == 1


def test_reconcile_marks_insufficient_evidence_uncertain_without_mutation(tmp_path):
    ledger = EventLedger(tmp_path / "ledger.json")

    result = reconcile_delivery(_receipt(source_url="http://invalid.example/report"), ledger)

    assert result["delivery_status"] == "delivery_uncertain"
    assert result["sender_attempts"] == 0
    assert ledger.delivery_history() == []


def test_reconcile_accepts_nested_worker_receipt_without_resend(tmp_path):
    ledger = EventLedger(tmp_path / "ledger.json")
    receipt = {
        "trace_id": "brief-nested-1",
        "release_id": "release-nested-1",
        "snapshot_id": "snapshot-nested-1",
        "alert_id": "briefing-nested-1",
        "observation_id": "briefing-observation-nested-1",
        "sent_at": "2026-09-05T06:01:02+00:00",
        "worker_receipt": {
            "delivery_trace_id": "brief-nested-1",
            "release_id": "release-nested-1",
            "snapshot_id": "snapshot-nested-1",
            "notification_id": "briefing-nested-1",
            "observation_id": "briefing-observation-nested-1",
            "receipt_status": "accepted",
            "delivery_status": "delivered",
            "workflow_run_id": "33966136743",
            "source_url": "https://hanjhou2000716.github.io/prstklab-stk-detector/?alert=briefing-nested-1",
        },
    }

    result = reconcile_delivery(receipt, ledger)

    assert result["reconciled"] is True
    assert result["sender_attempts"] == 0
    assert ledger.delivery_history()[0]["workflow_run_id"] == "33966136743"


def test_reconcile_rejects_conflicting_nested_identity_without_mutation(tmp_path):
    ledger = EventLedger(tmp_path / "ledger.json")
    receipt = _receipt(
        worker_receipt={
            "trace_id": "different-trace",
            "receipt_status": "accepted",
        }
    )

    result = reconcile_delivery(receipt, ledger)

    assert result["delivery_status"] == "delivery_uncertain"
    assert result["notification_reason"] == "receipt_lineage_conflict"
    assert ledger.delivery_history() == []


def test_reconcile_accepts_worker_status_only_shape(tmp_path):
    ledger = EventLedger(tmp_path / "ledger.json")
    receipt = _receipt(
        delivery_status=None,
        worker_receipt_status=None,
        status=None,
        worker_receipt={
            "release_id": "release-brief-1",
            "snapshot_id": "snapshot-brief-1",
            "alert_id": "briefing-morning-1",
            "observation_id": "briefing-observation-1",
            "status": "accepted",
            "delivered_at": "2026-09-05T06:01:02+00:00",
        },
    )

    result = reconcile_delivery(receipt, ledger)

    assert result["reconciled"] is True
    assert result["sender_attempts"] == 0
