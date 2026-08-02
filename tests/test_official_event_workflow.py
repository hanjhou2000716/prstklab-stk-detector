from pathlib import Path


def test_official_event_workflow_is_dispatchable_and_idempotent():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "official-event-monitor.yml").read_text(encoding="utf-8")

    assert "official-event-check" in workflow
    assert "official-event-${{ steps.status.outputs.key }}" in workflow
    assert "python -m src.official_event_monitor --send" in workflow
    assert "DASHBOARD_URL" in workflow
    assert "delivered_count" in workflow or "delivery_status" in workflow
