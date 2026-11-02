from __future__ import annotations

from pathlib import Path

import yaml


def test_legacy_outlet_never_manufactures_failure_to_emit_an_alert() -> None:
    workflow_path = Path(__file__).parents[1] / ".github" / "workflows" / "incident-notification-outlet.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    job_condition = str(workflow["jobs"]["notify"]["if"])
    assert "vars.INCIDENT_OPS_MODE != 'live'" in job_condition
    steps = workflow["jobs"]["notify"]["steps"]
    assert not any("exit 1" in str(step.get("run", "")) for step in steps)
    assert not any(step.get("id") == "native_alert" for step in steps)
    assert any("without manufacturing a failed run" in str(step.get("name", "")) for step in steps)
