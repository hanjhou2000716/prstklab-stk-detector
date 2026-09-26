from __future__ import annotations

from scripts import inspect_quality_run, quality_preflight


def test_mypy_failure_stops_before_targeted_and_full_tests() -> None:
    invoked: list[str] = []

    class Result:
        def __init__(self, returncode: int) -> None:
            self.returncode = returncode

    def runner(command, **_kwargs):
        if "check_quality_tools.py" in command:
            invoked.append("tool-versions")
        elif "rhysd/actionlint:1.7.7" in command:
            invoked.append("workflow-lint")
        elif command and command[0].lower().endswith(("actionlint", "actionlint.exe")):
            invoked.append("workflow-lint")
        elif "mypy" in command:
            invoked.append("mypy")
        else:
            invoked.append("ruff")
        return Result(1 if "mypy" in command else 0)

    code = quality_preflight.run_commands(
        [*quality_preflight.static_commands(), *quality_preflight.test_commands(None)],
        runner=runner,
    )

    assert code == 1
    assert invoked == ["tool-versions", "workflow-lint", "ruff", "mypy"]


def test_changed_tests_precede_full_suite(monkeypatch) -> None:
    monkeypatch.setattr(quality_preflight, "_changed_test_files", lambda _base: ["tests/test_scheduled_delivery.py"])

    commands = quality_preflight.test_commands("base-sha")

    labels = [label for label, _ in commands]
    assert labels == [
        "Reset coverage data",
        "Changed tests",
        "Full unit suite and project coverage gate",
        "Core release and delivery coverage gate",
    ]
    assert commands[1][1][-1] == "tests/test_scheduled_delivery.py"


def test_failed_gate_is_written_to_github_step_output(monkeypatch, tmp_path) -> None:
    output_file = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

    class Result:
        returncode = 1

    result = quality_preflight.run_commands(
        [("Mypy source", ["uv", "run", "mypy", "src"])],
        runner=lambda *_args, **_kwargs: Result(),
    )

    assert result == 1
    assert output_file.read_text(encoding="utf-8") == "failed_gate=Mypy source\n"


def test_report_for_pr_1013_intermediate_failure_is_superseded() -> None:
    source_run = {
        "workflow_id": 325438414,
        "pull_requests": [{"number": 1013, "head": {"sha": "4f0e300a4e5b10ed081cbed0f627a1ca9098686a"}}],
    }
    pull_request = {
        "number": 1013,
        "merged": True,
        "head": {"sha": "fc5c993e912d646225ab8069ac63979ed174aba9"},
    }
    related_runs = [
        {
            "id": 36121325085,
            "workflow_id": 325438414,
            "event": "pull_request",
            "conclusion": "success",
            "created_at": "2026-09-25T10:00:00Z",
            "pull_requests": [{"number": 1013, "head": {"sha": "fc5c993e912d646225ab8069ac63979ed174aba9"}}],
        }
    ]

    classification, message = inspect_quality_run.classify_pr_failure(
        source_run=source_run,
        pull_request=pull_request,
        related_runs=related_runs,
    )

    assert classification == "merged_latest_success"
    assert "已合併" in message


def test_workflow_reports_run_and_both_pull_request_commits() -> None:
    root = quality_preflight.ROOT
    workflow = (root / ".github" / "workflows" / "quality.yml").read_text(encoding="utf-8")

    for marker in (
        "pull_request_head_sha",
        "pull_request_base_sha",
        "workflow_tested_sha",
        "run_attempt",
        "run_url",
        "steps.test_preflight.outcome",
        "steps.static_preflight.outputs.failed_gate",
        "steps.test_preflight.outputs.failed_gate",
        "scripts/inspect_quality_run.py",
    ):
        assert marker in workflow


def test_unmerged_current_pr_head_failure_is_actionable() -> None:
    sha = "a" * 40
    source_run = {"workflow_id": 325438414, "pull_requests": [{"number": 44, "head": {"sha": sha}}]}
    pull_request = {"number": 44, "merged": False, "head": {"sha": sha}}
    related_runs = [
        {
            "workflow_id": 325438414,
            "event": "pull_request",
            "conclusion": "failure",
            "created_at": "2026-09-25T10:00:00Z",
            "pull_requests": [{"number": 44, "head": {"sha": sha}}],
        }
    ]

    classification, _ = inspect_quality_run.classify_pr_failure(
        source_run=source_run,
        pull_request=pull_request,
        related_runs=related_runs,
    )

    assert classification == "current_failure"
