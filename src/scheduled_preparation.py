"""Bounded preparation coordinator for immutable scheduled market releases."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.market_source_watch import watch_quotes_supersede_snapshot

SCHEMA_VERSION = "scheduled-preparation-v1"


@dataclass(frozen=True)
class PreparationWindow:
    first_attempt_deadline: float
    overall_deadline: float
    source_check_deadline: float
    delivery_deadline: float


def preparation_window(slot: str, scheduled_for: str, started_at: float) -> PreparationWindow:
    anchor = datetime.fromisoformat(scheduled_for.replace("Z", "+00:00"))
    if anchor.tzinfo is None or anchor.utcoffset() is None:
        raise ValueError("scheduled_anchor_timezone_missing")
    anchor_epoch = anchor.timestamp()
    delivery_deadline = anchor_epoch + 30 * 60
    source_check_deadline = anchor_epoch + 20 * 60
    first_attempt_deadline = min(started_at + 8 * 60, source_check_deadline)
    max_prepare_seconds = 13 * 60 if slot == "post_close" else 8 * 60
    overall_deadline = min(started_at + max_prepare_seconds, delivery_deadline - 5 * 60)
    return PreparationWindow(
        first_attempt_deadline=first_attempt_deadline,
        overall_deadline=overall_deadline,
        source_check_deadline=source_check_deadline,
        delivery_deadline=delivery_deadline,
    )


def _remaining(deadline: float, clock: Callable[[], float]) -> int:
    return max(0, int(deadline - clock()))


def _utc_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, UTC).isoformat()


def _read_key_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith(" "):
            key, value = line.split("=", 1)
            if key.replace("_", "").isalnum():
                values[key] = value
    return values


def _append_output(path: str, values: dict[str, Any]) -> None:
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as stream:
        for key, value in values.items():
            if "\n" in str(value) or "\r" in str(value):
                continue
            stream.write(f"{key}={value}\n")


def _append_summary(path: str, result: dict[str, Any], source_result: dict[str, Any] | None) -> None:
    if not path:
        return
    rendered = json.dumps(result, ensure_ascii=False, sort_keys=True)
    with Path(path).open("a", encoding="utf-8") as stream:
        stream.write("### Scheduled preparation coordinator\n\n```json\n")
        stream.write(rendered + "\n```\n")
        if source_result is not None:
            stream.write("\n末次官方來源證據：\n\n```json\n")
            stream.write(json.dumps(source_result, ensure_ascii=False, sort_keys=True) + "\n```\n")


def _persist_result(path: str, result: dict[str, Any]) -> None:
    if not path:
        return
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(destination)


def _run_command(
    command: Sequence[str], *, timeout_seconds: int, env: dict[str, str],
    run: Callable[..., subprocess.CompletedProcess[str]],
) -> subprocess.CompletedProcess[str]:
    # Callers inspect stdout for commands such as git rev-parse. Capture both
    # streams explicitly so result handling never depends on subprocess defaults.
    return run(
        command, timeout=max(1, timeout_seconds), env=env, check=False,
        text=True, capture_output=True,
    )


def _resolved_commit(result: subprocess.CompletedProcess[str]) -> str:
    if result.returncode != 0:
        return ""
    value = (result.stdout or "").strip()
    return value.lower() if re.fullmatch(r"[0-9a-fA-F]{40}", value) else ""


def coordinate_preparation(
    *,
    slot: str,
    scheduled_for: str,
    slot_context: str,
    notification_requested: str,
    snapshot_path: str,
    data_release_branch: str,
    initial_source_status: str,
    environ: dict[str, str] | None = None,
    clock: Callable[[], float] = time.time,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    popen: Callable[..., subprocess.Popen[Any]] = subprocess.Popen,
) -> tuple[dict[str, Any], int]:
    """Prepare, optionally rebuild once, and verify one immutable data base."""
    env = dict(os.environ if environ is None else environ)
    started_at = clock()
    window = preparation_window(slot, scheduled_for, started_at)
    source_process: subprocess.Popen[Any] | None = None
    source_path: Path | None = None
    override_path: Path | None = None
    temp_paths: list[Path] = []
    stage = "initialize"
    stage_started_at = started_at
    stage_history: list[dict[str, Any]] = []
    attempt = 0
    rebuild_reason = "none"
    source_status = "not_required"
    base_sha = ""
    current_sha = ""
    latest_values: dict[str, str] = {}
    source_result: dict[str, Any] | None = None
    source_rebuild_count = 0
    failure_reason = ""

    def enter_stage(name: str) -> None:
        nonlocal stage, stage_started_at
        current = clock()
        stage_history.append({
            "stage": stage,
            "started_at": _utc_timestamp(stage_started_at),
            "finished_at": _utc_timestamp(current),
            "duration_seconds": max(0, round(current - stage_started_at, 3)),
        })
        stage = name
        stage_started_at = current

    def close_stage() -> None:
        current = clock()
        stage_history.append({
            "stage": stage,
            "started_at": _utc_timestamp(stage_started_at),
            "finished_at": _utc_timestamp(current),
            "duration_seconds": max(0, round(current - stage_started_at, 3)),
        })

    def result_context() -> dict[str, Any]:
        return {
            "started_at": _utc_timestamp(started_at),
            "finished_at": _utc_timestamp(clock()),
            "source_check_deadline": _utc_timestamp(window.source_check_deadline),
            "delivery_deadline": _utc_timestamp(window.delivery_deadline),
            "remaining_budget_seconds": _remaining(window.overall_deadline, clock),
            "rebuild_count": max(0, attempt - 1),
            "first_failure_reason": failure_reason,
            "candidate_identity": {
                "snapshot_id": latest_values.get("snapshot_id", ""),
                "data_release_sha": base_sha or "unknown",
            },
            "stage_history": list(stage_history),
        }

    if slot == "post_close" and initial_source_status != "both_official_closes_available":
        source_file = tempfile.NamedTemporaryFile(prefix="prstk-final-source-", suffix=".json", delete=False)
        source_file.close()
        source_path = Path(source_file.name)
        temp_paths.append(source_path)
        source_env = dict(env)
        for name in (
            "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_IDS",
            "TELEGRAM_SUBSCRIBERS_PATH", "PUBLIC_OBSERVATIONS_SHARED_SECRET", "RECEIPT_CALLBACK_URL",
            "RAILWAY_STATUS_URL", "RAILWAY_STATUS_SHARED_SECRET", "DELIVERY_RECEIPT_SHARED_SECRET",
            "RAILWAY_OBSERVATIONS_URL", "PUBLIC_OBSERVATIONS_URL", "GITHUB_TOKEN", "GH_TOKEN",
            "GITHUB_STEP_SUMMARY", "GITHUB_OUTPUT",
        ):
            source_env[name] = ""
        try:
            source_process = popen(
                [sys.executable, "-m", "src.market_source_watch", "--scheduled-for", scheduled_for,
                 "--final-source-check", "--result-file", str(source_path)],
                env=source_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except OSError:
            source_status = "source_watch_start_failed"

    try:
        for attempt in (1, 2):
            deadline = window.first_attempt_deadline if attempt == 1 else window.overall_deadline
            if attempt == 2:
                deadline = window.overall_deadline
            enter_stage("budget_check")
            remaining = _remaining(deadline, clock)
            if remaining <= 0:
                failure_reason = "prepare_budget_exhausted_reserve_required"
                break

            enter_stage("restore")
            restored = _run_command(
                [sys.executable, "-m", "src.data_release", "--restore", "--branch", data_release_branch,
                 "--include", "site/data"],
                timeout_seconds=_remaining(deadline, clock), env=env, run=run,
            )
            if restored.returncode != 0:
                failure_reason = "data_release_restore_failed"
                break

            enter_stage("base_lookup")
            fetched = _run_command(
                ["git", "fetch", "--no-tags", "origin", f"refs/heads/{data_release_branch}:refs/remotes/origin/{data_release_branch}"],
                timeout_seconds=_remaining(deadline, clock), env=env, run=run,
            )
            if fetched.returncode != 0:
                failure_reason = "data_release_base_lookup_failed"
                break
            resolved = _run_command(
                ["git", "rev-parse", f"refs/remotes/origin/{data_release_branch}"],
                timeout_seconds=_remaining(deadline, clock), env=env, run=run,
            )
            base_sha = _resolved_commit(resolved)
            if resolved.returncode != 0:
                failure_reason = "data_release_base_lookup_failed"
                break
            if not base_sha:
                failure_reason = "data_release_base_lookup_output_invalid"
                break

            enter_stage("prepare")
            output_file = tempfile.NamedTemporaryFile(prefix="prstk-prepare-output-", delete=False)
            output_file.close()
            output_path = Path(output_file.name)
            temp_paths.append(output_path)
            child_env = dict(env)
            child_env["GITHUB_OUTPUT"] = str(output_path)
            command = [
                sys.executable, "-m", "src.scheduled_delivery", "--slot", slot, "--prepare-only",
                "--slot-context", slot_context, "--notification-requested", notification_requested,
                "--snapshot", snapshot_path,
            ]
            if attempt == 2 and source_rebuild_count and override_path is not None:
                command.extend(["--official-close-overrides", str(override_path)])
            try:
                prepared = _run_command(
                    command, timeout_seconds=_remaining(deadline, clock), env=child_env, run=run,
                )
            except subprocess.TimeoutExpired:
                failure_reason = "prepare_timeout_budget_exhausted"
                break
            latest_values = _read_key_values(output_path)
            if prepared.returncode != 0 or latest_values.get("prepared") != "true":
                failure_reason = latest_values.get("reason") or "scheduled_delivery_prepare_contract_failed"
                break
            if not latest_values.get("snapshot_id"):
                failure_reason = "prepared_snapshot_identity_missing"
                break

            if attempt == 1 and source_process is not None:
                enter_stage("final_source_check")
                # Keep the final watcher alive through its fixed anchor +20m
                # request-start cutoff, even when the first preparation ends
                # early. Its bounded source requests may finish up to 45s
                # later, subject to the shared preparation window.
                until_source_cutoff = max(0, window.source_check_deadline - clock())
                source_wait = min(
                    until_source_cutoff + 45,
                    _remaining(window.overall_deadline, clock),
                )
                try:
                    source_process.wait(timeout=source_wait)
                except subprocess.TimeoutExpired:
                    source_status = "source_watch_deadline_exceeded"
                    source_process.terminate()
                    source_process.wait(timeout=2)
                else:
                    if source_path and source_path.is_file():
                        try:
                            source_result = json.loads(source_path.read_text(encoding="utf-8"))
                            source_status = str(source_result.get("status") or "unknown")
                            probe = source_result.get("last_probe")
                            if isinstance(probe, dict):
                                override_file = tempfile.NamedTemporaryFile(
                                    prefix="prstk-official-close-overrides-", suffix=".json", delete=False,
                                )
                                override_file.write(json.dumps({
                                    "cash_quote": probe.get("cash_quote"),
                                    "futures_quote": probe.get("futures_quote"),
                                }, ensure_ascii=False).encode("utf-8"))
                                override_file.close()
                                override_path = Path(override_file.name)
                                temp_paths.append(override_path)
                        except (OSError, ValueError):
                            source_status = "source_watch_result_invalid"
                    else:
                        source_status = "source_watch_result_missing"

            source_changed = False
            if attempt == 1 and source_result is not None and source_path is not None:
                source_changed = watch_quotes_supersede_snapshot(source_result, snapshot_path)

            enter_stage("base_revalidation")
            if _remaining(window.overall_deadline, clock) <= 0:
                failure_reason = "prepare_budget_exhausted_reserve_required"
                break
            fetched = _run_command(
                ["git", "fetch", "--no-tags", "origin", f"refs/heads/{data_release_branch}:refs/remotes/origin/{data_release_branch}"],
                timeout_seconds=_remaining(window.overall_deadline, clock), env=env, run=run,
            )
            resolved = _run_command(
                ["git", "rev-parse", f"refs/remotes/origin/{data_release_branch}"],
                timeout_seconds=_remaining(window.overall_deadline, clock), env=env, run=run,
            )
            current_sha = _resolved_commit(resolved)
            if fetched.returncode != 0 or resolved.returncode != 0:
                failure_reason = "data_release_base_lookup_failed"
                break
            if not current_sha:
                failure_reason = "data_release_base_lookup_output_invalid"
                break

            base_changed = current_sha != base_sha
            if source_changed or base_changed:
                if attempt == 1 and _remaining(window.overall_deadline, clock) > 0:
                    rebuild_reason = "source_update_and_base_update" if source_changed and base_changed else (
                        "verified_source_update" if source_changed else "release_base_update"
                    )
                    source_rebuild_count = int(source_changed)
                    continue
                failure_reason = "prepared_base_changed_twice_during_prepare" if base_changed else "prepared_source_superseded_after_rebuild"
                break

            enter_stage("complete")
            close_stage()
            latest_values.update({
                "prepared": "true", "data_release_sha": base_sha,
                "data_release_base_sha": base_sha, "data_release_current_sha": current_sha,
                "base_current": "true", "preparation_stage": "complete",
                "preparation_attempts": str(attempt), "rebuild_attempts": str(attempt - 1),
                "source_rebuild_attempts": str(source_rebuild_count),
            })
            latest_values.pop("reason", None)
            latest_values.pop("prepare_failure_reason", None)
            _append_output(env.get("GITHUB_OUTPUT", ""), latest_values)
            result = {
                **result_context(),
                "schema_version": SCHEMA_VERSION, "status": "ready", "reason": "prepared_release_current",
                "slot": slot, "attempts": attempt, "rebuild_reason": rebuild_reason,
                "base_sha": base_sha, "snapshot_id": latest_values["snapshot_id"],
                "source_check_status": source_status, "source_check_changed_candidate": source_changed,
                "source_check_evidence_sha256": hashlib.sha256(
                    json.dumps(source_result, sort_keys=True, ensure_ascii=False).encode("utf-8")
                ).hexdigest() if source_result else "",
                "remaining_seconds": _remaining(window.overall_deadline, clock),
            }
            _append_summary(env.get("GITHUB_STEP_SUMMARY", ""), result, source_result)
            _persist_result(env.get("PREPARATION_RESULT_PATH", ""), result)
            return result, 0

        if not failure_reason:
            failure_reason = "scheduled_prepare_state_machine_exhausted"
        close_stage()
        failed_values = {
            **latest_values,
            "prepared": "false", "reason": failure_reason,
            "prepare_failure_reason": failure_reason, "preparation_stage": stage,
            "preparation_attempts": str(attempt), "data_release_base_sha": base_sha or "unknown",
            "data_release_current_sha": current_sha or "unknown", "base_current": "false",
            "notification_expected": latest_values.get("notification_expected", "true"),
        }
        _append_output(env.get("GITHUB_OUTPUT", ""), failed_values)
        print(f"::error::scheduled_prepare_failed:{failure_reason}")
        result = {
            **result_context(),
            "schema_version": SCHEMA_VERSION, "status": "failed", "reason": failure_reason,
            "stage": stage, "attempts": attempt, "base_sha": base_sha or "unknown",
            "current_sha": current_sha or "unknown", "source_check_status": source_status,
            "remaining_seconds": _remaining(window.overall_deadline, clock),
        }
        _append_summary(env.get("GITHUB_STEP_SUMMARY", ""), result, source_result)
        _persist_result(env.get("PREPARATION_RESULT_PATH", ""), result)
        return result, 1
    except subprocess.TimeoutExpired as exc:
        failure_reason = "prepare_timeout_budget_exhausted" if stage == "prepare" else f"{stage}_timeout"
        close_stage()
        failed_values = {
            **latest_values, "prepared": "false", "reason": failure_reason,
            "prepare_failure_reason": failure_reason, "preparation_stage": stage,
            "preparation_attempts": str(attempt), "data_release_base_sha": base_sha or "unknown",
            "data_release_current_sha": current_sha or "unknown", "base_current": "false",
        }
        _append_output(env.get("GITHUB_OUTPUT", ""), failed_values)
        print(f"::error::scheduled_prepare_failed:{failure_reason} ({type(exc).__name__})")
        result = {
            **result_context(), "schema_version": SCHEMA_VERSION, "status": "failed",
            "reason": failure_reason, "stage": stage,
        }
        _append_summary(env.get("GITHUB_STEP_SUMMARY", ""), result, source_result)
        _persist_result(env.get("PREPARATION_RESULT_PATH", ""), result)
        return result, 1
    finally:
        if source_process is not None and source_process.poll() is None:
            source_process.terminate()
            try:
                source_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                source_process.kill()
                source_process.wait(timeout=2)
        for path in temp_paths:
            path.unlink(missing_ok=True)


def main() -> int:
    required = ("SLOT", "SCHEDULED_FOR_AT", "SLOT_CONTEXT", "SNAPSHOT_PATH", "DATA_RELEASE_BRANCH")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        result = {
            "schema_version": SCHEMA_VERSION, "status": "failed",
            "reason": f"scheduled_prepare_invalid_context_{'_'.join(missing)}", "stage": "context",
        }
        _persist_result(os.environ.get("PREPARATION_RESULT_PATH", ""), result)
        print(f"::error::{result['reason']}")
        return 1
    _, status = coordinate_preparation(
        slot=os.environ["SLOT"], scheduled_for=os.environ["SCHEDULED_FOR_AT"],
        slot_context=os.environ["SLOT_CONTEXT"],
        notification_requested="true" if os.environ.get("NOTIFY") == "true" else "false",
        snapshot_path=os.environ["SNAPSHOT_PATH"], data_release_branch=os.environ["DATA_RELEASE_BRANCH"],
        initial_source_status=os.environ.get("OFFICIAL_CLOSE_WATCH_STATUS", "unknown"),
    )
    return status


if __name__ == "__main__":
    raise SystemExit(main())
