from __future__ import annotations

import json
from types import SimpleNamespace

from scripts.verify_quality_validation import _gh_json_lines, latest_candidate_run, validate_evidence_record
from scripts.write_quality_validation_evidence import build_evidence


def _run(*, run_id: int = 20, attempt: int = 1, conclusion: str = "success") -> dict:
    return {
        "id": run_id,
        "run_attempt": attempt,
        "event": "workflow_dispatch",
        "path": ".github/workflows/quality.yml",
        "head_sha": "a" * 40,
        "status": "completed",
        "conclusion": conclusion,
        "created_at": f"2026-10-04T00:{run_id:02d}:00Z",
        "run_started_at": f"2026-10-04T00:{run_id:02d}:00Z",
    }


def _record(run: dict) -> dict:
    return {
        "schema_version": "quality-candidate-validation-v1",
        "status": "success",
        "validation_mode": "full",
        "workflow_path": ".github/workflows/quality.yml",
        "repository": "hanjhou2000716/prstklab-stk-detector",
        "candidate_sha": "a" * 40,
        "tested_sha": "a" * 40,
        "base_sha": "b" * 40,
        "run_id": str(run["id"]),
        "run_attempt": str(run["run_attempt"]),
        "expected_gate_count": 1,
        "tool_versions": {"python": "3.11", "uv": "0.9", "actionlint": "1.7", "shellcheck": "0.11"},
        "input_fingerprints": {
            key: "c" * 64 for key in (
                "pyproject_toml_sha256", "uv_lock_sha256", "quality_preflight_sha256",
                "workflow_sha256", "evidence_writer_sha256",
            )
        },
        "gates": [{"name": "full preflight", "outcome": "success", "duration_seconds": 42.0}],
    }


def test_latest_dispatch_for_candidate_wins_and_a_failed_latest_run_blocks():
    earlier_success = _run(run_id=10)
    later_failure = _run(run_id=20, conclusion="failure")
    latest = latest_candidate_run([earlier_success, later_failure], "a" * 40)
    assert latest == later_failure
    assert validate_evidence_record(
        latest or {}, [], _record(earlier_success),
        repository="hanjhou2000716/prstklab-stk-detector",
        candidate_sha="a" * 40,
        base_sha="b" * 40,
    )


def test_latest_attempt_of_an_older_dispatch_supersedes_a_newer_run_id():
    newer_run_id = _run(run_id=20, conclusion="failure")
    retried_older_run = _run(run_id=10, attempt=2)
    retried_older_run["run_started_at"] = "2026-10-04T00:45:00Z"

    assert latest_candidate_run(
        [newer_run_id, retried_older_run], "a" * 40,
    ) == retried_older_run


def test_exact_candidate_base_latest_attempt_and_artifact_are_required():
    run = _run(run_id=20, attempt=2)
    artifact = [{"name": "quality-candidate-validation", "expired": False}]
    assert validate_evidence_record(
        run, artifact, _record(run), repository="hanjhou2000716/prstklab-stk-detector",
        candidate_sha="a" * 40, base_sha="b" * 40,
    ) == []

    wrong_base = _record(run)
    wrong_base["base_sha"] = "d" * 40
    errors = validate_evidence_record(
        run, artifact, wrong_base, repository="hanjhou2000716/prstklab-stk-detector",
        candidate_sha="a" * 40, base_sha="b" * 40,
    )
    assert "validation_evidence_base_sha_mismatch" in errors

    assert "validation_artifact_missing_or_expired" in validate_evidence_record(
        run, [{"name": "quality-candidate-validation", "expired": True}], _record(run),
        repository="hanjhou2000716/prstklab-stk-detector",
        candidate_sha="a" * 40, base_sha="b" * 40,
    )


def test_partial_or_modified_candidate_evidence_is_rejected():
    run = _run()
    record = _record(run)
    record["candidate_sha"] = "d" * 40
    record["gates"] = [{"name": "static", "outcome": "success"}, {"name": "tests", "outcome": "not_run"}]
    errors = validate_evidence_record(
        run, [{"name": "quality-candidate-validation", "expired": False}], record,
        repository="hanjhou2000716/prstklab-stk-detector",
        candidate_sha="a" * 40, base_sha="b" * 40,
    )
    assert "validation_evidence_candidate_sha_mismatch" in errors
    assert "validation_gate_failure_present" in errors


