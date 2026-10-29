import json

from src.official_event_trace import build_trace, write_trace


def test_trace_joins_preflight_to_actual_claim_and_receipt_without_source_content(tmp_path):
    batch = tmp_path / "batch.json"
    batch.write_text(json.dumps([{
        "event_ref": "opaque-event-ref",
        "notification_key": "claim-key-returned-by-ledger",
        "alert_id": "public-notification-id",
        "release_id": "release-1",
        "snapshot_id": "snapshot-1",
        "delivery_status": "delivered",
        "receipt_required": True,
        "delivered_count": 4,
        "failed_count": 0,
        "reason": "delivered",
        "source_text": "must not be retained",
    }]), encoding="utf-8")
    trace = write_trace(
        tmp_path / "trace.json",
        run_id="123", attempt="2", sha="a" * 40,
        candidate_results=[{
            "event_ref": "opaque-event-ref",
            "fact_fingerprint": "fact-hash",
            "key_fingerprint": "key-hash",
            "notification_key": "candidate-key",
            "source_key": "financialjuice",
            "source_identity": "fj:stable-fact-ref",
            "observation_id": "obs-1",
            "summary_status": "pending",
            "expected": True,
            "stage": "notification_preflight",
            "status": "ready",
            "source_published_at": "2026-10-16T02:00:00Z",
            "expires_at": "2026-10-16T02:30:00Z",
        }],
        batch_results_path=batch,
        stages={"queue": "admitted", "public_gate": "passed"},
        recorded_at="2026-10-16T02:10:00Z",
    )

    assert trace["schema_version"] == "official-event-trace-v1"
    assert trace["run_attempt"] == "2"
    event = trace["events"][0]
    assert event["claim_key"] == "claim-key-returned-by-ledger"
    assert event["notification_id"] == "public-notification-id"
    assert event["stage"] == "recipient_receipt"
    assert event["status"] == "delivered"
    assert event["source_type"] == "financialjuice"
    assert event["source_identity"] == "fj:stable-fact-ref"
    assert event["observation_id"] == "obs-1"
    assert event["summary_status"] == "pending"
    assert event["delivered_count"] == 4
    assert "source_text" not in json.dumps(trace)


def test_trace_preserves_preflight_failure_and_writes_empty_run_artifact(tmp_path):
    trace = write_trace(
        tmp_path / "trace.json", run_id="123", attempt=1, sha="b" * 40,
        candidate_results=[{
            "event_ref": "ref", "status": "content_incomplete",
            "reason": "summary_semantics_incomplete", "expected": True,
            "stage": "content_preflight",
        }], recorded_at="2026-10-16T02:10:00Z",
    )
    loaded = json.loads((tmp_path / "trace.json").read_text(encoding="utf-8"))
    assert loaded == trace
    assert trace["events"][0]["first_failure"]["reason"] == "summary_semantics_incomplete"
    assert trace["events"][0]["claim_key"] == ""

    empty = build_trace(run_id=123, attempt=1, sha="c" * 40, candidate_results=[])
    assert empty["events"] == []
