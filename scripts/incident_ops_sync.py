"""Bind central reconciliation findings to the private IncidentCoordinator."""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.incident_ops_auth import IncidentOpsAuthError, fetch_oidc_token, request_worker_json
from scripts.incident_reconciliation import RESEARCH_TITLE_PREFIX
from scripts.incident_reconciliation_health import ISSUE_TITLE_PREFIX as CENTRAL_HEALTH_TITLE_PREFIX
from scripts.monitor_liveness import (
    AUDIT_ISSUE_TITLE_PREFIX,
    EVENT_ISSUE_TITLE_PREFIX,
    LivenessAuditError,
    _request_json,
)
from scripts.monitor_liveness import (
    ISSUE_TITLE_PREFIX as MONITOR_TITLE_PREFIX,
)
from scripts.scheduled_brief_incidents import ISSUE_TITLE_PREFIX as SCHEDULED_TITLE_PREFIX
from src.incident_envelope import make_incident_envelope

MAX_RESULT_BYTES = 20 * 1024 * 1024
MAX_ENVELOPES = 100
WORKFLOW_PATH = ".github/workflows/incident-reconciliation.yml"
ALLOWED_INCIDENT_PREFIXES = (
    MONITOR_TITLE_PREFIX, AUDIT_ISSUE_TITLE_PREFIX, EVENT_ISSUE_TITLE_PREFIX,
    SCHEDULED_TITLE_PREFIX, RESEARCH_TITLE_PREFIX, CENTRAL_HEALTH_TITLE_PREFIX,
)
CRITICAL_TERMS = (
    "missed_deadline", "scheduled_anchor_claim_missing", "pagination_identity_invalid",
    "identity_mismatch", "hash_mismatch", "central_reconciliation_coverage_incomplete",
    "publication_gate_failed", "delivery_unknown",
)
SAFE_IDENTITY = re.compile(r"^[A-Za-z0-9_.:/@+-]{1,240}$")


