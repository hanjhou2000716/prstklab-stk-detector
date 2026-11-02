"""One-time, read-only legacy issue/journal import into IncidentCoordinator."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from scripts.incident_notification_outlet import (
    CONTROL_ISSUE_TITLE,
    CONTROL_MARKER,
    _parse_journal_body,
    _read_journal_issues,
)
from scripts.incident_ops_auth import IncidentOpsAuthError, fetch_oidc_token, worker_post_json
from scripts.incident_ops_sync import (
    ALLOWED_INCIDENT_PREFIXES,
    CRITICAL_TERMS,
    _affected_identities,
    _incident_type,
    _root_cause,
)
from scripts.incident_reconciliation import CENTRAL_WORKFLOW_PATH
from scripts.incident_reconciliation_health import (
    _read_result as _read_health_result,
)
from scripts.incident_reconciliation_health import (
    _result_is_complete,
)
from scripts.monitor_liveness import LivenessAuditError, _request_json
from src.incident_envelope import make_incident_envelope

REPOSITORY = "hanjhou2000716/prstklab-stk-detector"
REPOSITORY_ID = 1309835643
RECIPIENT = "hanjhou2000716@gmail.com"
EXPECTED_BASELINE_SHA = "6984defd4b97ca190ae99fe472f722a43ad7ecde"
IMPORT_WORKFLOW_PATH = ".github/workflows/incident-ops-import.yml"
HEALTH_WORKFLOW_PATH = ".github/workflows/incident-reconciliation-health.yml"
MAX_IMPORT_BYTES = 230_000
MAX_INCIDENTS = 100
MAX_CONFIRMED_WINDOWS = 256
KNOWN_HISTORY = {
    1099: "historical_pending_verification",
    1120: "historical_diagnosed",
    1121: "historical_pending_verification",
    1144: "active",
}


class IncidentImportError(RuntimeError):
    """Raised when the legacy snapshot cannot be proven complete and safe."""


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number > 0 else None


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else None


def _time_field(value: Any) -> str:
    parsed = _parse_time(value)
    return parsed.isoformat() if parsed else "unknown"


def _issue_number(row: dict[str, Any]) -> int | None:
    value = _positive_int(row.get("number"))
    if value is None or "pull_request" in row:
        return None
    title = str(row.get("title") or "")
    return value if title.startswith(ALLOWED_INCIDENT_PREFIXES) else None


def _issue_marker(body: str) -> str:
    return next((
        line.strip() for line in body.splitlines()
        if re.fullmatch(r"[a-z][a-z0-9-]*=[A-Za-z0-9_.:/;=-]{1,240}", line.strip())
    ), "")


def _issue_lifecycle(issue: dict[str, Any], *, recovery_verified: bool) -> str:
    number = _positive_int(issue.get("number"))
    if number == 1145:
        return "recovered" if recovery_verified else "historical_pending_verification"
    if number in KNOWN_HISTORY:
        return KNOWN_HISTORY[number]
    body = str(issue.get("body") or "")
    lifecycle_rows = [line.partition(":")[2].strip() for line in body.splitlines() if line.startswith("Lifecycle:")]
    if len(lifecycle_rows) == 1 and lifecycle_rows[0] in {
        "active", "recovery_pending", "recovered", "historical_diagnosed", "historical_pending_verification",
    }:
        return "historical_pending_verification" if lifecycle_rows[0] == "recovered" else lifecycle_rows[0]
    return "active" if str(issue.get("state") or "").lower() == "open" else "historical_pending_verification"


def _confirmed_windows(journal: dict[str, Any]) -> list[dict[str, Any]]:
    decisions = journal.get("recent_decisions")
    if not isinstance(decisions, list) or len(decisions) > 96:
        raise IncidentImportError("legacy_journal_decision_list_invalid")
    recipient_hash = hashlib.sha256(RECIPIENT.encode("utf-8")).hexdigest()
    windows: dict[str, dict[str, Any]] = {}
    for row in decisions:
        if not isinstance(row, dict):
            raise IncidentImportError("legacy_journal_decision_invalid")
        if row.get("status") != "confirmed" or row.get("notification_mode") != "half_hour_digest":
            continue
        window_key = str(row.get("window_key") or "")
        scheduled = _parse_time(window_key)
        confirmed_at = _parse_time(row.get("confirmed_at"))
        decision_id = str(row.get("decision_id") or "")
        outlet_run_id = _positive_int(row.get("outlet_run_id"))
        outlet_attempt = _positive_int(row.get("outlet_attempt"))
        if (
            scheduled is None or scheduled.minute not in {0, 30}
            or scheduled.second != 0 or scheduled.microsecond != 0
            or confirmed_at is None or confirmed_at < scheduled
            or not re.fullmatch(r"[0-9a-f]{64}", decision_id)
            or not outlet_run_id or not outlet_attempt
        ):
            raise IncidentImportError("legacy_confirmed_window_evidence_invalid")
        normalized_key = scheduled.isoformat()
        item = {
            "decision_key": f"ordinary|{normalized_key}|gmail|{recipient_hash}",
            "window_key": normalized_key,
            "channel": "gmail",
            "recipient_hash": recipient_hash,
            "status": "confirmed",
            "confirmed_at": confirmed_at.isoformat(),
            "decision_id": decision_id,
            "outlet_run_id": outlet_run_id,
            "outlet_attempt": outlet_attempt,
        }
        previous = windows.get(normalized_key)
        if previous is not None and previous != item:
            raise IncidentImportError("legacy_confirmed_window_conflict")
        windows[normalized_key] = item
    result = [windows[key] for key in sorted(windows)]
    if len(result) > MAX_CONFIRMED_WINDOWS:
        raise IncidentImportError("legacy_confirmed_window_limit_exceeded")
    return result


def snapshot_identity(journal_generation: int, journal_body: str) -> str:
    if isinstance(journal_generation, bool) or not isinstance(journal_generation, int) or journal_generation < 0:
        raise IncidentImportError("legacy_journal_generation_invalid")
    digest = hashlib.sha256(journal_body.encode("utf-8")).hexdigest()
    return f"journal-{journal_generation}-{digest[:32]}"


def _workflow_id(*, workflow_path: str, repository: str, api_url: str, token: str, deadline: float) -> int:
    workflow = _request_json(
        api_url, repository, token, "GET", f"actions/workflows/{quote(workflow_path.rsplit('/', 1)[1])}",
        deadline_monotonic=deadline,
    )
    workflow_id = _positive_int(workflow.get("id")) if isinstance(workflow, dict) else None
    if not workflow_id or str(workflow.get("path") or "") != workflow_path:
        raise IncidentImportError("recovery_proof_workflow_identity_invalid")
    return workflow_id


def _verified_run(
    run_id: int, *, workflow_path: str, workflow_id: int, repository: str,
    api_url: str, token: str, deadline: float,
) -> dict[str, Any]:
    run = _request_json(api_url, repository, token, "GET", f"actions/runs/{run_id}", deadline_monotonic=deadline)
    head_repository = run.get("head_repository") if isinstance(run, dict) else None
    if (
        not isinstance(run, dict)
        or _positive_int(run.get("id")) != run_id
        or _positive_int(run.get("workflow_id")) != workflow_id
        or str(run.get("path") or "") != workflow_path
        or str(run.get("head_branch") or "") != "main"
        or not isinstance(head_repository, dict)
        or str(head_repository.get("full_name") or "").casefold() != repository.casefold()
        or _positive_int(head_repository.get("id")) != REPOSITORY_ID
        or _positive_int(run.get("run_attempt")) != 1
        or str(run.get("head_sha") or "").lower() != EXPECTED_BASELINE_SHA
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
        or _parse_time(run.get("created_at")) is None
        or _parse_time(run.get("updated_at")) is None
    ):
        raise IncidentImportError("recovery_proof_run_identity_or_terminal_invalid")
    return run


def _artifact_proof(run: dict[str, Any], *, repository: str, api_url: str, token: str, deadline: float) -> dict[str, Any]:
    run_id = _positive_int(run.get("id"))
    attempt = _positive_int(run.get("run_attempt"))
    expected_name = f"incident-reconciliation-state-{run_id}-attempt-{attempt}"
    listing = _request_json(
        api_url, repository, token, "GET", f"actions/runs/{run_id}/artifacts?per_page=100&page=1",
        deadline_monotonic=deadline,
    )
    artifacts = listing.get("artifacts") if isinstance(listing, dict) else None
    total = listing.get("total_count") if isinstance(listing, dict) else None
    matches = [item for item in artifacts if isinstance(item, dict) and item.get("name") == expected_name] if isinstance(artifacts, list) else []
    if not isinstance(artifacts, list) or not isinstance(total, int) or total != len(artifacts) or len(matches) != 1:
        raise IncidentImportError("recovery_proof_artifact_list_or_identity_invalid")
    artifact = matches[0]
    workflow_run = artifact.get("workflow_run")
    digest = str(artifact.get("digest") or "").lower()
    artifact_id = _positive_int(artifact.get("id"))
    if (
        not artifact_id or artifact.get("expired") is True
        or not isinstance(workflow_run, dict)
        or _positive_int(workflow_run.get("id")) != run_id
        or str(workflow_run.get("head_sha") or "").lower() != EXPECTED_BASELINE_SHA
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
    ):
        raise IncidentImportError("recovery_proof_artifact_binding_invalid")
    return {"artifact_id": artifact_id, "name": expected_name, "digest": digest}


def verify_1145_recovery(*, repository: str, api_url: str, token: str, deadline: float) -> dict[str, Any]:
    """Require two complete central artifacts plus the exact recovery health artifact."""
    try:
        central_workflow_id = _workflow_id(
            workflow_path=CENTRAL_WORKFLOW_PATH, repository=repository, api_url=api_url, token=token, deadline=deadline,
        )
        health_workflow_id = _workflow_id(
            workflow_path=HEALTH_WORKFLOW_PATH, repository=repository, api_url=api_url, token=token, deadline=deadline,
        )
        central_proofs: list[dict[str, Any]] = []
        central_results: dict[int, dict[str, Any]] = {}
        central_run_times: dict[int, datetime] = {}
        for run_id in (41295919714, 41296321112):
            run = _verified_run(
                run_id, workflow_path=CENTRAL_WORKFLOW_PATH, workflow_id=central_workflow_id,
                repository=repository, api_url=api_url, token=token, deadline=deadline,
            )
            result = _read_health_result(run=run, repository=repository, api_url=api_url, token=token, deadline=deadline)
            complete, reason, _ = _result_is_complete(result)
            if not complete or _has_unresolved_work(result):
                raise IncidentImportError(f"recovery_proof_central_result_incomplete:{reason or 'unprocessed_source_work'}")
            central_run_times[run_id] = _parse_time(run.get("created_at"))  # type: ignore[assignment]
            central_results[run_id] = result
            central_proofs.append({
                "run_id": run_id, "attempt": 1, "sha": EXPECTED_BASELINE_SHA,
                "artifact": _artifact_proof(run, repository=repository, api_url=api_url, token=token, deadline=deadline),
                "result_sha256": hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            })
        if not central_run_times[41295919714] or not central_run_times[41296321112] or central_run_times[41295919714] >= central_run_times[41296321112]:
            raise IncidentImportError("recovery_proof_central_run_order_invalid")
        health_run = _verified_run(
            41296353945, workflow_path=HEALTH_WORKFLOW_PATH, workflow_id=health_workflow_id,
            repository=repository, api_url=api_url, token=token, deadline=deadline,
        )
        health_result = _read_health_result(
            run=health_run, repository=repository, api_url=api_url, token=token, deadline=deadline,
        )
        latest_central = central_results[41296321112]
        healthy_run_count = _positive_int(health_result.get("healthy_run_count"))
        if (
            health_result.get("health_status") != "recovered"
            or healthy_run_count is None
            or healthy_run_count < 2
            or _positive_int(health_result.get("latest_central_run_id")) != 41296321112
            or 1145 not in {_positive_int(item) for item in health_result.get("recovered_issue_numbers", [])}
            or not central_results[41295919714]
            or not latest_central
        ):
            raise IncidentImportError("recovery_proof_health_result_invalid")
        health_proof = {
            "run_id": 41296353945, "attempt": 1, "sha": EXPECTED_BASELINE_SHA,
            "artifact": _artifact_proof(health_run, repository=repository, api_url=api_url, token=token, deadline=deadline),
            "result_sha256": hashlib.sha256(json.dumps(health_result, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        }
        return {
            "status": "verified",
            "issue_number": 1145,
            "central_runs": central_proofs,
            "health_run": health_proof,
            "verified_at": datetime.now(UTC).isoformat(),
        }
    except (IncidentImportError, LivenessAuditError, OSError, ValueError, KeyError, TypeError) as exc:
        return {"status": "unverified", "issue_number": 1145, "reason": str(exc)[:180]}


def _has_unresolved_work(result: dict[str, Any]) -> bool:
    for key in ("unprocessed_source_runs", "source_scan_holds", "pending_diagnostics"):
        value = result.get(key)
        if value is None:
            continue
        if isinstance(value, (list, dict, str)) and len(value) == 0:
            continue
        return True
    return False


def _recovery_verified(proof: dict[str, Any]) -> bool:
    return proof.get("status") == "verified" and proof.get("issue_number") == 1145


def _make_envelopes(
    issues: list[dict[str, Any]], *, repository: str, run_id: int, attempt: int, sha: str,
    observed_at: str, recovery_verified: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    evidence = [{"repository": repository, "workflow": IMPORT_WORKFLOW_PATH, "run_id": run_id, "attempt": attempt, "sha": sha}]
    envelopes: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    snapshotted_issue_numbers: set[int] = set()
    for issue in issues:
        number = _issue_number(issue)
        if number is None:
            continue
        title = str(issue.get("title") or "")
        body = str(issue.get("body") or "")
        marker = _issue_marker(body)
        incident_type, component = _incident_type(title, marker)
        root_cause = _root_cause(issue)
        lifecycle = _issue_lifecycle(issue, recovery_verified=recovery_verified)
        for identity in _affected_identities(issue, {}, number, marker):
            envelope = make_incident_envelope(
                incident_type=incident_type,
                component=component,
                root_cause=root_cause,
                impact_type="legacy_github_issue_impact",
                impact_identity=identity,
                impact={"identity": identity, "description": f"Imported Issue #{number}; lifecycle {lifecycle}"},
                evidence=evidence,
                observed_at=observed_at,
                first_detected_at=_time_field(_issue_date(body, "First failure", "First detected")),
                source_occurred_at=_time_field(_issue_date(body, "Source occurred at", "Source published at")),
                severity="critical" if any(term in root_cause.casefold() for term in CRITICAL_TERMS) else "high",
                lifecycle=lifecycle,
                evidence_integrity="partial",
                new_impact=False,
                generation=1,
                state_version=1,
                issue_numbers=[number],
                compatibility={
                    "adapter": "github-incident-issue-import-v1",
                    "legacy_marker": marker or "unknown",
                    "legacy_issue_state": str(issue.get("state") or "unknown"),
                    "preserved_as_missed_delivery": number == 1120,
                },
            )
            envelopes.append(envelope)
            if number not in snapshotted_issue_numbers:
                snapshots.append({
                    "issue_number": number,
                    "title": title[:240],
                    "state": str(issue.get("state") or "unknown"),
                    "created_at": str(issue.get("created_at") or "unknown"),
                    "updated_at": str(issue.get("updated_at") or "unknown"),
                    "closed_at": str(issue.get("closed_at") or ""),
                    "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                    "lifecycle_imported": lifecycle,
                })
                snapshotted_issue_numbers.add(number)
            if len(envelopes) > MAX_INCIDENTS:
                raise IncidentImportError("legacy_issue_envelope_limit_exceeded")
    return envelopes, snapshots


def _issue_date(body: str, *field_names: str) -> str:
    for name in field_names:
        values = [line.partition(":")[2].strip() for line in body.splitlines() if line.startswith(name + ":")]
        if len(values) == 1:
            return values[0]
    return ""


def build_snapshot(
    *, issues: list[dict[str, Any]], journal_issue: dict[str, Any], repository: str,
    import_run_id: int, import_attempt: int, import_sha: str, recovery_proof: dict[str, Any],
    observed_at: str | None = None,
) -> dict[str, Any]:
    if repository.casefold() != REPOSITORY.casefold() or not re.fullmatch(r"[0-9a-f]{40}", import_sha):
        raise IncidentImportError("legacy_import_identity_invalid")
    if _positive_int(import_run_id) is None or _positive_int(import_attempt) is None:
        raise IncidentImportError("legacy_import_run_identity_invalid")
    if not isinstance(journal_issue, dict) or str(journal_issue.get("title") or "") != CONTROL_ISSUE_TITLE:
        raise IncidentImportError("legacy_control_journal_identity_invalid")
    journal_body = str(journal_issue.get("body") or "")
    if journal_body.splitlines().count(CONTROL_MARKER) != 1:
        raise IncidentImportError("legacy_control_journal_marker_invalid")
    journal = _parse_journal_body(journal_body, repository=repository)
    windows = _confirmed_windows(journal)
    envelopes, issue_metadata = _make_envelopes(
        issues, repository=repository, run_id=import_run_id, attempt=import_attempt, sha=import_sha,
        observed_at=observed_at or datetime.now(UTC).isoformat(),
        recovery_verified=_recovery_verified(recovery_proof),
    )
    snapshot = {
        "schema_version": "incident-legacy-import-v1",
        "source_repository": repository,
        "source_repository_id": REPOSITORY_ID,
        "journal_generation": journal["generation"],
        "journal_body_sha256": hashlib.sha256(journal_body.encode("utf-8")).hexdigest(),
        "journal_body": journal_body,
        "journal": journal,
        "confirmed_windows": windows,
        "issues": issue_metadata,
        "recovery_proof_1145": recovery_proof,
        "incidents": [{"envelope": item, "suppress_notification": True} for item in envelopes],
        "imported_at": observed_at or datetime.now(UTC).isoformat(),
        "import_evidence": {
            "workflow": IMPORT_WORKFLOW_PATH,
            "run_id": import_run_id,
            "attempt": import_attempt,
            "sha": import_sha,
        },
    }
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_IMPORT_BYTES:
        raise IncidentImportError("legacy_import_snapshot_size_limit_exceeded")
    return snapshot


def _write_json(path: str, value: dict[str, Any]) -> None:
    target = os.path.abspath(path)
    parent = os.path.dirname(target)
    os.makedirs(parent, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".incident-import-", suffix=".tmp", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def import_legacy_state(*, environment: dict[str, str]) -> dict[str, Any]:
    if environment.get("CONFIRM_IMPORT", "").strip().lower() != "true":
        raise IncidentImportError("legacy_import_confirmation_required")
    repository = environment.get("GITHUB_REPOSITORY", "").strip()
    if repository.casefold() != REPOSITORY.casefold() or _positive_int(environment.get("GITHUB_REPOSITORY_ID")) != REPOSITORY_ID:
        raise IncidentImportError("legacy_import_repository_identity_invalid")
    run_id = _positive_int(environment.get("GITHUB_RUN_ID"))
    attempt = _positive_int(environment.get("GITHUB_RUN_ATTEMPT"))
    sha = str(environment.get("GITHUB_SHA") or "").lower()
    if not run_id or not attempt or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise IncidentImportError("legacy_import_workflow_identity_missing")
    api_url = environment.get("GITHUB_API_URL", "https://api.github.com")
    github_token = environment.get("GITHUB_TOKEN", "")
    if not github_token:
        raise IncidentImportError("github_read_token_missing")
    deadline = time.monotonic() + 120
    rows = _read_journal_issues(
        repository=repository, api_url=api_url, token=github_token, deadline=deadline,
    )
    control = [
        issue for issue in rows
        if str(issue.get("title") or "") == CONTROL_ISSUE_TITLE
        or CONTROL_MARKER in str(issue.get("body") or "").splitlines()
    ]
    if len(control) != 1 or str(control[0].get("title") or "") != CONTROL_ISSUE_TITLE:
        raise IncidentImportError("legacy_control_journal_not_unique")
    journal_issue = control[0]
    journal = _parse_journal_body(journal_issue.get("body"), repository=repository)
    proof = verify_1145_recovery(repository=repository, api_url=api_url, token=github_token, deadline=deadline)
    incident_issues = [issue for issue in rows if _issue_number(issue) is not None]
    snapshot = build_snapshot(
        issues=incident_issues, journal_issue=journal_issue, repository=repository,
        import_run_id=run_id, import_attempt=attempt, import_sha=sha, recovery_proof=proof,
    )
    snapshot_raw = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    snapshot_id = snapshot_identity(journal["generation"], str(journal_issue.get("body") or ""))
    snapshot_path = environment.get("INCIDENT_IMPORT_SNAPSHOT_PATH", "incident-legacy-import.json")
    _write_json(snapshot_path, {"source": "github-incident-notification-journal", "snapshot_id": snapshot_id, "snapshot": snapshot})
    base = environment.get("INCIDENT_OPS_URL", "")
    if not base:
        raise IncidentImportError("incident_ops_url_required")
    try:
        oidc = fetch_oidc_token(environment, audience=environment.get("INCIDENT_OPS_AUDIENCE", "https://prstk-incident-ops"))
        response = worker_post_json(base, "/ops/incidents/import", {
            "source": "github-incident-notification-journal",
            "snapshot_id": snapshot_id,
            "snapshot": snapshot,
        }, token=oidc)
    except IncidentOpsAuthError as exc:
        raise IncidentImportError(str(exc)) from exc
    if response.get("ok") is not True or response.get("snapshot_id") != snapshot_id:
        raise IncidentImportError("legacy_import_worker_ack_invalid")
    return {
        "status": "imported",
        "snapshot_id": snapshot_id,
        "snapshot_sha256": hashlib.sha256(snapshot_raw).hexdigest(),
        "confirmed_window_count": len(snapshot["confirmed_windows"]),
        "incident_count": len(snapshot["incidents"]),
        "recovery_1145": response.get("recovery_proof_1145", proof.get("status")),
        "worker_ack": {key: response.get(key) for key in ("ok", "idempotent", "confirmed_windows_imported", "incidents_imported", "content_sha256")},
    }


def main() -> int:
    result_path = os.environ.get("INCIDENT_IMPORT_RESULT_PATH", "incident-legacy-import-result.json")
    try:
        result = import_legacy_state(environment=dict(os.environ))
    except (IncidentImportError, IncidentOpsAuthError, LivenessAuditError, OSError, ValueError) as exc:
        print(f"incident_ops_import_failed:{str(exc)[:180]}", file=sys.stderr)
        try:
            _write_json(result_path, {
                "status": "failed", "failure_reason": str(exc)[:180],
                "observed_at": datetime.now(UTC).isoformat(),
            })
        except OSError as write_error:
            print(f"incident_ops_import_result_preservation_failed:{type(write_error).__name__}", file=sys.stderr)
        return 1
    _write_json(result_path, result)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write("## One-time legacy incident state import\n\n")
            summary.write(f"- snapshot: `{result['snapshot_id']}`\n")
            summary.write(f"- confirmed windows: {result['confirmed_window_count']}\n")
            summary.write(f"- incident impacts: {result['incident_count']}\n")
            summary.write(f"- #1145 recovery proof: {result['recovery_1145']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
