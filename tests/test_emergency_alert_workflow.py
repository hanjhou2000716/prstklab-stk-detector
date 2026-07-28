from pathlib import Path


def test_emergency_workflow_has_fixed_major_event_categories_and_mini_app_delivery():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "emergency-alert.yml").read_text(encoding="utf-8")

    assert "options: [fed, macro, policy, conflict, energy, semiconductor, market, black_swan, material_positive]" in workflow
    assert "python -m src.emergency_alert" in workflow
    assert "DASHBOARD_URL" in workflow
    assert "external-market-alert" in workflow
    assert "EXTERNAL_ALERT_SHARED_SECRET" in workflow
    assert "actions/cache/restore@v4" in workflow
