from pathlib import Path

import yaml

WORKFLOW_ROOT = Path(__file__).resolve().parents[1] / ".github" / "workflows"
WRITER_WORKFLOWS = (
    "official-event-monitor.yml",
    "scheduled-brief.yml",
    "emergency-alert.yml",
    "refresh-dashboard.yml",
    "monitor-health.yml",
    "unified-research-report.yml",
)


def _steps(name: str) -> list[dict[str, object]]:
    workflow = yaml.safe_load((WORKFLOW_ROOT / name).read_text(encoding="utf-8"))
    job = next(iter(workflow["jobs"].values()))
    return list(job["steps"])


def test_every_shared_writer_has_an_id_and_safe_exit_contract() -> None:
    for name in WRITER_WORKFLOWS:
        steps = _steps(name)
        queue = next(
            step
            for step in steps
            if "src.writer_queue" in str(step.get("run", ""))
        )
        assert queue.get("id") == "writer_queue", name
        assert "src.writer_queue" in str(queue.get("run")), name
        workflow_text = (WORKFLOW_ROOT / name).read_text(encoding="utf-8")
        assert "QUEUE_STATUS" in workflow_text, name
        assert any("decision" in str(step.get("name", "")).lower() for step in steps), name


def test_superseded_runs_cannot_write_pages_receipts_ledgers_or_delivery_locks() -> None:
    mutation_markers = (
        "data_release --publish",
        "upload-pages-artifact",
        "deploy-pages-retry",
        "delivery_callback",
        "actions/cache/save",
    )
    for name in WRITER_WORKFLOWS:
        for step in _steps(name):
            text = " ".join(str(step.get(key, "")) for key in ("name", "run", "uses"))
            if not any(marker in text for marker in mutation_markers):
                continue
            # Diagnostic upload-artifact is intentionally not a public write.
            if "actions/upload-artifact" in str(step.get("uses", "")):
                continue
            condition = str(step.get("if", ""))
            assert "should_continue" in condition, f"{name}: {step.get('name', '<unnamed>')}"


def test_research_preparation_happens_before_shared_writer_queue() -> None:
    steps = _steps("unified-research-report.yml")
    names = [str(step.get("name", "")) for step in steps]
    assert names.index("Refresh market data for prepared release") < names.index(
        "Recheck production revision before persistence"
    )
    assert names.index("Gate research publication and preserve previous success") < names.index(
        "Recheck production revision before persistence"
    )
    queue = next(step for step in steps if step.get("name") == "Recheck production revision before persistence")
    assert queue.get("id") == "writer_queue"


def test_superseded_diagnostics_use_normal_success_noop_reason() -> None:
    for name in WRITER_WORKFLOWS:
        text = (WORKFLOW_ROOT / name).read_text(encoding="utf-8")
        assert "stale_workflow_superseded" in text, name
