from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_incident_workflows_use_non_fanout_polling_cadence():
    workflow_dir = ROOT / ".github" / "workflows"
    outlet = (workflow_dir / "incident-notification-outlet.yml").read_text(
        encoding="utf-8"
    )
    central = (workflow_dir / "incident-reconciliation.yml").read_text(
        encoding="utf-8"
    )
    health = (
        workflow_dir / "incident-reconciliation-health.yml"
    ).read_text(encoding="utf-8")

    assert "workflow_run:" not in outlet
    assert 'cron: "0,30 * * * *"' in outlet
    assert "workflow_dispatch:" in outlet

    assert "workflow_run:" not in central
    assert 'cron: "*/5 * * * *"' in central
    assert "workflow_dispatch:" in central

    assert "workflow_run:" not in health
    assert 'cron: "10,40 * * * *"' in health
    assert "workflow_dispatch:" in health
