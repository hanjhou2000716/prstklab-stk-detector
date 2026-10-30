"""Deduplicate per-event delivery incidents into first/reminder/recovery updates."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from scripts.monitor_liveness import (
    EVENT_INCIDENT_MARKER,
    EVENT_ISSUE_TITLE_PREFIX,
    MAX_AUDIT_SECONDS,
    LivenessAuditError,
    _open_incidents,
    _parse_time,
    _request_json,
)
from src.incident_cadence import can_emit_pending_alert, mark_pending_alert, preserve_pending_alert

REMINDER_INTERVAL = timedelta(minutes=30)
SUMMARY_ESCALATION = timedelta(minutes=10)


def _marker(body: object) -> str:
    for line in str(body or "").splitlines():
        if line.startswith(EVENT_INCIDENT_MARKER):
            return line[len(EVENT_INCIDENT_MARKER):].strip()
    return ""


def _field(body: object, label: str) -> str:
    prefix = f"{label}:"
    for line in str(body or "").splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return ""


def _timestamp(body: object, label: str) -> datetime | None:
    prefix = f"{label}:"
    for line in str(body or "").splitlines():
        if line.startswith(prefix):
            return _parse_time(line[len(prefix):].strip())
    return None


def _pending_alert_consumer() -> str:
    run_id = str(os.environ.get("GITHUB_RUN_ID") or "").strip()
    attempt = str(os.environ.get("GITHUB_RUN_ATTEMPT") or "").strip()
    return f"{run_id}/{attempt}" if run_id and attempt else "local"


def _mark_alert_pending(body: str, consumer: str, now: datetime) -> str:
    return mark_pending_alert(body, consumer, now)


def _issue_event_refs(body: object) -> tuple[list[str], bool]:
    lines = str(body or "").splitlines()
    refs_line = next((line for line in lines if line.startswith("Event refs:")), "")
    placeholders = {"not available", "unknown", "none", "n/a", "na"}
    refs = [
        item.strip()[:64]
        for item in refs_line.partition(":")[2].split(",")
        if item.strip() and item.strip().casefold() not in placeholders
    ]
    expected_count = next((line.partition(":")[2].strip() for line in lines if line.startswith("Affected event count:")), "")
    try:
        count = int(expected_count)
    except (TypeError, ValueError):
        count = -1
    complete_line = next((line for line in lines if line.startswith("Event refs complete:")), "")
    declared_complete = complete_line.partition(":")[2].strip().casefold() == "true" if complete_line else None
    complete = bool(refs) and (
        (declared_complete is True and (count < 0 or len(refs) >= count))
        or (declared_complete is None and count > 0 and len(refs) >= count)
    )
    return list(dict.fromkeys(refs)), complete


def _issue_group_identity(issue: dict[str, Any]) -> tuple[str, str, str, str]:
    body = issue.get("body")
    return (
        _marker(body),
        _field(body, "Component"),
        _field(body, "Root cause"),
        _field(body, "Summary contract"),
    )


def _issue_order(issue: dict[str, Any]) -> tuple[datetime, int]:
    first = _timestamp(issue.get("body"), "First failure") or _parse_time(issue.get("created_at"))
    number = issue.get("number")
    return first or datetime.max.replace(tzinfo=UTC), number if isinstance(number, int) else 2**63 - 1


def _replace_body_field(body: str, label: str, value: str) -> str:
    prefix = f"{label}:"
    lines = body.splitlines()
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = f"{prefix} {value}"
            return "\n".join(lines)
    return "\n".join([*lines, f"{prefix} {value}"])


def _existing_issue_evidence(body: object) -> list[dict[str, Any]]:
    value = _field(body, "Consolidated issue evidence")
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise LivenessAuditError("official_event_incident_consolidated_evidence_invalid") from exc
    if not isinstance(parsed, list) or any(
        not isinstance(row, dict)
        or not isinstance(row.get("issue_number"), int)
        or row["issue_number"] < 1
        or not isinstance(row.get("source_run_ids"), list)
        or any(not str(run_id).isdigit() for run_id in row["source_run_ids"])
        for row in parsed
    ):
        raise LivenessAuditError("official_event_incident_consolidated_evidence_invalid")
    return parsed


def _consolidate_issue_group(
    *, api_url: str, repository: str, token: str, key: str,
    rows: list[dict[str, Any]], deadline: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Keep one deterministic open issue and preserve every duplicate's evidence.

    Identity disagreement is not resolved by choosing a winner.  The caller
    records that group as incomplete and continues reconciling independent
    incident groups.
    """
    identities = {_issue_group_identity(row) for row in rows}
    if len(identities) != 1:
        raise LivenessAuditError("official_event_incident_duplicate_identity_conflict")
    marker, component, reason, contract = next(iter(identities))
    if marker != key or not component or not reason or not contract:
        raise LivenessAuditError("official_event_incident_duplicate_identity_incomplete")
    ordered = sorted(rows, key=_issue_order)
    canonical = ordered[0]
    canonical_number = canonical.get("number")
    if not isinstance(canonical_number, int):
        raise LivenessAuditError("official_event_incident_identity_invalid")

    issue_numbers: set[int] = set()
    source_runs: set[str] = set()
    source_evidence: dict[int, dict[str, Any]] = {}
    refs: list[str] = []
    references_complete = True
    first_failures: list[datetime] = []
    for row in ordered:
        number = row.get("number")
        if isinstance(number, int):
            issue_numbers.add(number)
        body = str(row.get("body") or "")
        for evidence in _existing_issue_evidence(body):
            evidence_number = evidence["issue_number"]
            source_evidence[evidence_number] = evidence
            source_runs.update(str(run_id) for run_id in evidence["source_run_ids"])
        for item in _field(body, "Consolidated issue numbers").split(","):
            try:
                parsed = int(item.strip().lstrip("#"))
            except ValueError:
                continue
            if parsed > 0:
                issue_numbers.add(parsed)
        for item in _field(body, "Consolidated source runs").split(","):
            if item.strip().isdigit():
                source_runs.add(item.strip())
        latest_run = _field(body, "Latest run").split(maxsplit=1)[0]
        if latest_run.isdigit():
            source_runs.add(latest_run)
        if isinstance(number, int):
            row_runs = [latest_run] if latest_run.isdigit() else []
            row_first = _timestamp(body, "First failure")
            source_evidence[number] = {
                "issue_number": number,
                "first_failure_at": row_first.isoformat() if row_first else None,
                "source_run_ids": row_runs,
                "comments_preserved_on_issue": number,
            }
        row_refs, row_complete = _issue_event_refs(body)
        refs.extend(row_refs)
        references_complete = references_complete and row_complete
        first = _timestamp(body, "First failure")
        if first is not None:
            first_failures.append(first)

    refs = list(dict.fromkeys(refs))
    if len(source_evidence) > 100:
        raise LivenessAuditError("official_event_incident_consolidation_evidence_limit_exceeded")
    refs_complete = references_complete and bool(refs)
    body = str(canonical.get("body") or "")
    if first_failures:
        body = _replace_body_field(body, "First failure", min(first_failures).isoformat())
    body = _replace_body_field(body, "Affected event count", str(len(refs)) if refs_complete else "unknown")
    body = _replace_body_field(body, "Event refs", ", ".join(refs[:100]) if refs else "not available")
    body = _replace_body_field(body, "Event refs complete", "true" if refs_complete and len(refs) <= 100 else "false")
    body = _replace_body_field(body, "Consolidated issue numbers", ", ".join(str(item) for item in sorted(issue_numbers)))
    body = _replace_body_field(body, "Consolidated source runs", ", ".join(sorted(source_runs, key=int)) or "unknown")
    evidence_json = json.dumps(
        [source_evidence[number] for number in sorted(source_evidence)],
        sort_keys=True, separators=(",", ":"),
    )
    body = _replace_body_field(body, "Consolidated issue evidence", evidence_json)
    if body != str(canonical.get("body") or ""):
        _request_json(
            api_url, repository, token, "PATCH", f"issues/{canonical_number}",
            {"body": body}, deadline_monotonic=deadline,
        )

    duplicate_numbers: list[int] = []
    for duplicate in ordered[1:]:
        number = duplicate.get("number")
        if not isinstance(number, int):
            raise LivenessAuditError("official_event_incident_identity_invalid")
        duplicate_body = str(duplicate.get("body") or "")
        duplicate_link = f"#{canonical_number}"
        if _field(duplicate_body, "Duplicate of") != duplicate_link:
            duplicate_body = _replace_body_field(duplicate_body, "Duplicate of", duplicate_link)
            _request_json(
                api_url, repository, token, "PATCH", f"issues/{number}",
                {"body": duplicate_body}, deadline_monotonic=deadline,
            )
        _request_json(
            api_url, repository, token, "PATCH", f"issues/{number}",
            {"state": "closed", "state_reason": "not_planned"}, deadline_monotonic=deadline,
        )
        duplicate_numbers.append(number)

    canonical = {**canonical, "body": body}
    return canonical, {
        "marker": key,
        "canonical_issue_number": canonical_number,
        "duplicate_issue_numbers": duplicate_numbers,
        "source_run_ids": sorted(source_runs, key=int),
        "event_refs_complete": refs_complete,
    }


