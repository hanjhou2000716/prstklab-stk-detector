"""Write immutable provenance for a full isolated quality validation run."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _version(command: list[str]) -> str:
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"
    lines = [line.strip() for line in (result.stdout or result.stderr).splitlines() if line.strip()]
    return lines[0][:160] if result.returncode == 0 and lines else "unavailable"


def _gate_results(summary_text: str) -> list[dict[str, Any]]:
    active = False
    gates: list[dict[str, Any]] = []
    for line in summary_text.splitlines():
        if line.strip() == "### Shared quality preflight gate results":
            active = True
            continue
        if not active or not line.startswith("|"):
            continue
        parts = [part.strip() for part in line.strip().strip("|").split("|")]
        if len(parts) != 3 or parts[0] in {"Gate", "---"} or parts[0].startswith("-"):
            continue
        duration = parts[2].removesuffix("s").strip()
        try:
            duration_seconds = float(duration)
        except ValueError:
            continue
        gates.append({"name": parts[0], "outcome": parts[1], "duration_seconds": duration_seconds})
    return gates


def build_evidence(environment: dict[str, str] | None = None) -> dict[str, Any]:
    env = environment or os.environ
    summary_path = Path(env.get("GITHUB_STEP_SUMMARY", ""))
    try:
        summary_text = summary_path.read_text(encoding="utf-8")
    except OSError:
        summary_text = ""
    candidate_sha = env.get("QUALITY_VALIDATION_CANDIDATE_SHA", "").lower()
    base_sha = env.get("QUALITY_PREFLIGHT_BASE_SHA", "").lower()
    gates = _gate_results(summary_text)
    try:
        expected_gate_count = int(env.get("QUALITY_PREFLIGHT_GATE_COUNT", "0"))
    except ValueError:
        expected_gate_count = 0
    preflight_outcome = env.get("QUALITY_PREFLIGHT_OUTCOME", "failure")
    errors = []
    if not SHA_PATTERN.fullmatch(candidate_sha):
        errors.append("candidate_sha_missing_or_invalid")
    if not SHA_PATTERN.fullmatch(base_sha):
        errors.append("base_sha_missing_or_invalid")
    if not gates:
        errors.append("preflight_gate_results_missing")
    if expected_gate_count <= 0 or len(gates) != expected_gate_count:
        errors.append("preflight_gate_count_mismatch")
    if any(gate["outcome"] != "success" for gate in gates):
        errors.append("one_or_more_preflight_gates_failed")
    if preflight_outcome != "success":
        errors.append("full_preflight_not_successful")
    workflow_file = ROOT / ".github" / "workflows" / "quality.yml"
    record: dict[str, Any] = {
        "schema_version": "quality-candidate-validation-v1",
        "status": "success" if not errors else "failure",
        "validation_mode": "full",
        "workflow_path": ".github/workflows/quality.yml",
        "workflow_ref": env.get("GITHUB_WORKFLOW_REF", ""),
        "workflow_sha": env.get("GITHUB_WORKFLOW_SHA", ""),
        "repository": env.get("GITHUB_REPOSITORY", ""),
        "candidate_sha": candidate_sha,
        "base_sha": base_sha,
        "expected_gate_count": expected_gate_count,
        "run_id": env.get("GITHUB_RUN_ID", ""),
        "run_attempt": env.get("GITHUB_RUN_ATTEMPT", ""),
        "created_at": datetime.now(UTC).isoformat(),
        "tool_versions": {
            "python": _version([os.environ.get("PYTHON", "python"), "--version"]),
            "uv": _version(["uv", "--version"]),
            "actionlint": _version(["actionlint", "-version"]),
            "shellcheck": _version(["shellcheck", "--version"]),
        },
        "input_fingerprints": {
            "pyproject_toml_sha256": _sha256(ROOT / "pyproject.toml"),
            "uv_lock_sha256": _sha256(ROOT / "uv.lock"),
            "quality_preflight_sha256": _sha256(ROOT / "scripts" / "quality_preflight.py"),
            "workflow_sha256": _sha256(workflow_file),
            "evidence_writer_sha256": _sha256(Path(__file__)),
        },
        "gates": gates,
        "errors": errors,
    }
    return record


def main() -> int:
    record = build_evidence()
    output = Path(os.environ.get("QUALITY_VALIDATION_EVIDENCE_PATH", "quality-validation-evidence.json"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"QUALITY_VALIDATION_EVIDENCE_STATUS={record['status']}")
    # The workflow's earlier gate already owns the job result. Always permit
    # uploading this sanitized record, including a failed validation record.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
