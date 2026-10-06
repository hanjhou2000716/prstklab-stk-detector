from src.workflow_execution_diagnostics import classify_workflow_execution


def test_hosted_runner_failure_before_steps_is_not_misreported_as_gmail_failure():
    result = classify_workflow_execution(
        {"status": "completed", "conclusion": "failure", "run_started_at": None},
        [{"status": "completed", "runner_id": 0, "started_at": None, "steps": []}],
        [{"title": "GitHub Actions runner", "message": "Unable to acquire a hosted runner"}],
    )

    assert result["classification"] == "platform_runner_allocation_failed"
    assert result["install_state"] == "not_run"
    assert result["sync_state"] == "not_run"
    assert result["source_health"] == "not_checked"
    assert result["result_contract"] == "not_checked"
    assert result["cursor_effect"] == "not_touched"
    assert result["failed_step_names"] == []


def test_queued_work_without_runner_is_not_a_failed_execution():
    result = classify_workflow_execution(
        {"status": "queued"},
        [{"status": "queued", "runner_id": 0, "steps": None}],
        [],
    )

    assert result["classification"] == "queued_not_started"
    assert result["cursor_effect"] == "not_touched"


def test_started_failure_with_a_failed_step_is_classified_by_stage_evidence():
    result = classify_workflow_execution(
        {"status": "completed", "conclusion": "failure", "run_started_at": "2026-10-06T00:00:00Z"},
        [{"name": "sync", "runner_id": 23, "steps": [
            {"name": "Install Gmail sync dependencies", "conclusion": "success"},
            {"name": "Run Gmail history sync", "conclusion": "failure"},
        ]}],
    )

    assert result["classification"] == "workflow_step_failed"
    assert result["failed_step_names"] == ["Run Gmail history sync"]
    assert result["cursor_effect"] == "unknown"


def test_started_failure_without_step_failure_keeps_result_unknown():
    result = classify_workflow_execution(
        {"status": "completed", "conclusion": "failure", "run_started_at": "2026-10-06T00:00:00Z"},
        [{"runner_id": 23, "steps": [{"name": "sync", "conclusion": "success"}] }],
    )

    assert result["classification"] == "execution_result_unknown"
    assert result["cursor_effect"] == "unknown"