def _resolved_event_refs(trace: dict[str, Any]) -> set[str]:
    resolved: set[str] = set()
    for row in trace.get("events", []):
        if not isinstance(row, dict):
            continue
        event_ref = str(row.get("event_ref") or "").strip()[:64]
        if not event_ref:
            continue
        status = str(row.get("status") or "").casefold()
        reason = str(row.get("reason") or "").casefold()
        expected = bool(row.get("expected"))
        if status in {"delivered", "already_delivered"}:
            resolved.add(event_ref)
        elif not expected and status in {"suppressed", "policy_suppressed", "no_event"}:
            resolved.add(event_ref)
        elif status == "suppressed" and reason in {
            "already_delivered", "policy_suppressed", "notification_not_required",
        }:
            resolved.add(event_ref)
    return resolved


def _historical_event_refs(trace: dict[str, Any], now: datetime) -> set[str]:
    historical: set[str] = set()
    for row in trace.get("events", []):
        if not isinstance(row, dict):
            continue
        event_ref = str(row.get("event_ref") or "").strip()[:64]
        if not event_ref:
            continue
        status = str(row.get("status") or "").casefold()
        expiry = _parse_time(row.get("expires_at") or row.get("source_expires_at"))
        if status in {"expired", "historical_diagnosed"} or row.get("expired") is True or (expiry and expiry <= now):
            historical.add(event_ref)
            continue
        source_type = str(row.get("source_type") or row.get("source_key") or "").casefold()
        detected = _parse_time(row.get("first_detected_at"))
        if (
            source_type in {"financialjuice", "financial_juice", "fj"}
            and status in {"summary_pending", "summary_timeout"}
            and detected is not None
            and now - detected >= timedelta(minutes=30)
        ):
            historical.add(event_ref)
    return historical


