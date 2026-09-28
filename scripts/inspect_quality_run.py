"""Read-only classification of an Actions quality run against its PR or main state."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

QUALITY_WORKFLOW_NAME = "Quality and delivery dry-run"
PULL_REF_RE = re.compile(r"^refs/pull/(\d+)/merge$")


def _associated_pr(run: dict[str, Any]) -> int | None:
    """Return a PR number only when the run identifies exactly one PR."""
    pull_requests = run.get("pull_requests")
    if isinstance(pull_requests, list) and pull_requests:
        numbers = {
            item.get("number") for item in pull_requests
            if isinstance(item, dict) and isinstance(item.get("number"), int)
        }
        return next(iter(numbers)) if len(numbers) == 1 else None
    match = PULL_REF_RE.fullmatch(str(run.get("head_branch") or run.get("event_name") or ""))
    return int(match.group(1)) if match else None


def _quality_runs(runs: list[dict[str, Any]], workflow_id: int | None) -> list[dict[str, Any]]:
    return sorted(
        (
            run for run in runs
            if (workflow_id is not None and run.get("workflow_id") == workflow_id)
            or (workflow_id is None and run.get("name") == QUALITY_WORKFLOW_NAME)
        ),
        key=lambda run: (str(run.get("created_at") or ""), int(run.get("run_attempt") or 1)),
        reverse=True,
    )


def _pr_runs_for_head(
    runs: list[dict[str, Any]], pr_number: int, head_sha: str, workflow_id: int | None,
) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for run in _quality_runs(runs, workflow_id):
        if run.get("event") != "pull_request":
            continue
        associated = any(
            isinstance(pull_request, dict)
            and pull_request.get("number") == pr_number
            and (pull_request.get("head") or {}).get("sha") == head_sha
            for pull_request in run.get("pull_requests") or []
        )
        # Some Actions run payloads omit pull_requests entirely. An exact full
        # head SHA remains sufficient to associate the check with this version.
        if associated or str(run.get("head_sha") or "") == head_sha:
            matched.append(run)
    return matched


def _runs_for_sha(
    repository: str,
    head_sha: str,
    workflow_id: int | None,
    *,
    runner: Callable[..., Any],
) -> list[dict[str, Any]]:
    """Fetch checks by immutable commit identity, never by a branch guess."""
    runs: list[dict[str, Any]] = []
    for page in range(1, 6):
        query = urlencode({"head_sha": head_sha, "per_page": 100, "page": page})
        payload = _gh_json(f"repos/{repository}/actions/runs?{query}", runner=runner)
        page_runs = payload.get("workflow_runs") or []
        runs.extend(page_runs)
        if len(page_runs) < 100:
            break
    return [
        run for run in _quality_runs(runs, workflow_id)
        if str(run.get("head_sha") or "") == head_sha
        or any(
            (pull_request.get("head") or {}).get("sha") == head_sha
            for pull_request in run.get("pull_requests") or []
            if isinstance(pull_request, dict)
        )
    ]


def _commit_associated_pr(
    repository: str,
    commit_sha: str,
    *,
    runner: Callable[..., Any],
) -> tuple[int | None, str]:
    """Resolve an Actions run without PR metadata through commit association."""
    if not re.fullmatch(r"[0-9a-fA-F]{40}", commit_sha):
        return None, "Run 未提供完整提交 SHA，無法安全查詢關聯 PR。"
    payload = _gh_json(
        f"repos/{repository}/commits/{commit_sha}/pulls?per_page=100",
        runner=runner,
    )
    if not isinstance(payload, list):
        return None, "提交關聯 PR API 回傳格式無法確認。"
    matches = {
        int(item["number"])
        for item in payload
        if isinstance(item, dict)
        and isinstance(item.get("number"), int)
        and ((item.get("base") or {}).get("repo") or {}).get("full_name") == repository
    }
    if len(matches) == 1:
        return next(iter(matches)), ""
    if len(matches) > 1:
        return None, "同一提交關聯多個 PR，無法唯一確認。"
    return None, "Run 未提供 PR 身份，提交關聯 API 也未找到同儲存庫 PR。"


def _failed_gates(
    repository: str,
    run_id: int,
    *,
    runner: Callable[..., Any],
) -> list[dict[str, str]]:
    """Return only sanitized job and step names, never logs or environment."""
    payload = _gh_json(
        f"repos/{repository}/actions/runs/{run_id}/jobs?per_page=100",
        runner=runner,
    )
    jobs = (payload.get("jobs") or []) if isinstance(payload, dict) else []
    failures: list[dict[str, str]] = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        job_name = str(job.get("name") or "unnamed job")[:160]
        failed_steps = [
            str(step.get("name") or "unnamed step")[:160]
            for step in job.get("steps") or []
            if isinstance(step, dict)
            and step.get("conclusion") in {"failure", "cancelled", "timed_out"}
        ]
        if failed_steps:
            failures.extend({"job": job_name, "step": step} for step in failed_steps)
        elif job.get("conclusion") in {"failure", "cancelled", "timed_out"}:
            failures.append({"job": job_name, "step": "step details unavailable"})
    return failures


def _main_quality_state(
    repository: str,
    workflow_id: int | None,
    *,
    runner: Callable[..., Any],
) -> dict[str, Any]:
    main = _gh_json(f"repos/{repository}/branches/main", runner=runner)
    main_sha = str((main.get("commit") or {}).get("sha") or "")
    result: dict[str, Any] = {"current_main_sha": main_sha, "main_quality_classification": "unknown"}
    if not re.fullmatch(r"[0-9a-fA-F]{40}", main_sha):
        result["main_quality_message"] = "目前 main SHA 無法確認。"
        return result
    runs = _runs_for_sha(repository, main_sha, workflow_id, runner=runner)
    main_runs = [run for run in runs if run.get("event") != "pull_request"]
    latest = main_runs[0] if main_runs else None
    if latest is None:
        result["main_quality_classification"] = "pending"
        result["main_quality_message"] = "目前 main SHA 尚無可核對的品質 workflow run。"
        return result
    result.update({
        "main_quality_run_id": latest.get("id"),
        "main_quality_conclusion": latest.get("conclusion"),
        "main_quality_run_url": latest.get("html_url"),
    })
    if latest.get("conclusion") == "success":
        result["main_quality_classification"] = "success"
        result["main_quality_message"] = "目前 main SHA 的最新品質檢查成功。"
    elif latest.get("conclusion") in {"failure", "cancelled", "timed_out", "action_required"}:
        result["main_quality_classification"] = "failure"
        result["main_quality_message"] = "目前 main SHA 的最新品質檢查未通過。"
    else:
        result["main_quality_classification"] = "pending"
        result["main_quality_message"] = "目前 main SHA 的品質檢查仍在執行或尚無結論。"
    return result


def classify_pr_failure(
    *,
    source_run: dict[str, Any],
    pull_request: dict[str, Any],
    related_runs: list[dict[str, Any]],
) -> tuple[str, str]:
    number = int(pull_request["number"])
    current_sha = str((pull_request.get("head") or {}).get("sha") or "")
    source_sha = str(source_run.get("head_sha") or ((((source_run.get("pull_requests") or [{}])[0]).get("head") or {}).get("sha") or ""))
    workflow_id = source_run.get("workflow_id")
    latest = _pr_runs_for_head(related_runs, number, current_sha, workflow_id)
    latest_conclusion = str(latest[0].get("conclusion") or latest[0].get("status") or "unknown") if latest else "missing"

    if pull_request.get("merged") is True:
        if latest and latest[0].get("conclusion") == "success":
            return "merged_latest_success", "PR 已合併，最後提交的品質檢查通過。"
        return "merged_check_unverified", "PR 已合併，但未找到最後提交的成功品質檢查。"
    if current_sha != source_sha:
        if latest_conclusion == "success":
            return "superseded_by_success", "同一 PR 的較新提交已通過品質檢查；此失敗 run 已被取代。"
        if latest_conclusion in {"failure", "cancelled", "timed_out", "action_required"}:
            return "latest_head_failing", "PR 已更新，但目前最新提交的品質檢查仍未通過。"
        return "latest_head_pending", "PR 已更新；最新提交尚無已完成的成功品質檢查。"
    if latest_conclusion == "success":
        return "superseded_by_success", "相同 PR 提交的較新檢查已成功；此失敗 run 已被取代。"
    if latest_conclusion in {"failure", "cancelled", "timed_out", "action_required"}:
        return "current_failure", "PR 目前提交的品質檢查仍失敗。"
    return "current_check_pending", "PR 目前提交尚無已完成的成功品質檢查。"


def _gh_json(path: str, *, runner: Callable[..., Any] = subprocess.run) -> Any:
    completed = runner(["gh", "api", path], check=False, capture_output=True, text=True)
    if completed.returncode:
        raise RuntimeError("GitHub CLI request failed; verify gh authentication and read access.")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GitHub API returned invalid JSON.") from exc


def _runs_for_pr(
    repository: str,
    pr_number: int,
    head_sha: str,
    workflow_id: int | None,
    *,
    runner: Callable[..., Any],
) -> list[dict[str, Any]]:
    runs = _runs_for_sha(repository, head_sha, workflow_id, runner=runner)
    return _pr_runs_for_head(runs, pr_number, head_sha, workflow_id)


def inspect(repository: str, run_id: int, *, runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    source = _gh_json(f"repos/{repository}/actions/runs/{run_id}", runner=runner)
    if source.get("name") != QUALITY_WORKFLOW_NAME:
        raise RuntimeError("The selected run is not the quality workflow.")
    if source.get("conclusion") not in {"failure", "cancelled", "timed_out", "action_required"}:
        raise RuntimeError("The selected quality run does not have a failed conclusion.")
    result: dict[str, Any] = {
        "run_id": run_id,
        "run_url": source.get("html_url"),
        "run_conclusion": source.get("conclusion"),
        "run_sha": source.get("head_sha"),
        "classification": "unknown",
        "failed_gates": [],
        "failed_gates_status": "unavailable",
    }
    try:
        result["failed_gates"] = _failed_gates(repository, run_id, runner=runner)
        result["failed_gates_status"] = "available"
    except RuntimeError:
        # Keep the primary run/PR classification useful if job-detail access is
        # temporarily unavailable, while exposing that the failed gate is unknown.
        result["failed_gates_status"] = "unavailable"

    pr_number = _associated_pr(source)
    if pr_number is None:
        source_sha = str(source.get("head_sha") or "")
        if str(source.get("head_branch") or "") == "main":
            result.update(_main_quality_state(repository, source.get("workflow_id"), runner=runner))
            main_sha = result.get("current_main_sha")
            if main_sha == source_sha and result.get("main_quality_classification") == "success":
                result["classification"] = "superseded_by_success"
                result["message"] = "main 最新提交已有成功的品質檢查；此失敗 run 已被成功重跑取代。"
            elif main_sha == source_sha and result.get("main_quality_classification") == "failure":
                result["classification"] = "current_failure"
                result["message"] = "失敗 run 的提交仍是 main 最新提交，最新品質檢查仍失敗。"
            else:
                result["classification"] = "latest_main_unverified"
                result["message"] = "main 的最新品質檢查未成功或尚無法確認。"
            return result
        pr_number, association_message = _commit_associated_pr(
            repository, source_sha, runner=runner,
        )
        if pr_number is None:
            result["message"] = association_message
            return result

    pr = _gh_json(f"repos/{repository}/pulls/{pr_number}", runner=runner)
    pr_head_sha = str((pr.get("head") or {}).get("sha") or "")
    runs = _runs_for_pr(
        repository,
        pr_number,
        pr_head_sha,
        source.get("workflow_id"),
        runner=runner,
    )
    classification, message = classify_pr_failure(source_run=source, pull_request=pr, related_runs=runs)
    result.update(
        {
            "pr_number": pr_number,
            "pr_url": pr.get("html_url"),
            "pr_state": pr.get("state"),
            "pr_merged": pr.get("merged"),
            "pr_head_sha": pr_head_sha,
            "merge_commit_sha": pr.get("merge_commit_sha"),
            "pr_latest_quality_classification": classification,
            "classification": classification,
            "message": message,
        }
    )
    latest_runs = _pr_runs_for_head(
        runs,
        pr_number,
        pr_head_sha,
        source.get("workflow_id"),
    )
    if latest_runs:
        result["latest_quality_run_id"] = latest_runs[0].get("id")
        result["latest_quality_conclusion"] = latest_runs[0].get("conclusion")
        result["latest_quality_run_url"] = latest_runs[0].get("html_url")
    result.update(_main_quality_state(repository, source.get("workflow_id"), runner=runner))
    result["three_evidence_summary"] = {
        "failed_run": {
            "sha": result.get("run_sha"),
            "conclusion": result.get("run_conclusion"),
            "url": result.get("run_url"),
            "failed_gates": result.get("failed_gates"),
        },
        "pr_last_commit": {
            "sha": result.get("pr_head_sha"),
            "classification": result.get("pr_latest_quality_classification"),
            "run_id": result.get("latest_quality_run_id"),
            "conclusion": result.get("latest_quality_conclusion"),
        },
        "current_main": {
            "sha": result.get("current_main_sha"),
            "classification": result.get("main_quality_classification"),
            "run_id": result.get("main_quality_run_id"),
            "conclusion": result.get("main_quality_conclusion"),
        },
    }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="GitHub repository as owner/name")
    parser.add_argument("--run-id", required=True, type=int, help="GitHub Actions run ID from the email or run URL")
    args = parser.parse_args(argv)
    try:
        result = inspect(args.repo, args.run_id)
    except (RuntimeError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"classification": "unknown", "message": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if result["classification"] == "unknown":
        return 2
    failing_classifications = {
        "current_failure",
        "latest_head_failing",
        "merged_check_unverified",
        "latest_main_unverified",
    }
    if result["classification"] in failing_classifications:
        return 1
    if result.get("main_quality_classification", "success") != "success":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
