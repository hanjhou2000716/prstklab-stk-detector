import re
from pathlib import Path

WORKFLOW_ROOT = Path(__file__).resolve().parents[1] / ".github" / "workflows"
WRITER_WORKFLOWS = (
    "official-event-monitor.yml",
    "scheduled-brief.yml",
    "emergency-alert.yml",
    "refresh-dashboard.yml",
    "monitor-health.yml",
    "unified-research-report.yml",
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
        assert any("decision" in step.lower() for step in steps), name


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
