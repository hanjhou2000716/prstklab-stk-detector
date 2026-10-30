"""Single serialized notification outlet for central incident reminders."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from scripts.incident_reconciliation import (
    RESEARCH_TITLE_PREFIX,
    STATE_ARTIFACT_MEMBER,
    _download_artifact_json,
    _safe_int,
    finalize_alert_cadence,
)
from scripts.incident_reconciliation_health import ISSUE_TITLE_PREFIX as HEALTH_ISSUE_TITLE_PREFIX
from scripts.monitor_liveness import (
    AUDIT_ISSUE_TITLE_PREFIX,
    EVENT_ISSUE_TITLE_PREFIX,
    LivenessAuditError,
    _open_incidents,
    _parse_time,
    _request_json,
)
from scripts.monitor_liveness import ISSUE_TITLE_PREFIX as MONITOR_ISSUE_TITLE_PREFIX
from scripts.scheduled_brief_incidents import ISSUE_TITLE_PREFIX as SCHEDULED_ISSUE_TITLE_PREFIX

OUTLET_SCHEMA = "incident-notification-outlet-v1"
OUTLET_WORKFLOW_PATH = ".github/workflows/incident-notification-outlet.yml"
ALLOWED_SOURCE_PATHS = {
    ".github/workflows/incident-reconciliation.yml",
    ".github/workflows/incident-reconciliation-health.yml",
}
ALLOWED_TITLE_PREFIXES = (
    MONITOR_ISSUE_TITLE_PREFIX,
    AUDIT_ISSUE_TITLE_PREFIX,
    EVENT_ISSUE_TITLE_PREFIX,
    SCHEDULED_ISSUE_TITLE_PREFIX,
    RESEARCH_TITLE_PREFIX,
    HEALTH_ISSUE_TITLE_PREFIX,
)
REMINDER_INTERVAL = timedelta(minutes=30)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(raw, path)
    finally:
        try:
            os.unlink(raw)
        except FileNotFoundError:
            pass


def _field(body: str, name: str) -> str:
    rows = [line.partition(":")[2].strip() for line in body.splitlines() if line.startswith(name + ":")]
    return rows[0] if len(rows) == 1 else ""


def _window_key(now: datetime) -> str:
    current = now.astimezone(UTC)
    minute = 0 if current.minute < 30 else 30
    return current.replace(minute=minute, second=0, microsecond=0).isoformat()


def _ordinary_window_open(now: datetime) -> bool:
    # Allow a five-minute runner-start delay after each half-hour boundary.
    minute = now.astimezone(UTC).minute
    return minute < 5 or 30 <= minute < 35


def _next_reminder_at(now: datetime, *, immediate: bool) -> str:
    current = now.astimezone(UTC)
    if not immediate:
        current = current.replace(minute=0 if current.minute < 30 else 30, second=0, microsecond=0)
    return (current + REMINDER_INTERVAL).isoformat()


def _critical_fingerprint(issue: dict[str, Any]) -> str:
    body = str(issue.get("body") or "")
    marker = next((line for line in body.splitlines() if re.match(r"^[a-z][a-z0-9-]*=[0-9a-f]{24,64}$", line)), "")
    root = _field(body, "Root cause")
    first = _field(body, "First failure")
    return hashlib.sha256(f"{marker}\n{root}\n{first}".encode()).hexdigest()


def _is_critical(issue: dict[str, Any], now: datetime) -> bool:
    body = str(issue.get("body") or "")
    if _field(body, "Lifecycle") in {"historical_diagnosed", "historical_pending_verification"}:
        return False
    root = _field(body, "Root cause").casefold()
    critical_terms = (
        "identity_conflict", "identity_mismatch", "hash_mismatch", "claim_state_conflict",
        "notification_claim_uncertain", "missed_deadline", "delivery_deadline",
        "insufficient_reserve", "scheduled_anchor_claim_missing",
    )
    if not any(term in root for term in critical_terms):
        return False
    observed = _parse_time(_field(body, "Observed at"))
    first = _parse_time(_field(body, "First failure"))
    # An old incident is not a new emergency. Require a recent attached observation.
    anchor = observed or first
    return anchor is not None and timedelta(0) <= now.astimezone(UTC) - anchor <= timedelta(minutes=10)


def _consumer(issue: dict[str, Any]) -> tuple[str, int] | None:
    raw = _field(str(issue.get("body") or ""), "Alert pending consumer")
    match = re.fullmatch(r"([1-9][0-9]{0,19})/([1-9][0-9]{0,5})", raw)
    return (match.group(1), int(match.group(2))) if match else None


def _issue_marker(issue: dict[str, Any]) -> str:
    body = str(issue.get("body") or "")
    rows = [line for line in body.splitlines() if re.fullmatch(r"[a-z][a-z0-9-]*=[0-9a-f]{24,64}", line)]
    return rows[0] if len(rows) == 1 else ""


def _load_verified_consumer(
    *, run_id: str, attempt: int, repository: str, api_url: str, token: str,
    deadline: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    run = _request_json(
        api_url, repository, token, "GET", f"actions/runs/{run_id}",
        deadline_monotonic=deadline,
    )
    if not isinstance(run, dict):
        raise LivenessAuditError("incident_outlet_consumer_run_invalid")
    run_sha = str(run.get("head_sha") or "").lower()
    path = str(run.get("path") or "")
    if (
        _safe_int(run.get("id")) != int(run_id)
        or _safe_int(run.get("run_attempt")) != attempt
        or run.get("status") != "completed"
        or run.get("head_branch") != "main"
        or path not in ALLOWED_SOURCE_PATHS
        or not re.fullmatch(r"[0-9a-f]{40}", run_sha)
        or str((run.get("repository") or {}).get("full_name") or repository).casefold() != repository.casefold()
    ):
        raise LivenessAuditError("incident_outlet_consumer_identity_invalid")
    artifact_name = f"incident-reconciliation-state-{run_id}-attempt-{attempt}"
    raw = _download_artifact_json(
        run=run, expected_artifact_name=artifact_name,
        expected_member=STATE_ARTIFACT_MEMBER, repository=repository,
        api_url=api_url, token=token, deadline=deadline,
    )
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise LivenessAuditError("incident_outlet_consumer_result_invalid") from exc
    if (
        not isinstance(result, dict)
        or result.get("schema_version") != "incident-reconciliation-v1"
        or str(result.get("consumer_run_id") or "") != run_id
        or _safe_int(result.get("consumer_attempt")) != attempt
        or str(result.get("consumer_sha") or "").lower() != run_sha
        or result.get("notification_due") is not True
        or not isinstance(result.get("notification_cadence_confirmations"), list)
    ):
        raise LivenessAuditError("incident_outlet_consumer_result_identity_invalid")
    return run, result


def prepare_outlet(
    *, repository: str, api_url: str, token: str, now: datetime | None = None,
    deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or not token:
        raise LivenessAuditError("incident_outlet_configuration_invalid")
    current = (now or datetime.now(UTC)).astimezone(UTC)
    deadline = deadline_monotonic or time.monotonic() + 90
    issues = _open_incidents(api_url, repository, token, deadline_monotonic=deadline)
    candidates: list[dict[str, Any]] = []
    for issue in issues:
        title = str(issue.get("title") or "")
        if not title.startswith(ALLOWED_TITLE_PREFIXES):
            continue
        body = str(issue.get("body") or "")
        consumer = _consumer(issue)
        marker = _issue_marker(issue)
        if _field(body, "Lifecycle") in {"historical_diagnosed", "historical_pending_verification"}:
            continue
        next_due = _parse_time(_field(body, "Next reminder at"))
        if not consumer or not marker or _safe_int(issue.get("number")) is None:
            continue
        fingerprint = _critical_fingerprint(issue)
        critical = _is_critical(issue, current)
        already_immediate = _field(body, "Last immediate alert fingerprint") == fingerprint
        due = next_due is None or current >= next_due
        if critical and not already_immediate:
            selected = True
            reason = "critical_new_or_escalated_incident"
        elif due and _ordinary_window_open(current):
            selected = True
            reason = "half_hour_reminder_window"
        else:
            selected = False
            reason = "not_due_in_current_window"
        if selected:
            candidates.append({
                "issue_number": int(issue["number"]),
                "marker": marker,
                "consumer_run_id": consumer[0],
                "consumer_attempt": consumer[1],
                "critical": critical,
                "critical_fingerprint": fingerprint if critical else "",
                "reason": reason,
                "reminder_mode": "immediate" if reason == "critical_new_or_escalated_incident" else "window",
                "next_reminder_at": _next_reminder_at(
                    current, immediate=reason == "critical_new_or_escalated_incident",
                ),
            })
    groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in candidates:
        groups.setdefault((row["consumer_run_id"], row["consumer_attempt"]), []).append(row)
    verified_consumers: list[dict[str, Any]] = []
    for (run_id, attempt), selected_rows in sorted(groups.items()):
        run, source_result = _load_verified_consumer(
            run_id=run_id, attempt=attempt, repository=repository, api_url=api_url,
            token=token, deadline=deadline,
        )
        source_confirmations = source_result["notification_cadence_confirmations"]
        matched: list[dict[str, Any]] = []
        for row in selected_rows:
            issue = next((item for item in issues if _safe_int(item.get("number")) == row["issue_number"]), None)
            body = str((issue or {}).get("body") or "")
            if body.splitlines().count(row["marker"]) != 1 or body.splitlines().count(f"Alert pending consumer: {run_id}/{attempt}") != 1:
                raise LivenessAuditError("incident_outlet_issue_reservation_mismatch")
            matches = [
                confirmation for confirmation in source_confirmations
                if isinstance(confirmation, dict)
                and _safe_int(confirmation.get("issue_number")) == row["issue_number"]
                and confirmation.get("marker") == row["marker"]
            ]
            if len(matches) != 1:
                raise LivenessAuditError("incident_outlet_source_confirmation_missing")
            matched.append({
                "issue_number": row["issue_number"],
                "marker": row["marker"],
                "next_reminder_at": row["next_reminder_at"],
                "critical": row["critical"],
                "critical_fingerprint": row["critical_fingerprint"],
                "reminder_mode": row["reminder_mode"],
            })
        verified_consumers.append({
            "run_id": run_id,
            "attempt": attempt,
            "sha": str(run["head_sha"]).lower(),
            "workflow_path": str(run["path"]),
            "confirmations": matched,
        })
    immediate = any(row["reason"] == "critical_new_or_escalated_incident" for row in candidates)
    due = bool(verified_consumers)
    return {
        "schema_version": OUTLET_SCHEMA,
        "status": "alert_pending" if due else "no_notification_due",
        "notification_due": due,
        "notification_mode": "immediate_critical" if immediate else "half_hour_digest" if due else "none",
        "window_key": _window_key(current),
        "candidate_count": len(candidates),
        "issue_numbers": sorted({row["issue_number"] for row in candidates}),
        "incident_fingerprint": hashlib.sha256("\n".join(sorted(f"{row['issue_number']}:{row['marker']}" for row in candidates)).encode()).hexdigest(),
        "consumers": verified_consumers,
        "observed_at": current.isoformat(),
        "outlet_run_id": os.environ.get("GITHUB_RUN_ID", "")[:32],
        "outlet_attempt": _safe_int(os.environ.get("GITHUB_RUN_ATTEMPT")),
        "outlet_sha": os.environ.get("GITHUB_SHA", "")[:40],
        "alert_job": "pending" if due else "not_due",
        "confirmed_at": "",
    }


def finalize_outlet(
    *, result_path: Path, repository: str, api_url: str, token: str,
    alert_emitted: bool, alert_step_outcome: str, now: datetime | None = None,
) -> dict[str, Any]:
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LivenessAuditError("incident_outlet_decision_unavailable") from exc
    if not isinstance(result, dict) or result.get("schema_version") != OUTLET_SCHEMA:
        raise LivenessAuditError("incident_outlet_decision_schema_invalid")
    if result.get("notification_due") is not True or not alert_emitted or alert_step_outcome != "failure":
        raise LivenessAuditError("incident_outlet_alert_terminal_unconfirmed")
    current = (now or datetime.now(UTC)).astimezone(UTC)
    updated: list[int] = []
    for consumer in result.get("consumers", []):
        if not isinstance(consumer, dict):
            raise LivenessAuditError("incident_outlet_consumer_contract_invalid")
        rows = consumer.get("confirmations")
        if not isinstance(rows, list) or not rows:
            raise LivenessAuditError("incident_outlet_confirmation_contract_invalid")
        confirmations = [
            {
                "issue_number": row["issue_number"], "marker": row["marker"],
                "next_reminder_at": _next_reminder_at(
                    current, immediate=row.get("reminder_mode", (
                        "immediate" if row.get("critical") is True and result.get("notification_mode") == "immediate_critical"
                        else "window"
                    )) == "immediate",
                ),
            }
            for row in rows if isinstance(row, dict)
        ]
        miniature = {
            "schema_version": "incident-reconciliation-v1",
            "consumer_run_id": consumer["run_id"],
            "consumer_attempt": consumer["attempt"],
            "consumer_sha": consumer["sha"],
            "notification_due": True,
            "notification_cadence_confirmations": confirmations,
        }
        with tempfile.TemporaryDirectory(prefix="prstk-outlet-") as folder:
            miniature_path = Path(folder) / "source-result.json"
            _atomic_json(miniature_path, miniature)
            finalize_alert_cadence(
                result_path=miniature_path, repository=repository, api_url=api_url,
                token=token, consumer_run_id=str(consumer["run_id"]),
                consumer_attempt=int(consumer["attempt"]), consumer_sha=str(consumer["sha"]),
                alert_emitted=True, alert_step_outcome="failure", now=current,
            )
        for row in rows:
            if not isinstance(row, dict):
                continue
            number = int(row["issue_number"])
            issue = _request_json(api_url, repository, token, "GET", f"issues/{number}", deadline_monotonic=time.monotonic()+20)
            if not isinstance(issue, dict) or _safe_int(issue.get("number")) != number:
                raise LivenessAuditError("incident_outlet_issue_identity_invalid")
            body = str(issue.get("body") or "")
            marker = str(row["marker"])
            if body.splitlines().count(marker) != 1:
                raise LivenessAuditError("incident_outlet_issue_marker_mismatch")
            lines = [line for line in body.splitlines() if not line.startswith(("Last outlet window:", "Last immediate alert fingerprint:"))]
            lines.append(f"Last outlet window: {result['window_key']} / {result['incident_fingerprint']}")
            title = str(issue.get("title") or "")
            root = _field(body, "Root cause")
            historical_miss = title.startswith(SCHEDULED_ISSUE_TITLE_PREFIX) and root == "scheduled_anchor_claim_missing"
            if historical_miss:
                lines = [line for line in lines if not line.startswith(("Next reminder at:", "Alert pending consumer:", "Alert pending since:"))]
                lines.append("Lifecycle: historical_diagnosed")
                lines.append("Reminder policy: stopped after confirmed historical missed-slot alert")
            elif row.get("critical") is True and re.fullmatch(r"[0-9a-f]{64}", str(row.get("critical_fingerprint") or "")):
                lines.append(f"Last immediate alert fingerprint: {row['critical_fingerprint']}")
            _request_json(api_url, repository, token, "PATCH", f"issues/{number}", {"body": "\n".join(lines)[:12000]}, deadline_monotonic=time.monotonic()+20)
            updated.append(number)
    result["status"] = "alert_confirmed"
    result["alert_job"] = "failure_confirmed"
    result["confirmed_at"] = current.isoformat()
    result["updated_issue_numbers"] = sorted(set(updated))
    _atomic_json(result_path, result)
    return result


def main() -> int:
    action = sys.argv[1:] or ["prepare"]
    path = Path(os.environ.get("INCIDENT_OUTLET_RESULT_PATH", "incident-notification-outlet.json"))
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    token = os.environ.get("GITHUB_TOKEN", "")
    try:
        if action == ["prepare"]:
            result = prepare_outlet(repository=repository, api_url=api_url, token=token)
            _atomic_json(path, result)
            output = os.environ.get("GITHUB_OUTPUT", "")
            if output:
                with open(output, "a", encoding="utf-8") as handle:
                    handle.write(f"notification_due={str(result['notification_due']).lower()}\n")
                    handle.write(f"notification_mode={result['notification_mode']}\n")
            print(json.dumps(result, sort_keys=True, separators=(",", ":")))
            return 0
        if action == ["finalize"]:
            result = finalize_outlet(
                result_path=path, repository=repository, api_url=api_url, token=token,
                alert_emitted=os.environ.get("INCIDENT_ALERT_EMITTED", "").casefold() == "true",
                alert_step_outcome=os.environ.get("INCIDENT_ALERT_STEP_OUTCOME", ""),
            )
            print(json.dumps(result, sort_keys=True, separators=(",", ":")))
            return 0
    except (LivenessAuditError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"incident_notification_outlet_failed:{str(exc)[:180]}", file=sys.stderr)
        return 1
    print("incident_notification_outlet_arguments_invalid", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