def _incident_group(reason: str, contract: str) -> tuple[str, str]:
    component = "financialjuice_summary" if "summary" in reason or "content" in reason else "official_event_delivery"
    source = f"{component}\n{reason[:120]}\n{contract[:40]}"
    return component, hashlib.sha256(source.encode("utf-8")).hexdigest()[:24]


def _read_trace(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LivenessAuditError(f"official_event_trace_unavailable:{type(exc).__name__}") from exc
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != "official-event-trace-v1"
        or not isinstance(value.get("events"), list)
        or not isinstance(value.get("stages"), dict)
        or not value.get("workflow_run_id")
        or not value.get("workflow_sha")
    ):
        raise LivenessAuditError("official_event_trace_identity_invalid")
    return value


def _active_incidents(trace: dict[str, Any], now: datetime) -> dict[str, dict[str, Any]]:
    active: dict[str, dict[str, Any]] = {}
    stages = trace.get("stages", {}) if isinstance(trace.get("stages"), dict) else {}
    for row in trace["events"]:
        if not isinstance(row, dict) or not row.get("expected"):
            continue
        status = str(row.get("status") or "unknown").casefold()
        if status in {"delivered", "already_delivered"}:
            continue
        reason = str(row.get("reason") or status)[:120]
        if status in {"suppressed", "no_event"}:
            reason = reason or "expected_event_not_processed"
        detected = _parse_time(row.get("first_detected_at"))
        recorded = _parse_time(row.get("candidate_recorded_at"))
        if status in {"expired", "historical_diagnosed"} or row.get("expired") is True:
            # Keep the immutable trace as the historical record, but do not
            # reopen a reminder cycle for an occurrence that can no longer run.
            continue
        if status == "ready":
            if str(stages.get("queue") or "").casefold() not in {"acquired", "completed", "not_required"}:
                reason = "writer_queue_blocked"
            elif str(stages.get("prepare") or "").casefold() not in {"prepared_release_current", "not_required"}:
                reason = "release_preparation_failed"
            elif str(stages.get("public_gate") or "").casefold() != "true":
                reason = "public_release_gate_blocked"
            elif str(stages.get("sender") or "").casefold() in {"failure", "skipped", "cancelled"}:
                reason = "sender_not_completed"
            elif str(stages.get("durable_receipt") or "").casefold() != "true":
                reason = "durable_receipt_unverified"
            else:
                continue
        if status in {"summary_pending", "summary_timeout"}:
            source_type = str(row.get("source_type") or row.get("source_key") or "").strip().casefold()
            if source_type in {"financialjuice", "financial_juice", "fj"}:
                # Only a verified FJ summary wait may become this incident;
                # source time and later audit observation time are not substitutes.
                if detected is None:
                    continue
                age = now - detected
                if age < SUMMARY_ESCALATION:
                    continue
                if age >= timedelta(minutes=30):
                    continue
                reason = "priority_summary_timeout"
            elif status == "summary_pending" and detected and now - detected < SUMMARY_ESCALATION:
                continue
        elif status == "content_incomplete":
            # Preserve the original classification; an ordinary incomplete
            # notice is not an FJ summary timeout.
            pass
        elif status == "unknown" and reason in {"candidate_ready", "notification_policy_not_eligible"}:
            continue
        contract = str(row.get("summary_contract_version") or "unknown")[:40]
        component, incident_key = _incident_group(reason, contract)
        incident = active.setdefault(incident_key, {
            "component": component,
            "reason": reason,
            "contract_version": contract,
            "first_failure_at": (detected or recorded or now).isoformat(),
            "event_refs": [],
            "latest_progress_at": str(row.get("last_progress_at") or row.get("candidate_recorded_at") or "")[:80],
            "workflow_run_id": str(trace.get("workflow_run_id") or "")[:32],
            "workflow_sha": str(trace.get("workflow_sha") or "")[:40],
        })
        event_ref = str(row.get("event_ref") or "")[:64]
        if event_ref and event_ref not in incident["event_refs"]:
            incident["event_refs"].append(event_ref)
        progress = str(row.get("last_progress_at") or row.get("candidate_recorded_at") or "")[:80]
        if progress > incident["latest_progress_at"]:
            incident["latest_progress_at"] = progress
        if detected:
            current_first = _parse_time(incident["first_failure_at"])
            if current_first is None or detected < current_first:
                incident["first_failure_at"] = detected.isoformat()
    return active


