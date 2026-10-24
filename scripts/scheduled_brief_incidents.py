"""Reconcile scheduled-report terminal and independent receipt-audit evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from scripts.monitor_liveness import (
    MAX_AUDIT_SECONDS,
    LivenessAuditError,
    _open_incidents,
    _parse_time,
    _request_json,
)

ISSUE_TITLE_PREFIX = "Scheduled market brief delivery degraded"
ISSUE_MARKER = "scheduled-brief-incident="
REMINDER_INTERVAL = timedelta(minutes=30)
ALLOWED_WORKFLOWS = {"Scheduled market brief", "Scheduled brief slot receipt audit"}


def _read_json(directory: Path, filename: str) -> dict[str, Any] | None:
    try:
        value = json.loads((directory / filename).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _same_attempt(value: Any, expected: int) -> bool:
    try:
        return int(value) == expected
    except (TypeError, ValueError):
        return False


def _safe_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _identity_error(event: dict[str, Any], repository: str) -> str:
    if str(event.get("repository") or "") != repository:
        return "trigger_repository_mismatch"
    if str(event.get("workflow_name") or "") not in ALLOWED_WORKFLOWS:
        return "trigger_workflow_not_allowed"
    if str(event.get("head_branch") or "") != "main":
        return "trigger_branch_not_trusted"
    head_repository = str(event.get("head_repository") or "")
    if head_repository != repository:
        return "trigger_head_repository_mismatch"
    if not str(event.get("run_id") or "").isdigit():
        return "trigger_run_id_invalid"
    if not str(event.get("attempt") or "").isdigit():
        return "trigger_attempt_invalid"
    if len(str(event.get("head_sha") or "")) != 40:
        return "trigger_sha_invalid"
    return ""


def _validated_evidence(event: dict[str, Any], directory: Path) -> dict[str, Any]:
    run_id = str(event["run_id"])
    attempt = int(event["attempt"])
    sha = str(event["head_sha"]).lower()
    workflow = str(event["workflow_name"])
    if workflow == "Scheduled market brief":
        candidates = list(directory.rglob("scheduled-terminal-*.json"))
        valid: list[dict[str, Any]] = []
        for path in candidates:
            item = _read_json(path.parent, path.name)
            if (
                isinstance(item, dict)
                and item.get("schema_version") == "notification-terminal-v2"
                and str(item.get("run_id") or "") == run_id
                and _same_attempt(item.get("run_attempt"), attempt)
                and str(item.get("workflow_sha") or "").lower() == sha
            ):
                valid.append(item)
        if len(valid) != 1:
            return {"kind": "report", "valid": False, "reason": "scheduled_terminal_artifact_missing_or_ambiguous"}
        return {"kind": "report", "valid": True, "terminal": valid[0]}

    candidates = list(directory.rglob("scheduled-slot-audit-*.json"))
    valid_audits: list[dict[str, Any]] = []
    for path in candidates:
        item = _read_json(path.parent, path.name)
        if (
            isinstance(item, dict)
            and item.get("schema_version") == "scheduled-slot-audit-result-v1"
            and str(item.get("run_id") or "") == run_id
            and _same_attempt(item.get("attempt"), attempt)
            and str(item.get("workflow_sha") or "").lower() == sha
        ):
            valid_audits.append(item)
    if len(valid_audits) != 1:
        return {"kind": "audit", "valid": False, "reason": "scheduled_audit_artifact_missing_or_ambiguous"}
    audit = valid_audits[0]
    result = audit.get("result")
    if not isinstance(result, dict):
        return {"kind": "audit", "valid": False, "reason": "scheduled_audit_result_contract_invalid"}
    return {"kind": "audit", "valid": True, "audit": audit, "result": result}


def _root_reason(evidence: dict[str, Any]) -> tuple[str, str, str, dict[str, Any]] | None:
    kind = evidence.get("kind")
    if not evidence.get("valid"):
        reason = str(evidence.get("reason") or "evidence_invalid")
        return "scheduled_audit_evidence", reason, "scheduled-slot-audit-result-v1", {}
    if kind == "report":
        terminal = evidence["terminal"]
        status = str(terminal.get("status") or "unknown")
        reason = _release_failure_reason(terminal.get("release_evidence")) or str(terminal.get("reason") or status)
        if terminal.get("expected") is False and terminal.get("failure") is not True:
            return None
        successful = status in {"delivered", "already_delivered", "expected_skip", "not_applicable", "suppressed"}
        if successful and terminal.get("failure") is not True:
            return None
        return "scheduled_market_brief", reason[:180], str(terminal.get("schema_version") or "notification-terminal-v2"), terminal
    audit = evidence["audit"]
    result = evidence["result"]
    status = str(audit.get("report_receipt_status") or result.get("status") or "unknown")
    if status == "delivered" and audit.get("diagnostic_complete") is True:
        return None
    diagnosis = result.get("run_diagnosis") if isinstance(result.get("run_diagnosis"), dict) else {}
    terminal_reason = (
        _release_failure_reason(diagnosis.get("release_evidence"))
        or str(diagnosis.get("terminal_reason") or "").strip()
    )
    reason = terminal_reason or str(audit.get("first_failure_reason") or result.get("reason") or status)
    contract = str(diagnosis.get("terminal_schema_version") or "notification-terminal-v2")
    return "scheduled_market_brief", reason[:180], contract[:64], result


def _anchor_label(record: dict[str, Any]) -> str:
    slot = str(record.get("slot") or "unknown")[:32]
    date = str(record.get("market_date") or record.get("date") or "unknown")[:20]
    anchor = str(record.get("anchor") or "")[:100]
    return f"{slot}:{date}" + (f" ({anchor})" if anchor else "")


def _release_failure_reason(release_evidence: Any) -> str:
    if not isinstance(release_evidence, dict):
        return ""
    for key in ("build", "pre_delivery_gate", "post_delivery_gate"):
        record = release_evidence.get(key)
        if not isinstance(record, dict) or record.get("evidence_status") != "verified":
            continue
        if record.get("status") not in {"failed", "blocked"}:
            continue
        reason = str(record.get("first_failure_reason") or "").replace("\r", " ").replace("\n", " ").strip()
        if reason:
            return reason[:180]
    return ""


def _incident_key(component: str, reason: str, contract: str) -> str:
    normalized = " ".join(reason.casefold().split())[:180]
    material = f"{component}\n{normalized}\n{contract[:64]}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def _marker(body: object) -> str:
    for line in str(body or "").splitlines():
        if line.startswith(ISSUE_MARKER):
            return line[len(ISSUE_MARKER):].strip()
    return ""


def _field(body: object, label: str) -> str:
    prefix = f"{label}:"
    for line in str(body or "").splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return ""


def _pending_alert_consumer() -> str:
    run_id = str(os.environ.get("GITHUB_RUN_ID") or "").strip()
    attempt = str(os.environ.get("GITHUB_RUN_ATTEMPT") or "").strip()
    return f"{run_id}/{attempt}" if run_id and attempt else "local"


def _mark_alert_pending(body: str, consumer: str) -> str:
    lines = [line for line in body.splitlines() if not line.startswith("Alert pending consumer:")]
    lines.append(f"Alert pending consumer: {consumer}")
    return "\n".join(lines)


def _issue_body(
    key: str, *, component: str, reason: str, contract: str, slots: list[str],
    first_failure: str, run_id: str, attempt: int, sha: str, evidence_status: str,
    now: datetime, next_reminder: datetime,
) -> str:
    return "\n".join((
        f"{ISSUE_MARKER}{key}",
        f"Component: {component}",
        f"Root cause: {reason[:180]}",
        f"Contract: {contract[:64]}",
        f"Affected slot count: {len(slots)}",
        f"Affected slots: {', '.join(slots[:100])}",
        f"Affected slots complete: {'true' if len(slots) <= 100 else 'false'}",
        f"First failure: {first_failure}",
        f"Latest evidence: {evidence_status[:160]}",
        f"Latest run: {run_id} attempt {attempt} ({sha})",
        f"Observed at: {now.isoformat()}",
        f"Next reminder at: {next_reminder.isoformat()}",
        "Historical missed slots remain missed; this incident records diagnosis and recovery evidence only.",
    ))


def _slot_is_recovered(issue_body: object, current_slot: str) -> bool:
    slots = _field(issue_body, "Affected slots").split(",")
    return any(item.strip().split(":", 1)[0] == current_slot for item in slots if item.strip())


def _handoff_result(
    *, event: dict[str, Any], result: dict[str, Any] | None,
    failure_reason: str = "",
) -> dict[str, Any]:
    complete = bool(result and result.get("diagnostic_complete") is True and not failure_reason)
    return {
        "schema_version": "scheduled-brief-incident-handoff-v1",
        "consumer_run_id": os.getenv("GITHUB_RUN_ID", "")[:32],
        "consumer_attempt": _safe_int(os.getenv("GITHUB_RUN_ATTEMPT", "")),
        "consumer_sha": os.getenv("GITHUB_SHA", "")[:40],
        "source_workflow": str(event.get("workflow_name") or "")[:80],
        "source_run_id": str(event.get("run_id") or "")[:32],
        "source_attempt": _safe_int(event.get("attempt")),
        "source_sha": str(event.get("head_sha") or "")[:40],
        "diagnostic_complete": complete,
        "incident_active": bool(result and result.get("incident_active")),
        "incident_handoff_status": "accepted" if complete else "failed",
        "failure_reason": failure_reason[:240],
        "opened_issue_numbers": result.get("opened_issue_numbers", []) if result else [],
        "reminded_issue_numbers": result.get("reminded_issue_numbers", []) if result else [],
        "recovered_issue_numbers": result.get("recovered_issue_numbers", []) if result else [],
        "evidence_kind": str(result.get("evidence_kind") or "unknown")[:40] if result else "unknown",
        "evidence_status": str(result.get("evidence_status") or "unknown")[:80] if result else "unknown",
    }


def _write_handoff_result(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def reconcile(
    *, event: dict[str, Any], evidence_directory: Path, repository: str,
    api_url: str, token: str, now: datetime | None = None,
    defer_notification_cadence: bool = False,
) -> dict[str, Any]:
    identity_error = _identity_error(event, repository)
    if identity_error:
        raise LivenessAuditError(identity_error)
    evidence = _validated_evidence(event, evidence_directory)
    current = (now or datetime.now(UTC)).astimezone(UTC)
    deadline = __import__("time").monotonic() + MAX_AUDIT_SECONDS
    issues = [
        item for item in _open_incidents(api_url, repository, token, deadline_monotonic=deadline)
        if str(item.get("title") or "").startswith(ISSUE_TITLE_PREFIX)
    ]
    indexed: dict[str, list[dict[str, Any]]] = {}
    for issue in issues:
        marker = _marker(issue.get("body"))
        if marker:
            indexed.setdefault(marker, []).append(issue)
    if any(len(rows) > 1 for rows in indexed.values()):
        raise LivenessAuditError("scheduled_brief_incident_duplicate_issue")

    component_reason = _root_reason(evidence)
    opened: list[int] = []
    reminded: list[int] = []
    recovered: list[int] = []
    cadence_confirmations: list[dict[str, str | int]] = []
    run_id = str(event["run_id"])
    attempt = int(event["attempt"])
    sha = str(event["head_sha"]).lower()
    if component_reason is not None:
        component, reason, contract, record = component_reason
        if evidence.get("kind") == "audit":
            result = evidence.get("result") or {}
            slot_record = {
                "slot": result.get("slot"),
                "market_date": result.get("market_date"),
                "anchor": result.get("anchor"),
            }
            first = str((evidence.get("audit") or {}).get("audited_at") or current.isoformat())
            evidence_status = str((evidence.get("audit") or {}).get("report_receipt_status") or "unknown")
        else:
            slot_record = record
            first = str(record.get("scheduled_for_at") or current.isoformat())
            evidence_status = str(record.get("status") or "unknown")
        slot_label = _anchor_label(slot_record)
        key = _incident_key(component, reason, contract)
        rows = indexed.get(key, [])
        if not rows:
            body = _issue_body(
                key, component=component, reason=reason, contract=contract,
                slots=[slot_label], first_failure=first, run_id=run_id,
                attempt=attempt, sha=sha, evidence_status=evidence_status,
                now=current,
                next_reminder=current if defer_notification_cadence else current + REMINDER_INTERVAL,
            )
            if defer_notification_cadence:
                body = _mark_alert_pending(body, _pending_alert_consumer())
            created = _request_json(
                api_url, repository, token, "POST", "issues",
                {"title": f"{ISSUE_TITLE_PREFIX} / {component}", "body": body},
                deadline_monotonic=deadline,
            )
            if not isinstance(created, dict) or not isinstance(created.get("number"), int):
                raise LivenessAuditError("scheduled_brief_incident_create_invalid")
            opened.append(created["number"])
            if defer_notification_cadence:
                cadence_confirmations.append({
                    "issue_number": created["number"],
                    "marker": f"{ISSUE_MARKER}{key}",
                    "next_reminder_at": (current + REMINDER_INTERVAL).isoformat(),
                })
        else:
            issue = rows[0]
            number = issue.get("number")
            if not isinstance(number, int):
                raise LivenessAuditError("scheduled_brief_incident_identity_invalid")
            body_before = str(issue.get("body") or "")
            first_existing = _field(body_before, "First failure") or first
            old_slots = [item.strip() for item in _field(body_before, "Affected slots").split(",") if item.strip()]
            slots = list(dict.fromkeys([*old_slots, slot_label]))
            next_due = _parse_time(_field(body_before, "Next reminder at"))
            pending_current = (
                defer_notification_cadence
                and _field(body_before, "Alert pending consumer") == _pending_alert_consumer()
            )
            if next_due is None or current >= next_due:
                due = True
                if defer_notification_cadence:
                    next_reminder = next_due or current
                else:
                    next_reminder = current + REMINDER_INTERVAL
            else:
                due = False
                next_reminder = next_due
            body = _issue_body(
                key, component=component, reason=reason, contract=contract,
                slots=slots, first_failure=first_existing, run_id=run_id,
                attempt=attempt, sha=sha, evidence_status=evidence_status,
                now=current, next_reminder=next_reminder,
            )
            if defer_notification_cadence and due:
                body = _mark_alert_pending(body, _pending_alert_consumer())
            _request_json(api_url, repository, token, "PATCH", f"issues/{number}", {"body": body}, deadline_monotonic=deadline)
            if due and not pending_current:
                _request_json(
                    api_url, repository, token, "POST", f"issues/{number}/comments",
                    {"body": f"Still degraded: {reason}; {len(slots)} affected scheduled slot(s). Latest run {run_id}, attempt {attempt}."},
                    deadline_monotonic=deadline,
                )
                reminded.append(number)
                if defer_notification_cadence:
                    cadence_confirmations.append({
                        "issue_number": number,
                        "marker": f"{ISSUE_MARKER}{key}",
                        "next_reminder_at": (current + REMINDER_INTERVAL).isoformat(),
                    })

    # A later successful, complete independent audit is recovery evidence for
    # this slot family. Close the incident as a service recovery, never as a
    # retroactive delivery of the earlier missed occurrence.
    if evidence.get("kind") == "audit" and evidence.get("valid"):
        audit = evidence["audit"]
        result = evidence["result"]
        if audit.get("diagnostic_complete") is True and audit.get("report_receipt_status") == "delivered":
            current_slot = str((audit.get("original_slot") or {}).get("slot") or result.get("slot") or "")
            for key, rows in indexed.items():
                if key in (indexed if component_reason is not None else {}):
                    continue
                issue = rows[0]
                number = issue.get("number")
                body = str(issue.get("body") or "")
                if not isinstance(number, int) or not _slot_is_recovered(body, current_slot):
                    continue
                _request_json(
                    api_url, repository, token, "POST", f"issues/{number}/comments",
                    {"body": f"Recovery verified by a complete receipt audit at {current.isoformat()}. Historical missed slot(s) remain recorded and were not resent."},
                    deadline_monotonic=deadline,
                )
                _request_json(
                    api_url, repository, token, "PATCH", f"issues/{number}",
                    {"state": "closed", "state_reason": "completed"},
                    deadline_monotonic=deadline,
                )
                recovered.append(number)

    return {
        "schema_version": "scheduled-brief-incident-reconcile-v1",
        "diagnostic_complete": bool(evidence.get("valid")),
        "incident_active": component_reason is not None,
        "opened_issue_numbers": opened,
        "reminded_issue_numbers": reminded,
        "recovered_issue_numbers": recovered,
        "notification_cadence_confirmations": cadence_confirmations,
        "evidence_kind": evidence.get("kind", "unknown"),
        "evidence_status": str((evidence.get("audit") or {}).get("report_receipt_status") or (evidence.get("terminal") or {}).get("status") or evidence.get("reason") or "unknown"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-output", type=Path, default=None)
    args = parser.parse_args()
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    event = {
        "repository": os.environ.get("TRIGGER_REPOSITORY", ""),
        "head_repository": os.environ.get("TRIGGER_HEAD_REPOSITORY", ""),
        "workflow_name": os.environ.get("TRIGGER_WORKFLOW_NAME", ""),
        "head_branch": os.environ.get("TRIGGER_HEAD_BRANCH", ""),
        "run_id": os.environ.get("TRIGGER_RUN_ID", ""),
        "attempt": os.environ.get("TRIGGER_RUN_ATTEMPT", ""),
        "head_sha": os.environ.get("TRIGGER_HEAD_SHA", ""),
    }
    result: dict[str, Any] | None = None
    failure_reason = ""
    try:
        if not token or "/" not in repository:
            raise LivenessAuditError("scheduled_brief_incident_configuration_invalid")
        result = reconcile(
            event=event,
            evidence_directory=Path(os.environ.get("INCIDENT_EVIDENCE_DIR", "incident-evidence")),
            repository=repository,
            api_url=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
            token=token,
        )
    except LivenessAuditError as exc:
        failure_reason = str(exc)
        print(failure_reason, file=sys.stderr)
    payload = _handoff_result(event=event, result=result, failure_reason=failure_reason)
    result_path = args.result_output or (
        Path(os.environ["INCIDENT_HANDOFF_RESULT_PATH"])
        if os.getenv("INCIDENT_HANDOFF_RESULT_PATH") else None
    )
    if result_path is not None:
        try:
            _write_handoff_result(result_path, payload)
        except OSError as exc:
            print(f"scheduled_brief_incident_result_write_failed={type(exc).__name__}", file=sys.stderr)
            return 1
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0 if payload["diagnostic_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
