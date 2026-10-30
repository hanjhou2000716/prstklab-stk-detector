"""Single serialized notification outlet for central incident reminders."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import time
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from scripts.incident_reconciliation import (
    RESEARCH_TITLE_PREFIX,
    STATE_ARTIFACT_MEMBER,
    _download_artifact_json,
    _safe_int,
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
from src.github_issue_api import IssuePaginationError, read_open_issues

OUTLET_SCHEMA = "incident-notification-outlet-v1"
JOURNAL_SCHEMA = "incident-notification-journal-v1"
OUTLET_WORKFLOW_PATH = ".github/workflows/incident-notification-outlet.yml"
ALERT_STEP_NAME = "Send one consolidated native incident alert"
CONTROL_ISSUE_TITLE = "PRStK incident notification control"
CONTROL_MARKER = "incident-notification-control=incident-notification-journal-v1"
JOURNAL_OPEN = "<!-- prstk-incident-notification-journal-v1 -->"
JOURNAL_CLOSE = "<!-- /prstk-incident-notification-journal-v1 -->"
DECISION_ARTIFACT_MEMBER = "incident-notification-outlet.json"
MAX_JOURNAL_DECISIONS = 96
MAX_IMMEDIATE_FINGERPRINTS = 128
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
    # Every ordinary reminder is aligned to the fixed half-hour windows.
    # An immediate critical alert is a one-off escalation; its next ordinary
    # reminder still returns to the shared :00/:30 cadence.
    boundary = current.replace(minute=0 if current.minute < 30 else 30, second=0, microsecond=0)
    return (boundary + REMINDER_INTERVAL).isoformat()


def _repo_id_from_env() -> int | None:
    raw = str(os.environ.get("GITHUB_REPOSITORY_ID") or "").strip()
    return _safe_int(raw)


def _default_journal(repository: str) -> dict[str, Any]:
    return {
        "schema_version": JOURNAL_SCHEMA,
        "repository": repository,
        "generation": 0,
        "updated_at": "",
        "last_confirmed_window_key": "",
        "last_confirmed_window_decision_id": "",
        "pending_decision": None,
        "recent_decisions": [],
        "immediate_fingerprints": [],
    }


def _journal_body(journal: dict[str, Any]) -> str:
    payload = json.dumps(journal, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    body = "\n".join((
        CONTROL_MARKER,
        JOURNAL_OPEN,
        payload,
        JOURNAL_CLOSE,
        "This issue is the serialized, machine-readable notification decision journal. Do not close or edit its identity marker.",
    ))
    if len(body.encode("utf-8")) > 50_000:
        raise LivenessAuditError("incident_notification_journal_size_limit_exceeded")
    return body


def _parse_journal_body(body: object, *, repository: str) -> dict[str, Any]:
    text = str(body or "")
    if len(text.encode("utf-8")) > 50_000:
        raise LivenessAuditError("incident_notification_journal_size_limit_exceeded")
    if text.splitlines().count(CONTROL_MARKER) != 1:
        raise LivenessAuditError("incident_notification_control_marker_invalid")
    if text.splitlines().count(JOURNAL_OPEN) != 1 or text.splitlines().count(JOURNAL_CLOSE) != 1:
        raise LivenessAuditError("incident_notification_journal_envelope_invalid")
    try:
        payload = text.split(JOURNAL_OPEN, 1)[1].split(JOURNAL_CLOSE, 1)[0].strip()
        journal = json.loads(payload)
    except (IndexError, json.JSONDecodeError) as exc:
        raise LivenessAuditError("incident_notification_journal_json_invalid") from exc
    if (
        not isinstance(journal, dict)
        or journal.get("schema_version") != JOURNAL_SCHEMA
        or str(journal.get("repository") or "").casefold() != repository.casefold()
        or not isinstance(journal.get("generation"), int)
        or journal.get("generation", -1) < 0
        or not isinstance(journal.get("recent_decisions"), list)
        or not isinstance(journal.get("immediate_fingerprints"), list)
    ):
        raise LivenessAuditError("incident_notification_journal_contract_invalid")
    pending = journal.get("pending_decision")
    if pending is not None and (
        not isinstance(pending, dict)
        or not re.fullmatch(r"[0-9a-f]{64}", str(pending.get("decision_id") or ""))
        or _safe_int(pending.get("outlet_run_id")) is None
        or _safe_int(pending.get("outlet_attempt")) is None
        or not re.fullmatch(r"[0-9a-f]{40}", str(pending.get("outlet_sha") or "").lower())
        or not isinstance(pending.get("consumers"), list)
    ):
        raise LivenessAuditError("incident_notification_pending_decision_invalid")
    return journal


def _read_journal_issues(
    *, repository: str, api_url: str, token: str, deadline: float,
) -> list[dict[str, Any]]:
    try:
        return read_open_issues(
            api_url=api_url,
            repository=repository,
            token=token,
            fetch_json=_request_json,
            deadline_monotonic=deadline,
            repository_id=_repo_id_from_env(),
            state="all",
        )
    except IssuePaginationError as exc:
        raise LivenessAuditError(f"incident_notification_issue_pagination_{exc}") from exc


def _load_control_journal(
    *, repository: str, api_url: str, token: str, deadline: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    issues = _read_journal_issues(
        repository=repository, api_url=api_url, token=token, deadline=deadline,
    )
    matches = [
        row for row in issues
        if CONTROL_MARKER in str(row.get("body") or "").splitlines()
        or str(row.get("title") or "") == CONTROL_ISSUE_TITLE
    ]
    if len(matches) > 1:
        raise LivenessAuditError("incident_notification_control_identity_ambiguous")
    if matches:
        issue = matches[0]
        if (
            _safe_int(issue.get("number")) is None
            or str(issue.get("title") or "") != CONTROL_ISSUE_TITLE
            or str(issue.get("state") or "").casefold() != "open"
        ):
            raise LivenessAuditError("incident_notification_control_identity_invalid")
        return issue, _parse_journal_body(issue.get("body"), repository=repository)

    journal = _default_journal(repository)
    body = _journal_body(journal)
    try:
        created = _request_json(
            api_url, repository, token, "POST", "issues",
            {"title": CONTROL_ISSUE_TITLE, "body": body}, deadline_monotonic=deadline,
        )
    except LivenessAuditError:
        # A timed-out create may have succeeded; re-read by exact marker before
        # deciding that the checkpoint itself is unavailable.
        created = None
    if isinstance(created, dict) and _safe_int(created.get("number")) is not None:
        issue_number = _safe_int(created.get("number"))
        issue = _request_json(
            api_url, repository, token, "GET", f"issues/{issue_number}",
            deadline_monotonic=deadline,
        )
        if (
            not isinstance(issue, dict)
            or _safe_int(issue.get("number")) != issue_number
            or str(issue.get("title") or "") != CONTROL_ISSUE_TITLE
            or str(issue.get("state") or "").casefold() != "open"
        ):
            raise LivenessAuditError("incident_notification_control_create_readback_invalid")
        journal = _parse_journal_body(issue.get("body"), repository=repository)
    else:
        refreshed = _read_journal_issues(
            repository=repository, api_url=api_url, token=token, deadline=deadline,
        )
        found = [row for row in refreshed if CONTROL_MARKER in str(row.get("body") or "").splitlines()]
        if len(found) != 1:
            raise LivenessAuditError("incident_notification_control_create_unconfirmed")
        issue = found[0]
        journal = _parse_journal_body(issue.get("body"), repository=repository)
    if str(issue.get("title") or "") != CONTROL_ISSUE_TITLE:
        raise LivenessAuditError("incident_notification_control_identity_invalid")
    return issue, journal


def _save_control_journal(
    *, issue_number: int, journal: dict[str, Any], expected_generation: int,
    expected_journal: dict[str, Any],
    repository: str, api_url: str, token: str, deadline: float, now: datetime,
) -> dict[str, Any]:
    current_issue = _request_json(
        api_url, repository, token, "GET", f"issues/{issue_number}", deadline_monotonic=deadline,
    )
    if (
        not isinstance(current_issue, dict)
        or _safe_int(current_issue.get("number")) != issue_number
        or str(current_issue.get("title") or "") != CONTROL_ISSUE_TITLE
        or str(current_issue.get("state") or "").casefold() != "open"
    ):
        raise LivenessAuditError("incident_notification_control_identity_invalid")
    current = _parse_journal_body(current_issue.get("body"), repository=repository)
    if current.get("generation") != expected_generation or current != expected_journal:
        raise LivenessAuditError("incident_notification_journal_write_conflict")
    value = dict(journal)
    value["generation"] = expected_generation + 1
    value["updated_at"] = now.astimezone(UTC).isoformat()
    value["recent_decisions"] = value.get("recent_decisions", [])[-MAX_JOURNAL_DECISIONS:]
    value["immediate_fingerprints"] = value.get("immediate_fingerprints", [])[-MAX_IMMEDIATE_FINGERPRINTS:]
    _request_json(
        api_url, repository, token, "PATCH", f"issues/{issue_number}",
        {"body": _journal_body(value)}, deadline_monotonic=deadline,
    )
    verified_issue = _request_json(
        api_url, repository, token, "GET", f"issues/{issue_number}", deadline_monotonic=deadline,
    )
    verified = _parse_journal_body(verified_issue.get("body"), repository=repository) if isinstance(verified_issue, dict) else {}
    if (
        not isinstance(verified_issue, dict)
        or _safe_int(verified_issue.get("number")) != issue_number
        or str(verified_issue.get("state") or "").casefold() != "open"
        or verified.get("generation") != expected_generation + 1
        or verified != value
    ):
        raise LivenessAuditError("incident_notification_journal_readback_mismatch")
    return value


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


def _verify_pending_alert_terminal(
    pending: dict[str, Any], *, repository: str, api_url: str, token: str,
    deadline: float,
) -> str:
    """Return confirmed/not_emitted only from the exact completed Actions attempt."""
    run_id = _safe_int(pending.get("outlet_run_id"))
    attempt = _safe_int(pending.get("outlet_attempt"))
    sha = str(pending.get("outlet_sha") or "").lower()
    if run_id is None or attempt is None or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise LivenessAuditError("incident_notification_pending_identity_invalid")
    run = _request_json(
        api_url, repository, token, "GET", f"actions/runs/{run_id}/attempts/{attempt}",
        deadline_monotonic=deadline,
    )
    head_repository = run.get("head_repository") if isinstance(run, dict) else None
    if (
        not isinstance(run, dict)
        or _safe_int(run.get("id")) != run_id
        or _safe_int(run.get("run_attempt")) != attempt
        or str(run.get("status") or "").casefold() != "completed"
        or str(run.get("path") or "") != OUTLET_WORKFLOW_PATH
        or str(run.get("head_branch") or "") != "main"
        or str(run.get("head_sha") or "").lower() != sha
        or not isinstance(head_repository, dict)
        or str(head_repository.get("full_name") or "").casefold() != repository.casefold()
    ):
        raise LivenessAuditError("incident_notification_alert_terminal_unknown")
    jobs = _request_json(
        api_url, repository, token, "GET",
        f"actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100&page=1",
        deadline_monotonic=deadline,
    )
    rows = jobs.get("jobs") if isinstance(jobs, dict) else None
    if not isinstance(rows, list) or len(rows) >= 100:
        raise LivenessAuditError("incident_notification_alert_jobs_incomplete")
    matches: list[dict[str, Any]] = []
    for job in rows:
        if not isinstance(job, dict):
            continue
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if isinstance(step, dict) and step.get("name") == ALERT_STEP_NAME:
                matches.append({"job": job, "step": step})
    if len(matches) != 1:
        raise LivenessAuditError("incident_notification_alert_step_identity_invalid")
    job = matches[0]["job"]
    step = matches[0]["step"]
    if (
        _safe_int(job.get("run_id")) != run_id
        or _safe_int(job.get("run_attempt")) != attempt
        or str(job.get("status") or "").casefold() != "completed"
        or str(step.get("status") or "").casefold() != "completed"
        or _parse_time(step.get("completed_at")) is None
    ):
        raise LivenessAuditError("incident_notification_alert_terminal_unknown")
    artifact_run = dict(run)
    artifact_run["run_attempt"] = attempt
    raw = _download_artifact_json(
        run=artifact_run,
        expected_artifact_name=f"incident-notification-outlet-decision-{run_id}-attempt-{attempt}",
        expected_member=DECISION_ARTIFACT_MEMBER,
        repository=repository, api_url=api_url, token=token, deadline=deadline,
    )
    try:
        decision = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise LivenessAuditError("incident_notification_decision_artifact_invalid") from exc
    if (
        not isinstance(decision, dict)
        or decision.get("schema_version") != OUTLET_SCHEMA
        or decision.get("notification_due") is not True
        or decision.get("decision_id") != pending.get("decision_id")
        or str(decision.get("outlet_run_id") or "") != str(run_id)
        or _safe_int(decision.get("outlet_attempt")) != attempt
        or str(decision.get("outlet_sha") or "").lower() != sha
        or decision.get("window_key") != pending.get("window_key")
        or decision.get("incident_fingerprint") != pending.get("incident_fingerprint")
    ):
        raise LivenessAuditError("incident_notification_decision_artifact_identity_invalid")
    conclusion = str(step.get("conclusion") or "").casefold()
    if conclusion == "failure":
        return "confirmed"
    if conclusion == "skipped":
        return "not_emitted"
    raise LivenessAuditError("incident_notification_alert_step_conclusion_unknown")


def _sync_incident_after_confirmed_alert(
    row: dict[str, Any], *, window_key: str, incident_fingerprint: str,
    repository: str, api_url: str, token: str, deadline: float, now: datetime,
) -> None:
    number = _safe_int(row.get("issue_number"))
    marker = str(row.get("marker") or "")
    if number is None or not re.fullmatch(r"[a-z][a-z0-9-]*=[0-9a-f]{24,64}", marker):
        raise LivenessAuditError("incident_notification_journal_incident_identity_invalid")
    issue = _request_json(api_url, repository, token, "GET", f"issues/{number}", deadline_monotonic=deadline)
    if not isinstance(issue, dict) or _safe_int(issue.get("number")) != number:
        raise LivenessAuditError("incident_outlet_issue_identity_invalid")
    body = str(issue.get("body") or "")
    if body.splitlines().count(marker) != 1:
        raise LivenessAuditError("incident_outlet_issue_marker_mismatch")
    lines = [line for line in body.splitlines() if not line.startswith((
        "Last outlet window:", "Last reminder at:", "Next reminder at:",
        "Last immediate alert fingerprint:",
    ))]
    title = str(issue.get("title") or "")
    root = _field(body, "Root cause")
    historical_miss = title.startswith(SCHEDULED_ISSUE_TITLE_PREFIX) and root == "scheduled_anchor_claim_missing"
    if historical_miss:
        lines = [line for line in lines if not line.startswith((
            "Alert pending consumer:", "Alert pending since:",
        ))]
        lines.append("Lifecycle: historical_diagnosed")
        lines.append("Reminder policy: stopped after confirmed historical missed-slot alert")
    else:
        consumer = f"{row.get('consumer_run_id')}/{row.get('consumer_attempt')}"
        lines = [line for line in lines if not (
            line.startswith("Alert pending consumer:") and line.partition(":")[2].strip() == consumer
        )]
        if not any(line.startswith("Alert pending consumer:") for line in lines):
            lines = [line for line in lines if not line.startswith("Alert pending since:")]
        next_due = _parse_time(row.get("next_reminder_at"))
        if next_due is None or next_due <= now:
            next_due = _parse_time(_next_reminder_at(now, immediate=row.get("reminder_mode") == "immediate"))
        if next_due is None:
            raise LivenessAuditError("incident_notification_next_reminder_invalid")
        lines.extend((
            f"Last reminder at: {now.astimezone(UTC).isoformat()}",
            f"Next reminder at: {next_due.isoformat()}",
        ))
        if row.get("critical") is True and re.fullmatch(r"[0-9a-f]{64}", str(row.get("critical_fingerprint") or "")):
            lines.append(f"Last immediate alert fingerprint: {row['critical_fingerprint']}")
    lines.append(f"Last outlet window: {window_key} / {incident_fingerprint}")
    _request_json(
        api_url, repository, token, "PATCH", f"issues/{number}",
        {"body": "\n".join(lines)[:12000]}, deadline_monotonic=deadline,
    )
    checked = _request_json(api_url, repository, token, "GET", f"issues/{number}", deadline_monotonic=deadline)
    if not isinstance(checked, dict) or _safe_int(checked.get("number")) != number:
        raise LivenessAuditError("incident_outlet_issue_readback_invalid")
    checked_body = str(checked.get("body") or "")
    if checked_body.splitlines().count(marker) != 1 or f"Last outlet window: {window_key} / {incident_fingerprint}" not in checked_body.splitlines():
        raise LivenessAuditError("incident_outlet_issue_readback_mismatch")


def _resolve_pending_decision(
    *, control_issue: dict[str, Any], journal: dict[str, Any], repository: str,
    api_url: str, token: str, deadline: float, now: datetime,
) -> dict[str, Any]:
    pending = journal.get("pending_decision")
    if not isinstance(pending, dict):
        return journal
    expected_journal = deepcopy(journal)
    terminal = _verify_pending_alert_terminal(
        pending, repository=repository, api_url=api_url, token=token, deadline=deadline,
    )
    if terminal == "confirmed":
        consumers = pending.get("consumers")
        if not isinstance(consumers, list) or not consumers:
            raise LivenessAuditError("incident_notification_pending_consumers_invalid")
        for consumer in consumers:
            if not isinstance(consumer, dict) or not isinstance(consumer.get("confirmations"), list):
                raise LivenessAuditError("incident_notification_pending_consumer_invalid")
            for row in consumer["confirmations"]:
                if not isinstance(row, dict):
                    raise LivenessAuditError("incident_notification_pending_confirmation_invalid")
                _sync_incident_after_confirmed_alert(
                    {
                        **row,
                        "consumer_run_id": consumer.get("run_id"),
                        "consumer_attempt": consumer.get("attempt"),
                    },
                    window_key=str(pending.get("window_key") or ""),
                    incident_fingerprint=str(pending.get("incident_fingerprint") or ""),
                    repository=repository, api_url=api_url, token=token,
                    deadline=deadline, now=now,
                )
        decision_status = "confirmed"
        if pending.get("notification_mode") == "half_hour_digest":
            journal["last_confirmed_window_key"] = str(pending.get("window_key") or "")
            journal["last_confirmed_window_decision_id"] = str(pending.get("decision_id") or "")
        fingerprints = [
            str(row.get("critical_fingerprint") or "")
            for consumer in consumers if isinstance(consumer, dict)
            for row in consumer.get("confirmations", []) if isinstance(row, dict)
            if row.get("critical") is True and re.fullmatch(r"[0-9a-f]{64}", str(row.get("critical_fingerprint") or ""))
        ]
        journal["immediate_fingerprints"] = list(dict.fromkeys([
            *journal.get("immediate_fingerprints", []), *fingerprints,
        ]))[-MAX_IMMEDIATE_FINGERPRINTS:]
    else:
        decision_status = "not_emitted"
    journal["recent_decisions"] = [
        *journal.get("recent_decisions", []),
        {
            "decision_id": pending["decision_id"],
            "window_key": pending.get("window_key", ""),
            "notification_mode": pending.get("notification_mode", ""),
            "status": decision_status,
            "outlet_run_id": pending["outlet_run_id"],
            "outlet_attempt": pending["outlet_attempt"],
            "confirmed_at": now.astimezone(UTC).isoformat() if terminal == "confirmed" else "",
        },
    ][-MAX_JOURNAL_DECISIONS:]
    expected_generation = int(journal.get("generation", 0))
    journal["pending_decision"] = None
    return _save_control_journal(
        issue_number=int(control_issue["number"]), journal=journal,
        expected_generation=expected_generation, expected_journal=expected_journal,
        repository=repository,
        api_url=api_url, token=token, deadline=deadline, now=now,
    )


def prepare_outlet(
    *, repository: str, api_url: str, token: str, now: datetime | None = None,
    deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or not token:
        raise LivenessAuditError("incident_outlet_configuration_invalid")
    current = (now or datetime.now(UTC)).astimezone(UTC)
    deadline = deadline_monotonic or time.monotonic() + 90
    issues = _open_incidents(api_url, repository, token, deadline_monotonic=deadline)
    control_issue, journal = _load_control_journal(
        repository=repository, api_url=api_url, token=token, deadline=deadline,
    )
    journal = _resolve_pending_decision(
        control_issue=control_issue, journal=journal, repository=repository,
        api_url=api_url, token=token, deadline=deadline, now=current,
    )
    current_window = _window_key(current)
    window_already_confirmed = journal.get("last_confirmed_window_key") == current_window
    immediate_fingerprints = {
        str(value) for value in journal.get("immediate_fingerprints", [])
        if re.fullmatch(r"[0-9a-f]{64}", str(value))
    }
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
        already_immediate = (
            _field(body, "Last immediate alert fingerprint") == fingerprint
            or fingerprint in immediate_fingerprints
        )
        due = next_due is None or current >= next_due
        if critical and not already_immediate:
            selected = True
            reason = "critical_new_or_escalated_incident"
        elif due and _ordinary_window_open(current) and not window_already_confirmed:
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
    result = {
        "schema_version": OUTLET_SCHEMA,
        "status": "alert_pending" if due else "no_notification_due",
        "notification_due": due,
        "notification_mode": "immediate_critical" if immediate else "half_hour_digest" if due else "none",
        "window_key": current_window,
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
        "control_issue_number": _safe_int(control_issue.get("number")),
        "decision_id": "",
        "journal_generation": journal.get("generation", 0),
    }
    if not due:
        if window_already_confirmed and _ordinary_window_open(current):
            result["suppression_reason"] = "ordinary_window_already_confirmed"
        return result

    outlet_run_id = _safe_int(os.environ.get("GITHUB_RUN_ID"))
    outlet_attempt = _safe_int(os.environ.get("GITHUB_RUN_ATTEMPT"))
    outlet_sha = str(os.environ.get("GITHUB_SHA") or "").lower()
    if outlet_run_id is None or outlet_attempt is None or not re.fullmatch(r"[0-9a-f]{40}", outlet_sha):
        raise LivenessAuditError("incident_notification_outlet_run_identity_invalid")
    mode = str(result["notification_mode"])
    critical_generation = sorted(
        str(row.get("critical_fingerprint") or "")
        for consumer in verified_consumers
        for row in consumer.get("confirmations", [])
        if isinstance(row, dict) and row.get("critical") is True
    )
    decision_id = hashlib.sha256(json.dumps({
        "schema": JOURNAL_SCHEMA,
        "mode": mode,
        "window_key": current_window,
        "incident_fingerprint": result["incident_fingerprint"],
        "critical_generation": critical_generation,
        "outlet_run_id": outlet_run_id,
        "outlet_attempt": outlet_attempt,
        "outlet_sha": outlet_sha,
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    result["decision_id"] = decision_id
    result["outlet_run_id"] = outlet_run_id
    result["outlet_attempt"] = outlet_attempt
    result["outlet_sha"] = outlet_sha
    if journal.get("pending_decision") is not None:
        raise LivenessAuditError("incident_notification_prior_decision_unresolved")
    expected_journal = deepcopy(journal)
    journal["pending_decision"] = {
        "decision_id": decision_id,
        "notification_mode": mode,
        "window_key": current_window,
        "incident_fingerprint": result["incident_fingerprint"],
        "issue_numbers": result["issue_numbers"],
        "outlet_run_id": outlet_run_id,
        "outlet_attempt": outlet_attempt,
        "outlet_sha": outlet_sha,
        "workflow_path": OUTLET_WORKFLOW_PATH,
        "consumers": verified_consumers,
        "status": "pending_terminal_confirmation",
        "created_at": current.isoformat(),
    }
    journal = _save_control_journal(
        issue_number=int(control_issue["number"]), journal=journal,
        expected_generation=int(journal.get("generation", 0)), expected_journal=expected_journal,
        repository=repository,
        api_url=api_url, token=token, deadline=deadline, now=current,
    )
    result["journal_generation"] = journal["generation"]
    result["journal_status"] = "pending_terminal_confirmation"
    return result


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
    if (
        result.get("notification_due") is not True
        or not alert_emitted
        or alert_step_outcome != "failure"
        or not re.fullmatch(r"[0-9a-f]{64}", str(result.get("decision_id") or ""))
        or _safe_int(result.get("outlet_run_id")) is None
        or _safe_int(result.get("outlet_attempt")) is None
        or not re.fullmatch(r"[0-9a-f]{40}", str(result.get("outlet_sha") or "").lower())
        or _safe_int(result.get("control_issue_number")) is None
    ):
        raise LivenessAuditError("incident_outlet_alert_terminal_unconfirmed")
    current = (now or datetime.now(UTC)).astimezone(UTC)
    # This step runs before GitHub marks its containing workflow attempt as
    # completed. Persist that the alert step reported emission, but leave the
    # control journal pending. The next serialized outlet run confirms the
    # exact completed attempt, step conclusion, and immutable decision artifact.
    result["status"] = "alert_reported_pending_terminal_confirmation"
    result["alert_job"] = "reported_failure_pending_workflow_terminal"
    result["alert_step_outcome"] = alert_step_outcome
    result["alert_reported_at"] = current.isoformat()
    result["terminal_confirmation"] = "pending_exact_run_attempt_and_artifact_readback"
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
