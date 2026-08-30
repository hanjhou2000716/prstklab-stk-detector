from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"


def _workflow(name: str) -> str:
    return (WORKFLOW_DIR / name).read_text(encoding="utf-8")


def _send_block(workflow: str, marker: str) -> str:
    """Return a notification step and its guard for static contract checks."""
    start = workflow.index(marker)
    end = workflow.find("\n      - name:", start + len(marker))
    return workflow[start:] if end < 0 else workflow[start:end]


def test_scheduled_notification_requires_public_release_gate_and_research_gate():
    workflow = _workflow("scheduled-brief.yml")
    block = _send_block(workflow, "- name: Send Telegram brief after successful publication")
    assert "steps.release_gate.outputs.allowed == 'true'" in block
    assert "steps.research_policy.outputs.allow_telegram == 'true'" in block
    assert "--send-only" in block


def test_official_event_notification_requires_public_release_gate():
    workflow = _workflow("official-event-monitor.yml")
    block = _send_block(workflow, "- name: Send new official event")
    assert "steps.release_gate.outputs.allowed == 'true'" in block
    assert "--send" in block


def test_emergency_notification_requires_public_release_gate():
    workflow = _workflow("emergency-alert.yml")
    block = _send_block(workflow, "- name: Send Telegram emergency alert")
    assert "steps.release_gate.outputs.allowed == 'true'" in block
    assert "src.emergency_alert" in block


def test_creator_notification_requires_parent_release_gate():
    workflow = _workflow("scheduled-brief.yml")
    block = _send_block(workflow, "- name: Send release-gated Creator notifications")
    assert "steps.release_gate.outputs.allowed == 'true'" in block
    assert "env.CREATOR_NOTIFICATION_ENABLED == 'true'" in block


def test_production_receipts_bind_release_and_snapshot():
    for name in ("scheduled-brief.yml", "official-event-monitor.yml", "emergency-alert.yml"):
        workflow = _workflow(name)
        assert "RELEASE_ID:" in workflow
        assert "SNAPSHOT_ID:" in workflow
        assert "python -m src.delivery_callback" in workflow


def test_scoped_legacy_photo_input_is_text_only_and_explicitly_single_recipient():
    workflow = _workflow("notify.yml")
    assert "text acceptance requires an explicit single test_chat_id" in workflow
    assert "inputs.photo_test == true" in workflow
    assert "DELIVERY_RECEIPT_KIND: text_acceptance" in workflow
    assert "sendPhoto" not in workflow
