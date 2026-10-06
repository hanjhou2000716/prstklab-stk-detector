import re
from pathlib import Path

import yaml

from src.writer_queue import WRITER_QUEUE_GATES, WRITER_WORKFLOW_IDENTITIES

WORKFLOW_ROOT = Path(__file__).resolve().parents[1] / ".github" / "workflows"
WRITER_WORKFLOWS = (
    "official-event-monitor.yml",
    "scheduled-brief.yml",
    "emergency-alert.yml",
    "refresh-dashboard.yml",
    "monitor-health.yml",
    "unified-research-report.yml",
    "deploy-pages.yml",
)


def _workflow_text(name: str) -> str:
    return (WORKFLOW_ROOT / name).read_text(encoding="utf-8")


def _step_blocks(name: str) -> list[str]:
    lines = _workflow_text(name).splitlines(keepends=True)
    starts = [
        index
        for index, line in enumerate(lines)
        if re.match(r"^      - (?:name|uses|run):", line)
    ]
    return ["".join(lines[start:end]) for start, end in zip(starts, starts[1:] + [len(lines)], strict=True)]


def test_every_shared_writer_has_an_id_and_safe_exit_contract() -> None:
    for name in WRITER_WORKFLOWS:
        steps = _step_blocks(name)
        queue = next(step for step in steps if "src.writer_queue" in step)
        assert "id: writer_queue" in queue, name
        workflow_text = _workflow_text(name)
        assert "QUEUE_STATUS" in workflow_text, name
        assert any("decision" in step.lower() or "id: terminal_diagnostic" in step for step in steps), name


def test_superseded_runs_cannot_write_pages_receipts_ledgers_or_delivery_locks() -> None:
    mutation_markers = (
        "data_release --publish",
        "upload-pages-artifact",
        "deploy-pages-retry",
        "delivery_callback",
        "actions/cache/save",
    )
    for name in WRITER_WORKFLOWS:
        for step in _step_blocks(name):
            if not any(marker in step for marker in mutation_markers):
                continue
            # Diagnostic upload-artifact is intentionally not a public write.
            if "actions/upload-artifact" in step:
                continue
            condition = re.search(r"^\s+if: (.+)$", step, re.MULTILINE)
            assert condition and "should_continue" in condition.group(1), f"{name}: {step.splitlines()[0]}"


def test_research_preparation_happens_before_shared_writer_queue() -> None:
    steps = _step_blocks("unified-research-report.yml")
    names = [
        match.group(1)
        for step in steps
        if (match := re.search(r"^      - name: (.+)$", step, re.MULTILINE))
    ]
    assert names.index("Refresh market data for prepared release") < names.index(
        "Recheck production revision before persistence"
    )
    assert names.index("Gate research publication and preserve previous success") < names.index(
        "Recheck production revision before persistence"
    )
    queue = next(step for step in steps if "Recheck production revision before persistence" in step)
    assert "id: writer_queue" in queue


def test_superseded_diagnostics_use_normal_success_noop_reason() -> None:
    for name in WRITER_WORKFLOWS:
        assert "stale_workflow_superseded" in _workflow_text(name), name


def test_every_release_or_pages_publisher_is_registered_by_exact_workflow_identity() -> None:
    publishing_paths = set()
    for path in WORKFLOW_ROOT.glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        if any(marker in text for marker in (
            "python -m src.data_release --publish",
            "actions/upload-pages-artifact",
            "actions/deploy-pages",
        )):
            publishing_paths.add(f".github/workflows/{path.name}")
    assert publishing_paths <= set(WRITER_WORKFLOW_IDENTITIES)
    assert set(WRITER_WORKFLOW_IDENTITIES) <= {
        f".github/workflows/{name}" for name in WRITER_WORKFLOWS
    }


def test_every_writer_has_a_static_publication_gate_job_and_step_contract() -> None:
    assert set(WRITER_QUEUE_GATES) == set(WRITER_WORKFLOW_IDENTITIES)
    for path, gate in WRITER_QUEUE_GATES.items():
        assert gate["workflow_id"] == WRITER_WORKFLOW_IDENTITIES[path]
        workflow = yaml.safe_load(_workflow_text(Path(path).name))
        jobs = workflow.get("jobs")
        assert isinstance(jobs, dict)
        job = jobs.get(gate["job_name"])
        if job is None:
            job = next(
                (value for value in jobs.values()
                 if isinstance(value, dict) and value.get("name") == gate["job_name"]),
                None,
            )
        assert isinstance(job, dict), path
        steps = job.get("steps")
        assert isinstance(steps, list), path
        matches = [
            index for index, step in enumerate(steps)
            if isinstance(step, dict) and step.get("name") == gate["step_name"]
        ]
        assert len(matches) == 1, path
        queue_index = matches[0]
        assert steps[queue_index].get("id") == "writer_queue", path
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            content = str(step.get("run") or "") + "\n" + str(step.get("uses") or "")
            if not any(marker in content for marker in (
                "python -m src.data_release --publish",
                "actions/upload-pages-artifact",
                "actions/deploy-pages",
            )):
                continue
            if "actions/upload-artifact" in content:
                continue
            assert index > queue_index, f"{path}: publication before writer gate"
            assert "writer_queue.outputs.should_continue" in str(step.get("if") or ""), path


def test_queue_regression_uses_real_scheduled_workflow_api_identity() -> None:
    scheduled = _workflow_text("scheduled-brief.yml")
    assert "HANDOFF_PARENT_VERIFIED" in scheduled
    assert "GITHUB_RUN_ATTEMPT_STARTED_AT" in scheduled

    workflow = yaml.safe_load(scheduled)
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict)
    steps = next(
        value["steps"]
        for value in jobs.values()
        if isinstance(value, dict)
        and isinstance(value.get("steps"), list)
        and any(
            isinstance(step, dict) and step.get("id") == "early_expiry"
            for step in value["steps"]
        )
    )
    expiry_index = next(
        index for index, step in enumerate(steps)
        if isinstance(step, dict) and step.get("id") == "early_expiry"
    )
    expiry_step = steps[expiry_index]
    assert expiry_step["env"]["GITHUB_EVENT_SCHEDULE"] == "${{ github.event.schedule || '' }}"
    assert steps[expiry_index + 1]["name"] == "Install production text-delivery dependencies"