def test_validation_rejects_unavailable_tools_and_candidate_fingerprint_drift():
    run = _run()
    record = _record(run)
    record["tool_versions"]["shellcheck"] = "unavailable"
    record["input_fingerprints"]["uv_lock_sha256"] = "d" * 64
    expected = {key: "c" * 64 for key in record["input_fingerprints"]}
    errors = validate_evidence_record(
        run, [{"name": "quality-candidate-validation", "expired": False}], record,
        repository="hanjhou2000716/prstklab-stk-detector",
        candidate_sha="a" * 40,
        base_sha="b" * 40,
        expected_fingerprints=expected,
    )

    assert "validation_tool_versions_missing" in errors
    assert "validation_input_fingerprint_does_not_match_candidate_tree" in errors


def test_evidence_rejects_missing_preflight_gates_even_if_return_status_is_success():
    run = _run()
    record = _record(run)
    record["expected_gate_count"] = 2
    errors = validate_evidence_record(
        run, [{"name": "quality-candidate-validation", "expired": False}], record,
        repository="hanjhou2000716/prstklab-stk-detector",
        candidate_sha="a" * 40, base_sha="b" * 40,
    )
    assert "validation_gate_count_mismatch" in errors


def test_paginated_github_json_lines_parse_without_unsupported_slurp(monkeypatch):
    records = [{"id": 1}, {"id": 2}]
    stdout = "\n".join(json.dumps(record) for record in records)
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(
        "scripts.verify_quality_validation.subprocess.run",
        fake_run,
    )

    assert _gh_json_lines(["--paginate", "repos/example/actions/runs", "--jq", ".workflow_runs[] | @json"]) == records
    assert calls[0][:4] == ["gh", "api", "--method", "GET"]


def test_paginated_github_json_lines_accept_json_quoted_records(monkeypatch):
    record = {"id": 3}
    stdout = json.dumps(json.dumps(record))
    monkeypatch.setattr(
        "scripts.verify_quality_validation.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=stdout, stderr=""),
    )

    assert _gh_json_lines(["--paginate", "repos/example/actions/runs", "--jq", ".workflow_runs[] | @json"]) == [record]


def test_github_json_reads_send_query_fields_with_get(monkeypatch):
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout='{"artifacts": []}', stderr="")

    monkeypatch.setattr("scripts.verify_quality_validation.subprocess.run", fake_run)

    from scripts.verify_quality_validation import _gh_json

    assert _gh_json(["repos/example/actions/runs/1/artifacts", "-f", "per_page=100"]) == {"artifacts": []}
    assert calls[0][:4] == ["gh", "api", "--method", "GET"]


def test_candidate_evidence_reads_shared_structured_preflight_file(monkeypatch, tmp_path):
    preflight_path = tmp_path / "preflight-gates.json"
    preflight_path.write_text(json.dumps({
        "schema_version": "quality-preflight-gates-v1",
        "status": "success",
        "expected_gate_count": 2,
        "gates": [
            {"name": "static", "outcome": "success", "duration_seconds": 1.2},
            {"name": "tests", "outcome": "success", "duration_seconds": 42.0},
        ],
    }), encoding="utf-8")
    monkeypatch.setattr("scripts.write_quality_validation_evidence._version", lambda _command: "test-version")

    record = build_evidence({
        "QUALITY_PREFLIGHT_EVIDENCE_PATH": str(preflight_path),
        "QUALITY_VALIDATION_CANDIDATE_SHA": "a" * 40,
        "GITHUB_SHA": "a" * 40,
        "QUALITY_PREFLIGHT_BASE_SHA": "b" * 40,
        "QUALITY_PREFLIGHT_GATE_COUNT": "2",
        "QUALITY_PREFLIGHT_OUTCOME": "success",
        "GITHUB_REPOSITORY": "hanjhou2000716/prstklab-stk-detector",
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "1",
    })

    assert record["status"] == "success"
    assert record["errors"] == []
    assert len(record["gates"]) == 2


def test_candidate_evidence_fails_closed_if_step_summary_exists_but_shared_file_is_missing(tmp_path, monkeypatch):
    summary_path = tmp_path / "summary.md"
    summary_path.write_text(
        "### Shared quality preflight gate results\n| Gate | Result | Duration |\n|---|---|---|\n| all | success | 1.00s |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("scripts.write_quality_validation_evidence._version", lambda _command: "test-version")

    record = build_evidence({
        "QUALITY_PREFLIGHT_EVIDENCE_PATH": str(tmp_path / "missing-gates.json"),
        "GITHUB_STEP_SUMMARY": str(summary_path),
        "QUALITY_VALIDATION_CANDIDATE_SHA": "a" * 40,
        "QUALITY_PREFLIGHT_BASE_SHA": "b" * 40,
        "QUALITY_PREFLIGHT_GATE_COUNT": "1",
        "QUALITY_PREFLIGHT_OUTCOME": "success",
        "GITHUB_REPOSITORY": "hanjhou2000716/prstklab-stk-detector",
    })

    assert record["status"] == "failure"
    assert "preflight_gate_evidence_missing" in record["errors"]
