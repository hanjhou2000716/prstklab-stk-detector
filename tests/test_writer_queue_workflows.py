import re
from pathlib import Path

import yaml

from src.writer_queue import (
    WRITER_QUEUE_GATES,
    WRITER_WORKFLOW_IDENTITIES,
    publication_gate_contract_fingerprint,
)

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


def _transitive_job_dependencies(job_name: str, jobs: dict[str, object]) -> set[str]:
    dependencies: set[str] = set()
    pending = [job_name]
    while pending:
        current = pending.pop()
        job = jobs.get(current)
        if not isinstance(job, dict):
            continue
        raw_needs = job.get("needs", [])
        needs = [raw_needs] if isinstance(raw_needs, str) else raw_needs
        if not isinstance(needs, list):
            continue
        for dependency in needs:
            if isinstance(dependency, str) and dependency not in dependencies:
                dependencies.add(dependency)
                pending.append(dependency)
    return dependencies


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
        gate_job_name = str(gate["job_name"])
        if job is None:
            gate_job_name, job = next(
                ((name, value) for name, value in jobs.items()
                 if isinstance(value, dict) and value.get("name") == gate["job_name"]),
                (gate_job_name, None),
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
        all_gate_steps = [
            (job_name, step)
            for job_name, candidate_job in jobs.items()
            if isinstance(candidate_job, dict)
            for step in candidate_job.get("steps", [])
            if isinstance(step, dict)
            and step.get("id") == "writer_queue"
            and step.get("name") == gate["step_name"]
        ]
        assert all_gate_steps == [(gate_job_name, steps[queue_index])], path
        fingerprint = publication_gate_contract_fingerprint(path, gate)
        assert re.fullmatch(r"[0-9a-f]{64}", fingerprint), path
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

        # A writer may publish in a downstream job only when its `needs` graph
        # proves that the gate job completed first. Telegram senders are held
        # to the same rule as Pages and release writes.
        publication_markers = (
            "python -m src.data_release --publish",
            "actions/upload-pages-artifact",
            "actions/deploy-pages",
        )
        for candidate_job_name, candidate_job in jobs.items():
            if not isinstance(candidate_job, dict):
                continue
            candidate_steps = candidate_job.get("steps", [])
            if not isinstance(candidate_steps, list):
                continue
            for index, step in enumerate(candidate_steps):
                if not isinstance(step, dict):
                    continue
                content = str(step.get("run") or "") + "\n" + str(step.get("uses") or "")
                step_env = step.get("env") if isinstance(step.get("env"), dict) else {}
                step_name = str(step.get("name") or "")
                is_sender = "TELEGRAM_BOT_TOKEN" in step_env or "Send Telegram" in step_name
                is_publication = any(marker in content for marker in publication_markers)
                if not is_sender and not is_publication:
                    continue
                if candidate_job_name == gate_job_name:
                    assert index > queue_index, f"{path}: sender/publication before writer gate"
                    assert "writer_queue.outputs.should_continue" in str(step.get("if") or ""), path
                    continue
                assert gate_job_name in _transitive_job_dependencies(candidate_job_name, jobs), (
                    f"{path}: sender/publication job {candidate_job_name} does not depend on gate job {gate_job_name}"
                )


def test_queue_regression_uses_real_scheduled_workflow_api_identity() -> None:
    scheduled = _workflow_text("scheduled-brief.yml")
    assert "HANDOFF_PARENT_VERIFIED" in scheduled
    assert "GITHUB_RUN_ATTEMPT_STARTED_AT" in scheduled

    workflow = yaml.safe_load(scheduled)
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict)
    assert jobs["refresh-notify-deploy"]["needs"] == "occurrence"
    assert jobs["refresh-notify-deploy"]["if"] == "needs.occurrence.outputs.expired != 'true'"
    assert jobs["refresh-notify-deploy"]["environment"]["name"] == "github-pages"
    occurrence_steps = jobs["occurrence"]["steps"]
    occurrence_expiry_index = next(
        index for index, step in enumerate(occurrence_steps)
        if isinstance(step, dict) and step.get("id") == "early_expiry"
    )
    assert occurrence_steps[occurrence_expiry_index + 1]["name"] == "Record expired occurrence terminal state"
    steps = jobs["refresh-notify-deploy"]["steps"]
    expiry_index = next(
        index for index, step in enumerate(steps)
        if isinstance(step, dict) and step.get("id") == "late_expiry"
    )
    expiry_step = steps[expiry_index]
    assert expiry_step["env"]["GITHUB_EVENT_SCHEDULE"] == "${{ github.event.schedule || '' }}"
    assert steps[expiry_index + 1]["name"] == "Set up Python"
    assert steps[expiry_index + 1]["if"] == "steps.late_expiry.outputs.expired != 'true'"
    assert steps[expiry_index + 2]["name"] == "Install production text-delivery dependencies"
    assert steps[expiry_index + 2]["if"] == "steps.late_expiry.outputs.expired != 'true'"
    assert any(
        step.get("name") == "Upload scheduled terminal record"
        and "github.run_attempt" in step["with"]["name"]
        for step in steps
        if isinstance(step, dict)
    )
    terminal_index = next(
        index for index, step in enumerate(steps)
        if isinstance(step, dict) and step.get("id") == "terminal_diagnostic"
    )
    for step in steps:
        if not isinstance(step, dict) or "always()" not in str(step.get("if") or ""):
            continue
        if step.get("id") == "terminal_diagnostic" or step.get("name") == "Upload scheduled terminal record":
            continue
        if step.get("name") == "Upload scheduled preparation record":
            assert "steps.late_expiry.outputs.expired != 'true'" in str(step.get("if") or "")
            continue
        assert "steps.late_expiry.outputs.expired != 'true'" in str(step.get("if") or "")
    assert steps[terminal_index + 1]["name"] == "Upload scheduled terminal record"
