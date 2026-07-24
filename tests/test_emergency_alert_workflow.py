from pathlib import Path


def test_emergency_workflow_has_fixed_major_event_categories_and_mini_app_delivery():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "emergency-alert.yml").read_text(encoding="utf-8")

    assert "options: [fed, macro, policy, conflict, semiconductor, market]" in workflow
    assert "python -m src.emergency_alert" in workflow
    assert "DASHBOARD_URL" in workflow
