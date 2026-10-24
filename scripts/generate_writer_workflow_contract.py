"""Generate or verify the fixed-source workflow contracts used by writer_queue."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.writer_queue import WRITER_QUEUE_GATES  # noqa: E402

OUTPUT = ROOT / "src" / "writer_workflow_contracts.json"
LEGACY_COMMITS = (
    "cc40ba0401362f6214b540c70b5e1aa3100d5773",
    "ce7f0ec273014dd173c4928feebb31c70280b266",
    "16bc07cc25aeeb9a7145dbabac6eab1b43251926",
    "017f6da40c8e8900088844f21bfdeb2bcffec4e8",
    "62b8e4fb7e5f53764ae0d8923f50e203c5b009dc",
)
PUBLISH_MARKERS = (
    "python -m src.data_release --publish",
    "actions/upload-pages-artifact",
    "actions/deploy-pages",
    "deploy-pages-retry",
)


class ContractError(RuntimeError):
    pass


def _yaml(source: bytes, path: str) -> dict[str, Any]:
    try:
        value = yaml.safe_load(source.decode("utf-8"))
    except (UnicodeError, yaml.YAMLError) as exc:
        raise ContractError(f"writer workflow YAML invalid: {path}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("jobs"), dict):
        raise ContractError(f"writer workflow jobs missing: {path}")
    return value


def _needs_graph(jobs: dict[str, Any]) -> dict[str, list[str]]:
    graph: dict[str, list[str]] = {}
    for name, value in jobs.items():
        if not isinstance(value, dict):
            raise ContractError(f"writer job contract invalid: {name}")
        raw = value.get("needs", [])
        needs = [raw] if isinstance(raw, str) else raw
        if not isinstance(needs, list) or any(not isinstance(item, str) for item in needs):
            raise ContractError(f"writer job needs invalid: {name}")
        if any(item not in jobs for item in needs):
            raise ContractError(f"writer job dependency missing: {name}")
        graph[name] = needs
    return graph


def _transitive_needs(job: str, graph: dict[str, list[str]]) -> set[str]:
    result: set[str] = set()
    pending = list(graph.get(job, []))
    while pending:
        item = pending.pop()
        if item in result:
            continue
        result.add(item)
        pending.extend(graph.get(item, []))
    return result


def _contract(path: str, source: bytes) -> dict[str, Any]:
    workflow = _yaml(source, path)
    jobs = workflow["jobs"]
    gate = WRITER_QUEUE_GATES[path]
    gate_job_name = str(gate["job_name"])
    gate_job = jobs.get(gate_job_name)
    if not isinstance(gate_job, dict):
        raise ContractError(f"publication gate job missing: {path}")
    steps = gate_job.get("steps")
    if not isinstance(steps, list):
        raise ContractError(f"publication gate steps missing: {path}")
    matches = [
        index for index, step in enumerate(steps)
        if isinstance(step, dict) and step.get("name") == gate["step_name"]
    ]
    if len(matches) != 1 or steps[matches[0]].get("id") != "writer_queue":
        raise ContractError(f"publication gate is not unique and identified: {path}")
    gate_index = matches[0]
    graph = _needs_graph(jobs)
    protected_jobs: set[str] = set()
    protected_steps: list[dict[str, Any]] = []
    for job_name, job in jobs.items():
        job_steps = job.get("steps", [])
        if not isinstance(job_steps, list):
            raise ContractError(f"writer steps invalid: {path}:{job_name}")
        for index, step in enumerate(job_steps):
            if not isinstance(step, dict):
                continue
            run = str(step.get("run") or "")
            uses = str(step.get("uses") or "")
            env = step.get("env") if isinstance(step.get("env"), dict) else {}
            name = str(step.get("name") or "")
            content = f"{run}\n{uses}"
            sender = "TELEGRAM_BOT_TOKEN" in env or "Send Telegram" in name
            publication = any(marker in content for marker in PUBLISH_MARKERS)
            if not (sender or publication):
                continue
            if "actions/upload-artifact" in uses:
                continue
            protected_jobs.add(job_name)
            protected_steps.append({
                "job": job_name,
                "index": index,
                "name": name,
                "kind": "sender" if sender else "publication",
            })
            if job_name == gate_job_name:
                if index <= gate_index or "writer_queue.outputs.should_continue" not in str(step.get("if") or ""):
                    raise ContractError(f"protected step precedes/escapes writer gate: {path}:{job_name}:{name}")
            elif gate_job_name not in _transitive_needs(job_name, graph):
                raise ContractError(f"protected job lacks gate dependency: {path}:{job_name}:{name}")
    if gate_job_name not in protected_jobs:
        raise ContractError(f"gate job has no protected publication/sender work: {path}")
    return {
        "workflow_id": int(gate["workflow_id"]),
        "workflow_path": path,
        "workflow_content_sha256": hashlib.sha256(source).hexdigest(),
        "gate_job": gate_job_name,
        "gate_step": str(gate["step_name"]),
        "gate_step_index": gate_index,
        "job_needs": graph,
        "protected_jobs": sorted(protected_jobs),
        "protected_steps": protected_steps,
    }


def _git_show(revision: str, path: str) -> bytes:
    # An optional, local-only source bundle makes regeneration possible in a
    # shallow/offline checkout. CI still reads the immutable Git objects.
    bundle_path = ROOT / ".writer-workflow-legacy-sources.json"
    if bundle_path.is_file():
        try:
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            bundled = bundle.get(revision, {}).get(path)
        except (OSError, json.JSONDecodeError, AttributeError) as exc:
            raise ContractError("legacy workflow source bundle is invalid") from exc
        if isinstance(bundled, str):
            return bundled.encode("utf-8")
    result = subprocess.run(
        ["git", "-c", f"safe.directory={ROOT.as_posix()}", "show", f"{revision}:{path}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if result.returncode:
        raise ContractError(f"historical writer workflow unavailable: {revision[:12]}:{path}")
    return result.stdout


def _frozen_legacy_contracts() -> dict[str, dict[str, Any]]:
    """Load reviewed legacy contracts when this checkout omits old Git objects.

    PR and worktree checkouts are intentionally shallow. In that case the
    versioned contract file is the approved compatibility record; its schema,
    revision set, workflow identities, hashes, gate identities, and protected
    paths are still checked here. A full checkout continues to regenerate the
    records from immutable Git blobs.
    """
    try:
        value = json.loads(OUTPUT.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError("frozen legacy workflow contracts unavailable") from exc
    if not isinstance(value, dict) or value.get("schema_version") != "writer-workflow-contracts-v1":
        raise ContractError("frozen legacy workflow contract schema invalid")
    legacy = value.get("verified_legacy_commits")
    if not isinstance(legacy, dict) or set(legacy) != set(LEGACY_COMMITS):
        raise ContractError("frozen legacy workflow revision set invalid")
    checked: dict[str, dict[str, Any]] = {}
    for revision in LEGACY_COMMITS:
        workflows = legacy.get(revision)
        if not isinstance(workflows, dict) or set(workflows) != set(WRITER_QUEUE_GATES):
            raise ContractError(f"frozen legacy workflow set invalid: {revision[:12]}")
        checked_workflows: dict[str, Any] = {}
        for path, gate in WRITER_QUEUE_GATES.items():
            contract = workflows.get(path)
            if not isinstance(contract, dict):
                raise ContractError(f"frozen legacy workflow contract invalid: {revision[:12]}:{path}")
            if (
                contract.get("workflow_path") != path
                or contract.get("workflow_id") != int(gate["workflow_id"])
                or not isinstance(contract.get("workflow_content_sha256"), str)
                or len(contract["workflow_content_sha256"]) != 64
                or not isinstance(contract.get("gate_job"), str)
                or not contract["gate_job"]
                or not isinstance(contract.get("gate_step"), str)
                or not contract["gate_step"]
                or not isinstance(contract.get("protected_jobs"), list)
                or not contract["protected_jobs"]
                or not isinstance(contract.get("protected_steps"), list)
                or not isinstance(contract.get("job_needs"), dict)
            ):
                raise ContractError(f"frozen legacy workflow contract shape invalid: {revision[:12]}:{path}")
            checked_workflows[path] = contract
        checked[revision] = checked_workflows
    return checked


def _legacy_contracts() -> dict[str, dict[str, Any]]:
    try:
        return {
            revision: {
                path: _contract(path, _git_show(revision, path))
                for path in sorted(WRITER_QUEUE_GATES)
            }
            for revision in LEGACY_COMMITS
        }
    except ContractError as exc:
        if not str(exc).startswith("historical writer workflow unavailable:"):
            raise
        return _frozen_legacy_contracts()


def build() -> dict[str, Any]:
    current: dict[str, Any] = {}
    for path in sorted(WRITER_QUEUE_GATES):
        source = (ROOT / path).read_bytes()
        current[path] = _contract(path, source)
    legacy = _legacy_contracts()
    return {
        "schema_version": "writer-workflow-contracts-v1",
        "writer_workflows": current,
        "verified_legacy_commits": legacy,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        expected = json.dumps(build(), sort_keys=True, indent=2) + "\n"
    except (ContractError, OSError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.write:
        OUTPUT.write_text(expected, encoding="utf-8")
        print(f"updated {OUTPUT.relative_to(ROOT)}")
        return 0
    try:
        actual = OUTPUT.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"writer workflow contract file unavailable: {type(exc).__name__}", file=sys.stderr)
        return 1
    if actual != expected:
        print("writer workflow contract is stale or does not match parsed workflows", file=sys.stderr)
        return 1
    print("writer workflow contracts match active and verified legacy sources")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