def _body(
    key: str, incident: dict[str, Any], now: datetime, *,
    preserve_first: datetime | None = None,
    next_reminder_at: datetime | None = None,
) -> str:
    first = preserve_first or _parse_time(incident.get("first_failure_at")) or now
    placeholders = {"not available", "unknown", "none", "n/a", "na"}
    all_refs = list(dict.fromkeys(
        str(ref)[:64]
        for ref in incident.get("event_refs", [])
        if str(ref).strip() and str(ref).strip().casefold() not in placeholders
    ))
    refs = ", ".join(all_refs[:100]) or "not available"
    next_reminder = next_reminder_at or (now + REMINDER_INTERVAL)
    return "\n".join((
        f"{EVENT_INCIDENT_MARKER}{key}",
        f"Component: {incident['component']}",
        f"Root cause: {incident['reason']}",
        f"Summary contract: {incident['contract_version']}",
        f"Affected event count: {len(all_refs)}",
        f"Event refs: {refs}",
        f"Event refs complete: {'true' if all_refs and len(all_refs) <= 100 else 'false'}",
        f"First failure: {first.isoformat()}",
        f"Latest progress: {incident['latest_progress_at'] or 'unknown'}",
        f"Latest run: {incident['workflow_run_id']} ({incident['workflow_sha']})",
        f"Observed at: {now.isoformat()}",
        f"Next reminder at: {next_reminder.isoformat()}",
    ))


