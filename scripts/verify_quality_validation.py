"""Require a successful, exact-SHA isolated validation before PR checks proceed."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

WORKFLOW_PATH = ".github/workflows/quality.yml"
ARTIFACT_NAME = "quality-candidate-validation"
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def latest_candidate_run(runs: list[dict[str, Any]], candidate_sha: str) -> dict[str, Any] | None:
    matching = [
        run for run in runs
        if run.get("event") == "workflow_dispatch"
        and run.get("path") == WORKFLOW_PATH
        and str(run.get("head_sha") or "").lower() == candidate_sha.lower()
    ]
    return max(
        matching,
        key=lambda run: (
            str(run.get("run_started_at") or run.get("updated_at") or run.get("created_at") or ""),
            int(run.get("id") or 0),
            int(run.get("run_attempt") or 0),
        ),
        default=None,
    )


def validate_evidence_record(
    run: dict[str, Any], artifacts: list[dict[str, Any]], record: dict[str, Any],
    *, repository: str, candidate_sha: str, base_sha: str,
) -> list[str]:
    errors: list[str] = []
    if not SHA_PATTERN.fullmatch(candidate_sha.lower()):
        errors.append("candidate_sha_invalid")
    if not SHA_PATTERN.fullmatch(base_sha.lower()):
        errors.append("base_sha_invalid")
    if run.get("event") != "workflow_dispatch" or run.get("path") != WORKFLOW_PATH:
        errors.append("validation_workflow_identity_mismatch")
    if str(run.get("head_sha") or "").lower() != candidate_sha.lower():
        errors.append("validation_candidate_sha_mismatch")
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        errors.append("latest_isolated_validation_not_successful")
    artifact = next((item for item in artifacts if item.get("name") == ARTIFACT_NAME), None)
    if not artifact or artifact.get("expired") is True:
        errors.append("validation_artifact_missing_or_expired")
    if record.get("schema_version") != "quality-candidate-validation-v1":
        errors.append("validation_evidence_schema_mismatch")
    if record.get("status") != "success" or record.get("validation_mode") != "full":
        errors.append("validation_evidence_not_full_success")
    if record.get("workflow_path") != WORKFLOW_PATH:
        errors.append("validation_evidence_workflow_mismatch")
    if str(record.get("repository") or "").lower() != repository.lower():
        errors.append("validation_repository_mismatch")
    if str(record.get("candidate_sha") or "").lower() != candidate_sha.lower():
        errors.append("validation_evidence_candidate_sha_mismatch")
    if str(record.get("base_sha") or "").lower() != base_sha.lower():
        errors.append("validation_evidence_base_sha_mismatch")
    if str(record.get("run_id") or "") != str(run.get("id") or ""):
        errors.append("validation_run_id_mismatch")
    if str(record.get("run_attempt") or "") != str(run.get("run_attempt") or ""):
        errors.append("validation_run_attempt_mismatch")
    gates = record.get("gates")
    if not isinstance(gates, list) or not gates:
        errors.append("validation_gate_list_missing")
    elif any(not isinstance(gate, dict) or gate.get("outcome") != "success" for gate in gates):
        errors.append("validation_gate_failure_present")
    try:
        expected_gate_count = int(record.get("expected_gate_count") or 0)
    except (TypeError, ValueError):
        expected_gate_count = 0
    if expected_gate_count <= 0 or not isinstance(gates, list) or len(gates) != expected_gate_count:
        errors.append("validation_gate_count_mismatch")
    fingerprints = record.get("input_fingerprints")
    if not isinstance(fingerprints, dict) or any(
        not re.fullmatch(r"[0-9a-f]{64}", str(fingerprints.get(key) or ""))
        for key in (
            "pyproject_toml_sha256", "uv_lock_sha256", "quality_preflight_sha256",
            "workflow_sha256", "evidence_writer_sha256",
        )
    ):
        errors.append("validation_input_fingerprint_missing")
    tool_versions = record.get("tool_versions")
    if not isinstance(tool_versions, dict) or any(
        not str(tool_versions.get(key) or "").strip()
        for key in ("python", "uv", "actionlint", "shellcheck")
    ):
        errors.append("validation_tool_versions_missing")
    return errors


def _gh_json(arguments: list[str]) -> Any:
    result = subprocess.run(["gh", "api", *arguments], check=False, capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise RuntimeError(f"GitHub read failed ({result.returncode}): {result.stderr.strip()[:300]}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GitHub read returned invalid JSON.") from exc


def verify_from_github(repository: str, candidate_sha: str, base_sha: str) -> list[str]:
    if not SHA_PATTERN.fullmatch(candidate_sha.lower()) or not SHA_PATTERN.fullmatch(base_sha.lower()):
        return ["candidate_and_base_must_be_full_commit_shas"]
    runs_value = _gh_json([
        "--paginate", "--slurp", f"repos/{repository}/actions/workflows/quality.yml/runs",
        "-f", "event=workflow_dispatch", "-f", f"head_sha={candidate_sha}", "-f", "per_page=100",
        "--jq", "[.[].workflow_runs[]]",
    ])
    runs = runs_value if isinstance(runs_value, list) else []
    run = latest_candidate_run([item for item in runs if isinstance(item, dict)], candidate_sha)
    if run is None:
        return ["no_isolated_validation_for_exact_candidate_sha"]
    try:
        artifact_response = _gh_json([
            f"repos/{repository}/actions/runs/{run.get('id')}/artifacts", "-f", "per_page=100", "--jq", ".artifacts",
        ])
    except RuntimeError as exc:
        return [f"cannot_read_validation_artifacts:{exc}"]
    artifacts = artifact_response if isinstance(artifact_response, list) else []
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        return ["latest_isolated_validation_not_successful"]
    if not any(item.get("name") == ARTIFACT_NAME and item.get("expired") is not True for item in artifacts if isinstance(item, dict)):
        return ["validation_artifact_missing_or_expired"]
    with tempfile.TemporaryDirectory(prefix="quality-validation-") as temporary:
        downloaded = subprocess.run(
            ["gh", "run", "download", str(run["id"]), "--repo", repository,
             "--name", ARTIFACT_NAME, "--dir", temporary],
            check=False, capture_output=True, text=True, timeout=120,
        )
        if downloaded.returncode:
            return [f"validation_artifact_download_failed:{downloaded.stderr.strip()[:240]}"]
        evidence_files = list(Path(temporary).rglob("quality-validation-evidence.json"))
        if len(evidence_files) != 1:
            return ["validation_evidence_file_missing_or_ambiguous"]
        try:
            record = json.loads(evidence_files[0].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ["validation_evidence_json_invalid"]
    if not isinstance(record, dict):
        return ["validation_evidence_is_not_an_object"]
    return validate_evidence_record(
        run, [item for item in artifacts if isinstance(item, dict)], record,
        repository=repository, candidate_sha=candidate_sha, base_sha=base_sha,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--base-sha", required=True)
    args = parser.parse_args(argv)
    try:
        errors = verify_from_github(args.repo, args.candidate_sha, args.base_sha)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"BLOCKED: isolated candidate validation could not be verified ({exc})", file=sys.stderr)
        return 2
    if errors:
        print("BLOCKED: isolated candidate validation evidence is incomplete: " + ", ".join(errors), file=sys.stderr)
        return 1
    print(f"Verified full isolated validation for candidate {args.candidate_sha} against base {args.base_sha}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