class IncidentOpsSyncError(RuntimeError):
    """Raised when incident evidence cannot be safely handed to the coordinator."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed > 0 else None


def _field(body: str, name: str) -> str:
    values = [line.partition(":")[2].strip() for line in body.splitlines() if line.startswith(name + ":")]
    return values[0] if len(values) == 1 else ""


def _tokens(value: str) -> list[str]:
    if not value:
        return []
    output: list[str] = []
    for raw in re.split(r"[,;\n]", value):
        token = raw.strip()
        if token and len(token) <= 160 and SAFE_IDENTITY.fullmatch(token):
            output.append(token)
    return sorted(set(output))


def _slot_identity(value: str) -> dict[str, str] | None:
    label = value.strip()
    display = re.fullmatch(
        r"(?P<slot>[A-Za-z0-9_-]{1,32}):(?P<date>\d{4}-\d{2}-\d{2})"
        r"(?:\s+\((?P<anchor>[A-Za-z0-9_.:/@+-]{1,100})\))?",
        label,
    )
    if display:
        result = {"slot": display.group("slot"), "date": display.group("date")}
        if display.group("anchor"):
            result["anchor"] = display.group("anchor")
        return result
    anchored = re.fullmatch(
        r"(?P<market>taiwan|us):(?P<date>\d{4}-\d{2}-\d{2}):(?P<slot>[A-Za-z0-9_-]{1,32})",
        label,
        re.IGNORECASE,
    )
    if anchored:
        return {
            "slot": anchored.group("slot"), "date": anchored.group("date"), "anchor": label,
        }
    return None


def _root_cause(issue: dict[str, Any]) -> str:
    body = str(issue.get("body") or "")
    marker = next((line.strip() for line in body.splitlines() if re.fullmatch(r"[a-z][a-z0-9-]*=[A-Za-z0-9_.:/;=-]{1,240}", line.strip())), "")
    reason = _field(body, "Root cause") or _field(body, "Failure class") or _field(body, "First failure reason")
    if marker:
        reason = marker.partition("=")[2]
    if not reason:
        reason = str(issue.get("title") or "incident_reason_unknown").split(" / ", 1)[-1]
    # Root causes cross into email and Worker state. Reduce arbitrary Issue
    # prose to a stable code; never copy source URLs, query values, or comments.
    reason = re.sub(r"[^A-Za-z0-9_.:-]+", "_", reason.casefold()).strip("_:")[:180]
    return reason or "incident_reason_unknown"


def _incident_type(title: str, marker: str) -> tuple[str, str]:
    value = title.casefold()
    if value.startswith(SCHEDULED_TITLE_PREFIX.casefold()):
        return "scheduled_report_failure", "scheduled_report"
    if value.startswith(EVENT_ISSUE_TITLE_PREFIX.casefold()):
        return "official_event_failure", "official_event_monitor"
    if value.startswith(AUDIT_ISSUE_TITLE_PREFIX.casefold()) or "official-monitor-audit-incident=" in marker.casefold():
        return "monitor_audit_failure", "official_monitor_audit"
    if value.startswith(MONITOR_TITLE_PREFIX.casefold()):
        return "monitor_failure", "official_event_monitor"
    if value.startswith(RESEARCH_TITLE_PREFIX.casefold()):
        return "research_publication_failure", "unified_research_report"
    if value.startswith(CENTRAL_HEALTH_TITLE_PREFIX.casefold()):
        return "central_reconciliation_failure", "central_reconciliation"
    raise IncidentOpsSyncError("incident_issue_title_unrecognized")


def _lifecycle(issue: dict[str, Any], row: dict[str, Any], issue_number: int) -> str:
    body = str(issue.get("body") or "")
    recovered = {_safe_int(item) for item in row.get("recovered_issue_numbers", []) if _safe_int(item)}
    if issue_number in recovered:
        return "recovered"
    historical_diagnosed = {_safe_int(item) for item in row.get("historical_diagnosed_issue_numbers", []) if _safe_int(item)}
    if issue_number in historical_diagnosed:
        return "historical_diagnosed"
    historical_pending = {_safe_int(item) for item in row.get("historical_pending_issue_numbers", []) if _safe_int(item)}
    if issue_number in historical_pending:
        return "historical_pending_verification"
    existing = _field(body, "Lifecycle")
    if str(issue.get("state") or "").casefold() == "closed":
        if existing in {"recovered", "historical_diagnosed", "historical_pending_verification"}:
            return existing
        return "historical_pending_verification"
    if existing in {"active", "recovery_pending", "recovered", "historical_diagnosed", "historical_pending_verification"}:
        return existing
    if row.get("incident_active") is True or issue.get("state") == "open":
        return "active"
    # A closed Issue does not prove recovery. Keep its last known status explicit.
    return "historical_pending_verification"


def _affected_identities(issue: dict[str, Any], row: dict[str, Any], issue_number: int, marker: str) -> list[dict[str, Any]]:
    body = str(issue.get("body") or "")
    raw_slots = [item.strip() for item in _field(body, "Affected slots").split(",") if item.strip()]
    refs = _tokens(_field(body, "Affected event refs") or _field(body, "Affected refs"))
    source_slot = str(row.get("slot") or row.get("anchor") or "").strip()
    source_ref = str(row.get("event_ref") or row.get("source_event_ref") or "").strip()
    identities: list[dict[str, Any]] = []
    for slot in raw_slots:
        structured = _slot_identity(slot)
        if structured:
            identities.append({"issue_number": issue_number, "marker": marker[:240], **structured})
        elif SAFE_IDENTITY.fullmatch(slot):
            identities.append({"issue_number": issue_number, "marker": marker[:240], "slot": slot})
    if source_slot and SAFE_IDENTITY.fullmatch(source_slot) and not any(
        item.get("slot") == source_slot or item.get("anchor") == source_slot for item in identities
    ):
        identities.append({"issue_number": issue_number, "marker": marker[:240], "slot": source_slot})
    if source_ref and SAFE_IDENTITY.fullmatch(source_ref):
        refs = sorted(set([*refs, source_ref]))
    if refs:
        identities.extend({"issue_number": issue_number, "marker": marker[:240], "event_ref": ref} for ref in refs)
    if not identities:
        identities.append({"issue_number": issue_number, "marker": marker[:240] or "marker_unknown"})
    return identities[:100]


def _incident_issue_numbers(row: dict[str, Any]) -> list[int]:
    values: list[Any] = []
    for key in (
        "issue_number", "canonical_issue_number", "opened_issue_numbers", "reminded_issue_numbers",
        "recovered_issue_numbers", "historical_pending_issue_numbers", "historical_diagnosed_issue_numbers",
    ):
        value = row.get(key)
        if isinstance(value, list):
            values.extend(value)
        elif value is not None:
            values.append(value)
    return sorted({number for item in values if (number := _safe_int(item))})


def _declared_new_impact(row: dict[str, Any], issue_number: int, impact_identity: dict[str, Any]) -> bool:
    declarations = row.get("new_impact_identities", [])
    if not isinstance(declarations, list) or len(declarations) > 100:
        raise IncidentOpsSyncError("incident_new_impact_declarations_invalid")
    for declaration in declarations:
        if not isinstance(declaration, dict) or set(declaration) - {"issue_number", "slot", "date", "anchor", "event_ref", "marker"}:
            raise IncidentOpsSyncError("incident_new_impact_declaration_invalid")
        declared_issue = _safe_int(declaration.get("issue_number"))
        selectors = [key for key in ("slot", "date", "anchor", "event_ref", "marker") if key in declaration]
        if declared_issue is None or not selectors:
            raise IncidentOpsSyncError("incident_new_impact_declaration_identity_invalid")
        if any(
            not isinstance(declaration.get(selector), str)
            or (selector == "date" and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(declaration.get(selector))))
            or (selector != "date" and not SAFE_IDENTITY.fullmatch(str(declaration.get(selector))))
            for selector in selectors
        ):
            raise IncidentOpsSyncError("incident_new_impact_declaration_identity_invalid")
        if declared_issue == issue_number and all(impact_identity.get(selector) == declaration[selector] for selector in selectors):
            return True
    return False


def _fetch_issue(number: int, *, repository: str, api_url: str, token: str, deadline: float) -> dict[str, Any]:
    issue = _request_json(api_url, repository, token, "GET", f"issues/{number}", deadline_monotonic=deadline)
    if not isinstance(issue, dict) or _safe_int(issue.get("number")) != number:
        raise IncidentOpsSyncError("incident_issue_readback_identity_invalid")
    if str(issue.get("state") or "").casefold() not in {"open", "closed"}:
        raise IncidentOpsSyncError("incident_issue_state_invalid")
    repository_url = f"{api_url.rstrip('/')}/repos/{repository}".rstrip("/").casefold()
    if str(issue.get("repository_url") or "").rstrip("/").casefold() != repository_url:
        raise IncidentOpsSyncError("incident_issue_repository_mismatch")
    title = str(issue.get("title") or "")
    if not title.startswith(ALLOWED_INCIDENT_PREFIXES):
        raise IncidentOpsSyncError("incident_issue_title_not_supported")
    return issue


def build_envelopes(
    result: dict[str, Any], *, issues: dict[int, dict[str, Any]], repository: str,
    run_id: int, attempt: int, sha: str, artifact_id: int, artifact_digest: str,
) -> list[dict[str, Any]]:
    if result.get("schema_version") != "incident-reconciliation-v1":
        raise IncidentOpsSyncError("incident_reconciliation_schema_unsupported")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise IncidentOpsSyncError("incident_consumer_sha_invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", artifact_digest):
        raise IncidentOpsSyncError("incident_artifact_digest_invalid")
    observed_at = str(result.get("observed_at") or "")
    if not observed_at:
        raise IncidentOpsSyncError("incident_result_observed_at_missing")
    all_rows = result.get("results")
    if not isinstance(all_rows, list):
        raise IncidentOpsSyncError("incident_result_rows_invalid")
    evidence = [{
        "repository": repository,
        "workflow": WORKFLOW_PATH,
        "run_id": run_id,
        "attempt": attempt,
        "sha": sha,
        "artifact_id": artifact_id,
        "artifact_digest": f"sha256:{artifact_digest.lower()}",
    }]
    envelopes: list[dict[str, Any]] = []
    new_impact_claimed: set[tuple[str, str, str]] = set()
    for row in all_rows:
        if not isinstance(row, dict):
            raise IncidentOpsSyncError("incident_result_row_invalid")
        for issue_number in _incident_issue_numbers(row):
            issue = issues.get(issue_number)
            if issue is None:
                raise IncidentOpsSyncError("incident_issue_evidence_missing")
            title = str(issue.get("title") or "")
            body = str(issue.get("body") or "")
            marker = next((line.strip() for line in body.splitlines() if re.fullmatch(r"[a-z][a-z0-9-]*=[A-Za-z0-9_.:/;=-]{1,240}", line.strip())), "")
            incident_type, component = _incident_type(title, marker)
            root_cause = _root_cause(issue)
            lifecycle = _lifecycle(issue, row, issue_number)
            issue_opened = issue_number in {
                _safe_int(value) for value in row.get("opened_issue_numbers", []) if _safe_int(value)
            } or (row.get("incident_opened") is True and _safe_int(row.get("issue_number")) == issue_number)
            incident_identity = (incident_type.casefold(), component.casefold(), root_cause.casefold())
            source_run_id = _safe_int(row.get("source_run_id"))
            source_attempt = _safe_int(row.get("source_attempt"))
            source_identity: dict[str, Any] = {
                "issue_number": issue_number,
                "marker": marker[:240] or "marker_unknown",
            }
            source_slot = str(row.get("slot") or row.get("anchor") or "").strip()
            source_ref = str(row.get("event_ref") or row.get("source_event_ref") or "").strip()
            if source_slot and SAFE_IDENTITY.fullmatch(source_slot):
                source_identity["slot"] = source_slot
            if source_ref and SAFE_IDENTITY.fullmatch(source_ref):
                source_identity["event_ref"] = source_ref
            if source_run_id:
                source_identity["source_run_id"] = source_run_id
            if source_attempt:
                source_identity["source_attempt"] = source_attempt
            for impact_identity in _affected_identities(issue, row, issue_number, marker):
                if source_run_id and not ("slot" in impact_identity or "event_ref" in impact_identity):
                    # Keep run identity as supporting provenance only; the impact key remains the Issue's stable identity.
                    pass
                reason = root_cause.casefold()
                severity = "critical" if any(term in reason for term in CRITICAL_TERMS) else "high"
                impact_is_new = issue_opened or _declared_new_impact(row, issue_number, impact_identity)
                new_impact = lifecycle == "active" and impact_is_new and incident_identity not in new_impact_claimed
                if new_impact:
                    # One reconciliation batch may describe several slots or events
                    # under the same incident. Reserve one generation-level alert.
                    new_impact_claimed.add(incident_identity)
                status = str(row.get("status") or "unknown")[:80]
                diagnostic_complete = row.get("diagnostic_complete") is True
                evidence_integrity = "verified" if diagnostic_complete else "partial"
                first = _time_field(_field(body, "First failure") or _field(body, "First detected"))
                source_occurred = _time_field(_field(body, "Source occurred at") or _field(body, "Source published at"))
                envelope = make_incident_envelope(
                    incident_type=incident_type,
                    component=component,
                    root_cause=root_cause,
                    impact_type="incident_issue_impact",
                    impact_identity=impact_identity,
                    impact={
                        "identity": impact_identity,
                        "description": f"Issue #{issue_number}; latest diagnostic state: {status}",
                    },
                    evidence=evidence,
                    observed_at=observed_at,
                    first_detected_at=first,
                    source_occurred_at=source_occurred,
                    severity=severity,
                    lifecycle=lifecycle,
                    evidence_integrity=evidence_integrity,
                    new_impact=new_impact,
                    generation=1,
                    state_version=1,
                    issue_numbers=[issue_number],
                    compatibility={"adapter": "incident-reconciliation-v1", "legacy_source": marker or None},
                )
                envelopes.append(envelope)
                if len(envelopes) > MAX_ENVELOPES:
                    raise IncidentOpsSyncError("incident_envelope_batch_limit_exceeded")
    return envelopes


def _time_field(value: str) -> str:
    if not value:
        return "unknown"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "unknown"
    if parsed.tzinfo is None:
        return "unknown"
    return parsed.astimezone(UTC).isoformat()


def _token() -> str:
    audience = os.environ.get("INCIDENT_OPS_AUDIENCE", "https://prstk-incident-ops")
    try:
        return fetch_oidc_token(dict(os.environ), audience=audience)
    except IncidentOpsAuthError as exc:
        raise IncidentOpsSyncError(str(exc)) from exc


def _post(url: str, payload: dict[str, Any], token: str) -> dict[str, Any]:
    try:
        return request_worker_json(url, method="POST", token=token, payload=payload)
    except IncidentOpsAuthError as exc:
        raise IncidentOpsSyncError(str(exc)) from exc


def sync_file(path: Path) -> dict[str, Any]:
    size = path.stat().st_size
    if size <= 0 or size > MAX_RESULT_BYTES:
        raise IncidentOpsSyncError("incident_result_file_size_invalid")
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise IncidentOpsSyncError("incident_result_object_invalid")
    repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if repository.casefold() != "hanjhou2000716/prstklab-stk-detector":
        raise IncidentOpsSyncError("incident_repository_identity_invalid")
    run_id = _safe_int(os.environ.get("GITHUB_RUN_ID"))
    attempt = _safe_int(os.environ.get("GITHUB_RUN_ATTEMPT"))
    sha = os.environ.get("GITHUB_SHA", "").lower()
    artifact_id = _safe_int(os.environ.get("INCIDENT_RESULT_ARTIFACT_ID"))
    digest = os.environ.get("INCIDENT_RESULT_ARTIFACT_DIGEST", "").removeprefix("sha256:").lower()
    if not run_id or not attempt or not artifact_id:
        raise IncidentOpsSyncError("incident_artifact_identity_missing")
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise IncidentOpsSyncError("github_read_token_missing")
    issue_numbers = sorted({number for row in result.get("results", []) if isinstance(row, dict) for number in _incident_issue_numbers(row)})
    deadline = time.monotonic() + 90
    issues = {
        number: _fetch_issue(number, repository=repository, api_url=api_url, token=token, deadline=deadline)
        for number in issue_numbers
    }
    envelopes = build_envelopes(
        result, issues=issues, repository=repository, run_id=run_id,
        attempt=attempt, sha=sha, artifact_id=artifact_id, artifact_digest=digest,
    )
    output: dict[str, Any] = {"status": "no_incident_evidence", "envelope_count": 0, "accepted_count": 0}
    if envelopes:
        mode = os.environ.get("INCIDENT_OPS_MODE", "shadow").strip().lower()
        if mode not in {"shadow", "live"}:
            raise IncidentOpsSyncError("incident_ops_mode_invalid")
        base = os.environ.get("INCIDENT_OPS_URL", "").rstrip("/")
        if not base:
            if mode == "live":
                raise IncidentOpsSyncError("incident_ops_url_required_in_live_mode")
            output["status"] = "not_configured_shadow"
        else:
            token = _token()
            output = _post(f"{base}/ops/incidents/evidence", {"producer_mode": mode, "envelopes": envelopes}, token)
            output["status"] = "accepted_shadow" if mode != "live" else "accepted_live"
        output["envelope_count"] = len(envelopes)
    return output


def main() -> int:
    path = Path(os.environ.get("INCIDENT_RECONCILIATION_RESULT_PATH", "incident-reconciliation-state.json"))
    try:
        result = sync_file(path)
    except (IncidentOpsSyncError, LivenessAuditError, OSError, UnicodeError, ValueError) as exc:
        print(f"incident_ops_sync_failed:{str(exc)[:180]}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write("## Durable incident coordinator handoff\n\n")
            summary.write(f"- status: {result.get('status', 'unknown')}\n")
            summary.write(f"- envelopes: {result.get('envelope_count', 0)}\n")
            summary.write(f"- accepted: {result.get('accepted_count', 'not reported')}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