def reconcile_incidents(
    *, api_url: str, repository: str, token: str, trace_path: str | Path,
    now: datetime | None = None, defer_notification_cadence: bool = False,
    deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    trace = _read_trace(trace_path)
    stages = trace["stages"]
    # A failed or incomplete scan is not evidence that an earlier incident recovered.
    scan_complete = str(stages.get("scan") or "").casefold() in {"success", "completed"}
    active = _active_incidents(trace, current)
    deadline = deadline_monotonic or __import__("time").monotonic() + MAX_AUDIT_SECONDS
    issues = _open_incidents(api_url, repository, token, deadline_monotonic=deadline)
    event_issues = [
        issue for issue in issues
        if str(issue.get("title") or "").startswith(EVENT_ISSUE_TITLE_PREFIX)
    ]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for issue in event_issues:
        key = _marker(issue.get("body"))
        if key:
            grouped.setdefault(key, []).append(issue)
    indexed: dict[str, list[dict[str, Any]]] = {}
    unresolved_groups: list[dict[str, Any]] = []
    consolidated_groups: list[dict[str, Any]] = []
    unresolved_keys: set[str] = set()
    for key, rows in grouped.items():
        if len(rows) == 1:
            indexed[key] = rows
            continue
        try:
            canonical, result = _consolidate_issue_group(
                api_url=api_url, repository=repository, token=token,
                key=key, rows=rows, deadline=deadline,
            )
        except LivenessAuditError as exc:
            unresolved_keys.add(key)
            unresolved_groups.append({
                "marker": key,
                "issue_numbers": sorted(
                    int(row["number"]) for row in rows if isinstance(row.get("number"), int)
                ),
                "reason": str(exc)[:160],
            })
            continue
        indexed[key] = [canonical]
        consolidated_groups.append(result)
    opened: list[int] = []
    reminded: list[int] = []
    recovered: list[int] = []
    historical_pending: list[int] = []
    cadence_confirmations: list[dict[str, str | int]] = []
    for key, incident in active.items():
        if key in unresolved_keys:
            continue
        matches = indexed.get(key, [])
        if not matches:
            next_reminder = current if defer_notification_cadence else current + REMINDER_INTERVAL
            body = _body(key, incident, current, next_reminder_at=next_reminder)
            if defer_notification_cadence:
                body = _mark_alert_pending(body, _pending_alert_consumer(), current)
            created = _request_json(
                api_url, repository, token, "POST", "issues",
                {"title": f"{EVENT_ISSUE_TITLE_PREFIX} / {incident['component']}", "body": body},
                deadline_monotonic=deadline,
            )
            if not isinstance(created, dict) or not isinstance(created.get("number"), int):
                raise LivenessAuditError("official_event_incident_create_invalid")
            opened.append(created["number"])
            if defer_notification_cadence:
                cadence_confirmations.append({
                    "issue_number": created["number"],
                    "marker": f"{EVENT_INCIDENT_MARKER}{key}",
                    "next_reminder_at": (current + REMINDER_INTERVAL).isoformat(),
                })
            continue
        issue = matches[0]
        number = issue.get("number")
        if not isinstance(number, int):
            raise LivenessAuditError("official_event_incident_identity_invalid")
        first = _timestamp(issue.get("body"), "First failure")
        next_due = _timestamp(issue.get("body"), "Next reminder at")
        due = next_due is None or current >= next_due
        pending_current = (
            defer_notification_cadence
            and _field(issue.get("body"), "Alert pending consumer") == _pending_alert_consumer()
        )
        notify_due = due and (
            not defer_notification_cadence
            or can_emit_pending_alert(issue.get("body"), _pending_alert_consumer(), current)
        )
        prior_refs, prior_refs_complete = _issue_event_refs(issue.get("body"))
        merged_incident = dict(incident)
        merged_incident["event_refs"] = list(dict.fromkeys([*prior_refs, *incident["event_refs"]]))
        body = _body(
            key, merged_incident, current, preserve_first=first,
            next_reminder_at=(
                (next_due or current) if due and defer_notification_cadence
                else current + REMINDER_INTERVAL if due
                else next_due
            ),
        )
        for label in ("Consolidated issue numbers", "Consolidated source runs"):
            value = _field(issue.get("body"), label)
            if value:
                body = _replace_body_field(body, label, value)
        if defer_notification_cadence:
            if notify_due:
                body = _mark_alert_pending(body, _pending_alert_consumer(), current)
            else:
                body = preserve_pending_alert(body, issue.get("body"))
        if not prior_refs_complete:
            body = body.replace("Event refs complete: true", "Event refs complete: false")
        _request_json(
            api_url, repository, token, "PATCH", f"issues/{number}", {"body": body},
            deadline_monotonic=deadline,
        )
        if notify_due and not pending_current:
            reminded.append(number)
            if defer_notification_cadence:
                cadence_confirmations.append({
                    "issue_number": number,
                    "marker": f"{EVENT_INCIDENT_MARKER}{key}",
                    "next_reminder_at": (current + REMINDER_INTERVAL).isoformat(),
                })
    if scan_complete:
        resolved_refs = _resolved_event_refs(trace)
        historical_refs = _historical_event_refs(trace, current)
        for key, rows in indexed.items():
            if key in active or key in unresolved_keys:
                continue
            issue = rows[0]
            number = issue.get("number")
            if not isinstance(number, int):
                raise LivenessAuditError("official_event_incident_identity_invalid")
            issue_refs, refs_complete = _issue_event_refs(issue.get("body"))
            first_failure = _timestamp(issue.get("body"), "First failure")
            if not issue_refs and first_failure is not None and current - first_failure >= REMINDER_INTERVAL:
                # A completed scan can classify an unreferenced old incident as
                # unknown, but cannot establish recovery or delivery. A later
                # attributable active event rebuilds the body and reactivates it.
                body = str(issue.get("body") or "")
                historical_pending.append(number)
                if _field(body, "Lifecycle") != "historical_pending_verification":
                    lines = [
                        line for line in body.splitlines()
                        if not line.startswith((
                            "Lifecycle:", "Next reminder at:", "Alert pending consumer:",
                            "Alert pending since:", "Reminder policy:",
                        ))
                    ]
                    lines.extend((
                        "Lifecycle: historical_pending_verification",
                        f"Historical review recorded at: {current.isoformat()}",
                        "Reminder policy: stopped; prior event identity remains unknown; no recovery claimed",
                    ))
                    _request_json(
                        api_url, repository, token, "PATCH", f"issues/{number}",
                        {"body": "\n".join(lines)[:12000]}, deadline_monotonic=deadline,
                    )
                continue
            if refs_complete and issue_refs and set(issue_refs).issubset(historical_refs):
                body = str(issue.get("body") or "")
                lines = [
                    line for line in body.splitlines()
                    if not line.startswith(("Next reminder at:", "Alert pending consumer:", "Alert pending since:"))
                ]
                if _field(body, "Lifecycle") != "historical_diagnosed":
                    lines.append("Lifecycle: historical_diagnosed")
                    lines.append(f"Historical diagnosis confirmed at: {current.isoformat()}")
                    lines.append("Reminder policy: stopped; source event expired and was not resent")
                    _request_json(
                        api_url, repository, token, "PATCH", f"issues/{number}",
                        {"body": "\n".join(lines)[:12000]}, deadline_monotonic=deadline,
                    )
                continue
            # A clean scan with no candidates is not evidence of recovery. Close
            # only when every event recorded on the issue has a terminal outcome.
            if not refs_complete or not issue_refs or not set(issue_refs).issubset(resolved_refs):
                continue
            prior_body = str(issue.get("body") or "").rstrip()
            prior_body += (
                f"\nRecovery verified by a complete official-event scan at {current.isoformat()}; "
                f"terminal event evidence: {', '.join(issue_refs[:20])}.\n"
            )
            _request_json(
                api_url, repository, token, "PATCH", f"issues/{number}",
                {"body": prior_body[:12000], "state": "closed", "state_reason": "completed"},
                deadline_monotonic=deadline,
            )
            recovered.append(number)
    return {
        "schema_version": "official-event-incident-reconcile-v1",
        "diagnostic_complete": scan_complete and not unresolved_groups,
        "incident_active": bool(active) or bool(unresolved_groups),
        "opened_issue_numbers": opened,
        "reminded_issue_numbers": reminded,
        "recovered_issue_numbers": recovered,
        "historical_pending_issue_numbers": historical_pending,
        "consolidated_issue_groups": consolidated_groups,
        "unresolved_issue_groups": unresolved_groups,
        "notification_cadence_confirmations": cadence_confirmations,
    }


def main() -> int:
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    trace_path = os.environ.get("OFFICIAL_EVENT_TRACE_PATH", "official-event-trace.json")
    if not token or "/" not in repository:
        print("official_event_incident_configuration_invalid", file=sys.stderr)
        return 1
    try:
        result = reconcile_incidents(
            api_url=api_url, repository=repository, token=token, trace_path=trace_path,
        )
    except LivenessAuditError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
