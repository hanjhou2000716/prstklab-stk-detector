import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from scripts import incident_reconciliation as incidents

ROOT = Path(__file__).resolve().parents[1]
SHA = "a5ec959bdb6056b3652bf8fce9a257ba1658780d"
LEGACY_REASON = "GitHub Actions queue pagination incomplete"


def _terminal():
    return {
        "schema_version": "unified-research-terminal-v1", "run_id": 40790581515,
        "attempt": 1, "sha": SHA, "production_run": True, "business_status": "degraded",
        "reason": LEGACY_REASON,
        "stages": {"writer_queue": "failed", "writer_queue_error_code": LEGACY_REASON},
    }


def _event():
    return {
        "run_id": 40790581515, "attempt": 1, "head_sha": SHA,
        "workflow_id": 319283753, "conclusion": "failure",
    }


def test_actual_workflow_terminal_and_legacy_artifact_share_consumer_contract(monkeypatch, tmp_path):
    workflow = yaml.safe_load((ROOT / ".github/workflows/unified-research-report.yml").read_text(encoding="utf-8"))
    step = next(
        row for row in workflow["jobs"]["build-and-deploy"]["steps"]
        if 'Path("unified-research-terminal.json")' in row.get("run", "")
    )
    script = step["run"].split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    env = {
        **os.environ, "PYTHONPATH": str(ROOT), "SCAN_MODE": "production",
        "RESEARCH_DUE": "true", "QUEUE_STATUS": "failed", "QUEUE_ERROR_CODE": LEGACY_REASON,
        "JOB_STATUS": "failure", "GITHUB_RUN_ID": "40790581515", "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_SHA": SHA,
    }
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, env=env,
        capture_output=True, text=True, encoding="utf-8", timeout=20, check=False,
    )
    assert result.returncode == 0, result.stderr
    produced = json.loads((tmp_path / "unified-research-terminal.json").read_text(encoding="utf-8"))
    assert produced["reason"] == "writer_queue_pagination_incomplete"
    assert produced["reason_detail"] == LEGACY_REASON
    assert produced["stages"]["writer_queue_error_code"] == LEGACY_REASON

    calls = []
    monkeypatch.setattr(incidents, "_open_incidents", lambda *a, **k: [])
    monkeypatch.setattr(incidents, "_request_json", lambda *a, **k: calls.append(a) or {"number": 1123})
    for terminal in (_terminal(), produced):
        outcome = incidents._research_incident(
            event=_event(), repository="owner/repo", api_url="https://api.github.com", token="token",
            now=datetime(2026, 10, 29, 13, 0, tzinfo=UTC), terminal=terminal,
        )
        assert outcome["status"] == "degraded"
        assert outcome["opened_issue_numbers"] == [1123]
        assert "Root cause: writer_queue_pagination_incomplete" in calls[-1][5]["body"]


@pytest.mark.parametrize("field,value,error", [
    ("run_id", 40790581516, "incident_research_terminal_identity_invalid"),
    ("attempt", 2, "incident_research_terminal_identity_invalid"),
    ("sha", "b" * 40, "incident_research_terminal_identity_invalid"),
    ("reason", "writer_queue_failed\nRoot cause: fake", "incident_research_terminal_reason_invalid"),
    ("reason", "x" * 201, "incident_research_terminal_reason_invalid"),
])
def test_reason_compatibility_preserves_identity_and_text_boundaries(monkeypatch, field, value, error):
    terminal = {**_terminal(), field: value}
    calls = []
    monkeypatch.setattr(incidents, "_request_json", lambda *a, **k: calls.append(a) or {})
    with pytest.raises(incidents.LivenessAuditError, match=error):
        incidents._research_incident(
            event=_event(), repository="owner/repo", api_url="https://api.github.com", token="token",
            now=datetime(2026, 10, 29, 13, 0, tzinfo=UTC), terminal=terminal,
        )
    assert calls == []
