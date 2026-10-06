"""Classify failed GitHub workflow runs without inferring unobserved side effects."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

_RUNNER_ALLOCATION = re.compile(
    r"(?:failed|unable|unable to|not able) to (?:acquire|allocate|assign).*runner|"
    r"hosted runner.*(?:unavailable|allocation|acquire)|runner allocation",
    re.IGNORECASE,
)


def _started(value: object) -> bool:
    return bool(str(value or "").strip())


def classify_workflow_execution(
    run: Mapping[str, Any],
    jobs: Sequence[Mapping[str, Any]],
    annotations: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Separate runner allocation, executed-step, and unknown-result failures."""
    normalized_jobs = [job for job in jobs if isinstance(job, Mapping)]
    steps: list[Mapping[str, Any]] = []
    for job in normalized_jobs:
        job_steps = job.get("steps")
        if isinstance(job_steps, list):
            steps.extend(step for step in job_steps if isinstance(step, Mapping))
    any_started = _started(run.get("run_started_at")) or any(
        _started(job.get("started_at")) or bool(job.get("runner_id")) or any(
            _started(step.get("started_at")) for step in (job.get("steps") or [])
            if isinstance(step, Mapping)
        )
        for job in normalized_jobs
    )
    annotation_text = " ".join(
        f"{item.get('title', '')} {item.get('message', '')} {item.get('annotation_level', '')}"
        for item in annotations if isinstance(item, Mapping)
    )
    status = str(run.get("status") or "unknown").casefold()
    conclusion = str(run.get("conclusion") or "").casefold()
    if not any_started and status in {"queued", "waiting", "pending", "requested"}:
        classification = "queued_not_started"
        reason = "workflow_has_not_reached_a_runner"
    elif not any_started and conclusion == "failure" and _RUNNER_ALLOCATION.search(annotation_text):
        classification = "platform_runner_allocation_failed"
        reason = "hosted_runner_unavailable_before_any_step"
    elif not any_started:
        classification = "pre_step_failure_unclassified"
        reason = "no_runner_or_step_evidence_and_no_authoritative_platform_annotation"
    else:
        failed_steps = [
            str(step.get("name") or "") for step in steps
            if str(step.get("conclusion") or "").casefold() == "failure"
        ]
        if failed_steps:
            classification = "workflow_step_failed"
            reason = "failed_step_recorded"
        elif conclusion == "failure":
            classification = "execution_result_unknown"
            reason = "run_failed_after_start_without_a_failed_step_record"
        else:
            classification = "execution_in_progress_or_nonfailure"
            reason = "run_state_does_not_establish_failure"
    return {
        "schema_version": "workflow-execution-diagnostic-v1",
        "classification": classification,
        "reason": reason,
        "runner_started": any_started,
        "step_count": len(steps),
        "failed_step_names": failed_steps if any_started else [],
        "install_state": "not_run" if not any_started else "inspect_steps",
        "sync_state": "not_run" if not any_started else "inspect_steps",
        "source_health": "not_checked" if not any_started else "inspect_result",
        "result_contract": "not_checked" if not any_started else "inspect_result",
        "cursor_effect": "not_touched" if not any_started else "unknown",
    }
