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
    pull_requests = run.get("pull_requests")
    if isinstance(pull_requests, list) and pull_requests:
        number = pull_requests[0].get("number")
        if isinstance(number, int):
            return number
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


def _pr_runs_for_head(runs: list[dict[str, Any]], pr_number: int, head_sha: str, workflow_id: int | None) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for run in _quality_runs(runs, workflow_id):
        if run.get("event") != "pull_request":
            continue
        for pull_request in run.get("pull_requests") or []:
            if pull_request.get("number") == pr_number and (pull_request.get("head") or {}).get("sha") == head_sha:
                matched.append(run)
                break
    return matched


def classify_pr_failure(
    *,
    source_run: dict[str, Any],
    pull_request: dict[str, Any],
    related_runs: list[dict[str, Any]],
) -> tuple[str, str]:
    number = int(pull_request["number"])
    current_sha = str((pull_request.get("head") or {}).get("sha") or "")
    source_sha = str((((source_run.get("pull_requests") or [{}])[0]).get("head") or {}).get("sha") or "")
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
    head_branch: str,
    workflow_id: int | None,
    *,
    runner: Callable[..., Any],
) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for page in range(1, 6):
        query = urlencode({"branch": head_branch, "event": "pull_request", "per_page": 100, "page": page})
        payload = _gh_json(
            f"repos/{repository}/actions/runs?{query}",
            runner=runner,
        )
        page_runs = payload.get("workflow_runs") or []
        runs.extend(page_runs)
        if len(page_runs) < 100:
            break
    return [
        run for run in runs
        if any(item.get("number") == pr_number for item in run.get("pull_requests") or [])
        and ((workflow_id is not None and run.get("workflow_id") == workflow_id) or (workflow_id is None and run.get("name") == QUALITY_WORKFLOW_NAME))
    ]


def inspect(repository: str, run_id: int, *, runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    source = _gh_json(f"repos/{repository}/actions/runs/{run_id}", runner=runner)
    if source.get("name") != QUALITY_WORKFLOW_NAME:
        raise RuntimeError("The selected run is not the quality workflow.")
    if source.get("conclusion") not in {"failure", "cancelled", "timed_out", "action_required"}:
        raise RuntimeError("The selected quality run does not have a failed conclusion.")
    pr_number = _associated_pr(source)
    result: dict[str, Any] = {
        "run_id": run_id,
        "run_url": source.get("html_url"),
        "run_conclusion": source.get("conclusion"),
        "run_sha": source.get("head_sha"),
        "classification": "unknown",
    }
    if pr_number is None:
        branch = str(source.get("head_branch") or "")
        if branch != "main":
            result["message"] = "Run 未提供可驗證的 PR 或 main 身份。"
            return result
        main = _gh_json(f"repos/{repository}/branches/main", runner=runner)
        main_sha = str((main.get("commit") or {}).get("sha") or "")
        result["current_main_sha"] = main_sha
        latest_runs = _gh_json(
            f"repos/{repository}/actions/runs?head_sha={main_sha}&per_page=100",
            runner=runner,
        ).get("workflow_runs") or []
        latest = _quality_runs(latest_runs, source.get("workflow_id"))
        if main_sha == str(source.get("head_sha") or ""):
            if latest and latest[0].get("conclusion") == "success":
                result["classification"] = "superseded_by_success"
                result["message"] = "main 最新提交已有成功的品質檢查；此失敗 run 已被成功重跑取代。"
            elif latest and latest[0].get("conclusion") == "failure":
                result["classification"] = "current_failure"
                result["message"] = "失敗 run 的提交仍是 main 最新提交，最新品質檢查仍失敗。"
            else:
                result["classification"] = "latest_main_unverified"
                result["message"] = "失敗 run 的提交仍是 main 最新提交，但尚無成功檢查證據。"
        else:
            if latest and latest[0].get("conclusion") == "success":
                result["classification"] = "superseded_by_success"
                result["message"] = "main 已前進，且最新 main 提交的品質檢查成功。"
            else:
                result["classification"] = "latest_main_unverified"
                result["message"] = "main 已前進，但最新 main 提交尚無已確認的成功品質檢查。"
        return result

    pr = _gh_json(f"repos/{repository}/pulls/{pr_number}", runner=runner)
    runs = _runs_for_pr(
        repository,
        pr_number,
        str((pr.get("head") or {}).get("ref") or ""),
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
            "pr_head_sha": (pr.get("head") or {}).get("sha"),
            "merge_commit_sha": pr.get("merge_commit_sha"),
            "classification": classification,
            "message": message,
        }
    )
    latest_runs = _pr_runs_for_head(
        runs,
        pr_number,
        str((pr.get("head") or {}).get("sha") or ""),
        source.get("workflow_id"),
    )
    if latest_runs:
        result["latest_quality_run_id"] = latest_runs[0].get("id")
        result["latest_quality_conclusion"] = latest_runs[0].get("conclusion")
        result["latest_quality_run_url"] = latest_runs[0].get("html_url")
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
    return 1 if result["classification"] in {
        "current_failure",
        "latest_head_failing",
        "merged_check_unverified",
        "latest_main_unverified",
    } else 0


if __name__ == "__main__":
    raise SystemExit(main())
