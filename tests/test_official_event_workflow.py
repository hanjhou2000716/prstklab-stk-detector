from pathlib import Path


def test_official_event_workflow_is_dispatchable_and_idempotent():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "official-event-monitor.yml").read_text(encoding="utf-8")

    assert "official-event-check" in workflow
    assert "official-event-${{ steps.status.outputs.key }}" in workflow
    assert "python -m src.official_event_monitor --send" in workflow
    assert "DASHBOARD_URL" in workflow
    assert "delivered_count" in workflow or "delivery_status" in workflow
    assert "src.delivery_callback" in workflow
    assert "PUBLIC_OBSERVATIONS_URL" in workflow
    assert "PUBLIC_OBSERVATIONS_SHARED_SECRET" in workflow


def test_gmail_history_dispatches_realtime_monitor_after_new_reviewed_rows():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "gmail-history-sync.yml").read_text(encoding="utf-8")
    assert "contents: write" in workflow
    assert "gmail-sync-result.json" in workflow
    assert "official-event-check" in workflow
    assert "processed" in workflow
