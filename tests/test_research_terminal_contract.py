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
        "PRSTK_TEST_WORKDIR": str(tmp_path),
        "RESEARCH_DUE": "true", "QUEUE_STATUS": "failed", "QUEUE_ERROR_CODE": LEGACY_REASON,
        "JOB_STATUS": "failure", "GITHUB_RUN_ID": "40790581515", "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_SHA": SHA,
    }
    # Initialize the subprocess with the project's coverage configuration, then
    # isolate workflow artifacts before running the actual producer entry.
    script = 'import os\nos.chdir(os.environ["PRSTK_TEST_WORKDIR"])\n' + script
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, env=env,
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


def test_parent_success_with_missing_pages_binding_is_still_degraded(monkeypatch):
    terminal = {
        "schema_version": "unified-research-terminal-v1",
        "run_id": _event()["run_id"], "attempt": 1, "sha": SHA,
        "production_run": True, "business_status": "healthy", "reason": "",
        "stages": {
            "deployment": "success", "research_noop": False,
            "required_market_strategy_pairs": ["us/value"],
            "selected_market_strategy_pairs": ["us/value"],
            "executed_market_strategy_pairs": ["us/value"],
            "strategy_step_outcomes": {"us/value": "success"},
            "strategy_pair_dispositions": {
                "us/value": {"state": "complete_scan", "scan_state": "complete"},
            },
        },
    }
    calls = []
    monkeypatch.setattr(incidents, "_open_incidents", lambda *a, **k: [])
    monkeypatch.setattr(incidents, "_request_json", lambda *a, **k: calls.append(a) or {"number": 1144})

    result = incidents._research_incident(
        event=_event(), repository="owner/repo", api_url="https://api.github.com", token="token",
        now=datetime(2026, 11, 1, 17, 20, tzinfo=UTC), terminal=terminal,
    )

    assert result["status"] == "degraded"
    assert result["opened_issue_numbers"] == [1144]
    assert "Root cause: research_publication_not_verified" in calls[-1][5]["body"]


def test_parent_healthy_without_scan_or_valid_noop_is_not_recovered(monkeypatch):
    terminal = {
        "schema_version": "unified-research-terminal-v1",
        "run_id": _event()["run_id"], "attempt": 1, "sha": SHA,
        "production_run": True, "business_status": "healthy", "reason": "",
        "stages": {"research_noop": False, "research_selection": "unknown"},
    }
    calls = []
    monkeypatch.setattr(incidents, "_open_incidents", lambda *a, **k: [])
    monkeypatch.setattr(incidents, "_request_json", lambda *a, **k: calls.append(a) or {"number": 1145})

    result = incidents._research_incident(
        event=_event(), repository="owner/repo", api_url="https://api.github.com", token="token",
        now=datetime(2026, 11, 3, 0, 0, tzinfo=UTC), terminal=terminal,
    )

    assert result["status"] == "degraded"
    assert result["opened_issue_numbers"] == [1145]
    assert "Root cause: research_scan_evidence_incomplete" in calls[-1][5]["body"]


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
