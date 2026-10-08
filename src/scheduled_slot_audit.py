"""Read-only receipt audit for all four scheduled notification anchors."""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import time as time_module
import zipfile
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from datetime import time as day_time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from src.schedule_contract import NEW_YORK, TAIPEI, fixed_scheduled_for, scheduled_anchor_key
from src.scheduled_recipient_manifest import RecipientManifest, parse_recipient_manifest, recipient_set_version
from src.workflow_execution_diagnostics import classify_workflow_execution

SCHEDULE_TO_SLOT = {
    "45 22 * * *": "morning",
    "30 1 * * 1-5": "pre_open",
    "5 7 * * 1-5": "post_close",
    "45 13 * * 1-5": "us_premarket",
    "45 14 * * 1-5": "us_premarket",
}


class _ArtifactRedirectHandler(HTTPRedirectHandler):
    """Strip GitHub credentials before following a signed artifact redirect."""

    max_redirections = 3
    max_repeats = 1

    def redirect_request(self, request, response, code, message, headers, new_url):
        source = urlparse(request.full_url)
        target = urlparse(new_url)
        artifact_endpoint = re.fullmatch(
            r"/repos/[^/]+/[^/]+/actions/(?:artifacts/\d+/zip|runs/\d+/logs)",
            source.path,
        )
        artifact_host = re.fullmatch(r"productionresultssa\d+\.blob\.core\.windows\.net", target.hostname or "")
        if (
            source.scheme != "https" or source.hostname != "api.github.com"
            or not artifact_endpoint or target.scheme != "https" or not artifact_host
            or target.username or target.password or target.fragment
        ):
            raise URLError("artifact_redirect_destination_rejected")
        redirected = super().redirect_request(request, response, code, message, headers, new_url)
        if redirected is not None:
            for name in ("Authorization", "Cookie", "Proxy-Authorization", "X-GitHub-Api-Version"):
                redirected.remove_header(name)
        return redirected


def _open_artifact_url(request: Request, *, timeout: int):
    """Use the constrained redirect policy for artifact/log API downloads."""
    return build_opener(_ArtifactRedirectHandler()).open(request, timeout=timeout)


def _candidate_occurrence(schedule: str, reference: datetime) -> datetime | None:
    """Return the most recent UTC occurrence represented by this exact cron."""
    slot = SCHEDULE_TO_SLOT.get(str(schedule or "").strip())
    if slot is None:
        return None
    current = reference.astimezone(UTC)
    try:
        hour_text, minute_text = schedule.split()[1], schedule.split()[0]
        hour, minute = int(hour_text), int(minute_text)
    except (IndexError, TypeError, ValueError):
        return None
    for offset in range(8):
        day = current.date() - timedelta(days=offset)
        if schedule.endswith("1-5") and day.weekday() >= 5:
            continue
        candidate = datetime.combine(day, day_time(hour, minute), UTC)
        if candidate <= current:
            return candidate
    return None


def _candidate_slot(schedule: str, occurrence: datetime) -> tuple[str, datetime] | None:
    slot = SCHEDULE_TO_SLOT.get(schedule)
    if slot is None:
        return None
    if slot == "us_premarket":
        local = occurrence.astimezone(NEW_YORK)
        if local.hour != 9 or local.minute != 45:
            return None
        return slot, local
    local = occurrence.astimezone(TAIPEI)
    expected = {"morning": (6, 45), "pre_open": (9, 30), "post_close": (15, 5)}[slot]
    if (local.hour, local.minute) != expected:
        return None
    return slot, local


def _load_ledger(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("scheduled_receipt_ledger_invalid") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("delivery_claims"), dict):
        raise ValueError("scheduled_receipt_ledger_invalid")
    return payload


def _calendar_snapshot(slot: str, day: datetime) -> dict[str, Any]:
    """Build calendar evidence with independent TWSE and TAIFEX sources."""
    from src.market_data import get_market_status
    from src.taifex_calendar import get_taifex_index_futures_status

    target = day.date()
    if slot == "us_premarket":
        return {"markets": {"us": get_market_status("us", target)}}
    cash = get_market_status("taiwan", target)
    cash["calendar_provider"] = "pandas_market_calendars"
    futures = get_taifex_index_futures_status(target, now=day)
    return {"markets": {"taiwan_cash": cash, "taiwan_futures": futures}}


def _receipt_result(
    payload: dict[str, Any], *, anchor: str, slot_date: str,
    expected_recipient_hashes: set[str] | None,
) -> dict[str, Any]:
    claims = payload["delivery_claims"]
    claim = claims.get(f"scheduled-anchor:{anchor}")
    base = {"market_date": slot_date, "anchor": anchor, "read_only": True}
    if not isinstance(claim, dict):
        return {"status": "missing_receipt", "reason": "scheduled_anchor_claim_missing", **base}
    configured = {str(value) for value in claim.get("recipient_hashes", []) if str(value)}
    delivered = {str(value) for value in claim.get("delivered_recipient_hashes", []) if str(value)}
    if claim.get("kind") != "scheduled_brief" or claim.get("anchor_key") != anchor:
        return {"status": "blocked", "reason": "scheduled_anchor_claim_identity_mismatch", **base}
    if not expected_recipient_hashes:
        return {"status": "blocked", "reason": "expected_recipient_set_unavailable", **base}
    if configured != expected_recipient_hashes:
        return {
            "status": "incomplete_receipt", "reason": "scheduled_anchor_recipient_set_mismatch",
            "recipient_count": len(expected_recipient_hashes),
            "configured_count": len(configured),
            "delivered_count": len(configured & delivered), **base,
        }
    failed = {str(value) for value in claim.get("failed_recipient_hashes", []) if str(value)}
    if claim.get("status") != "delivered" or not configured or not configured.issubset(delivered) or failed:
        return {
            "status": "incomplete_receipt", "reason": "scheduled_anchor_recipients_not_fully_delivered",
            "recipient_count": len(expected_recipient_hashes),
            "delivered_count": len(expected_recipient_hashes & delivered), **base,
        }
    return {
        "status": "delivered", "reason": "durable_recipient_receipt_verified",
        "recipient_count": len(expected_recipient_hashes), "delivered_count": len(expected_recipient_hashes), **base,
    }


def _expected_recipient_manifest_from_env() -> tuple[set[str], str, str, str]:
    """Read one atomic, content-addressed recipient manifest; never inspect sender IDs."""
    raw_manifest = os.getenv("SCHEDULED_RECIPIENT_SET_MANIFEST", "")
    try:
        manifest = parse_recipient_manifest(raw_manifest)
    except ValueError as exc:
        return set(), "", "", str(exc)
    return set(manifest.recipient_hashes), manifest.version, manifest.effective_at, ""


def _expected_recipient_hashes_from_env() -> set[str]:
    """Compatibility helper for callers that need only the manifest hash set."""
    return _expected_recipient_manifest_from_env()[0]


def _recipient_set_metadata_error(
    version: str,
    effective_at: str,
    slot_anchor: datetime,
    recipient_hashes: set[str],
) -> tuple[str, str]:
    """Validate the independently maintained, content-addressed recipient-set identity."""
    normalized_version = str(version or "").strip()
    if not normalized_version:
        return "expected_recipient_set_version_unavailable", "unknown"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", normalized_version):
        return "expected_recipient_set_version_invalid", "unknown"
    raw_effective = str(effective_at or "").strip()
    if not raw_effective:
        return "expected_recipient_set_effective_at_unavailable", "unknown"
    if not recipient_hashes or any(not re.fullmatch(r"[0-9a-f]{12}", str(value)) for value in recipient_hashes):
        return "expected_recipient_set_hashes_unavailable", "unknown"
    try:
        parsed = datetime.fromisoformat(raw_effective.replace("Z", "+00:00"))
    except ValueError:
        return "expected_recipient_set_effective_at_invalid", "unknown"
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return "expected_recipient_set_effective_at_invalid", "unknown"
    effective_utc = parsed.astimezone(UTC)
    normalized_effective = effective_utc.isoformat().replace("+00:00", "Z")
    if effective_utc > slot_anchor.astimezone(UTC):
        return "expected_recipient_set_not_effective_for_slot", normalized_effective
    try:
        expected_version = recipient_set_version(recipient_hashes, normalized_effective)
    except (TypeError, ValueError):
        return "expected_recipient_set_fingerprint_invalid", normalized_effective
    if normalized_version != expected_version:
        return "expected_recipient_set_fingerprint_mismatch", normalized_effective
    return "", normalized_effective


def _terminal_records_from_logs(body: bytes) -> list[dict[str, Any]]:
    """Extract bounded v1/v2 terminal rows from logs or a run-bound artifact."""
    if len(body) > 20 * 1024 * 1024:
        raise ValueError("workflow_logs_too_large")
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        for member in archive.infolist():
            if not member.filename.endswith((".txt", ".json")) or member.file_size > 5 * 1024 * 1024:
                continue
            with archive.open(member) as handle:
                raw_content = handle.read(5 * 1024 * 1024 + 1)
                if len(raw_content) > 5 * 1024 * 1024:
                    continue
                raw_lines = raw_content.splitlines() if member.filename.endswith(".txt") else [raw_content]
                for raw_line in raw_lines:
                    try:
                        line = raw_line.decode("utf-8")
                        json_start = line.find("{")
                        row = json.loads(line[json_start:]) if json_start >= 0 else None
                    except (UnicodeError, json.JSONDecodeError):
                        continue
                    if (
                        isinstance(row, dict)
                        and row.get("schema_version") in {
                            "notification-terminal-v1", "notification-terminal-v2",
                        }
                        and row.get("workflow") == "scheduled"
                    ):
                        key = tuple(str(row.get(field) or "") for field in (
                            "schema_version", "run_id", "workflow_sha", "slot",
                            "scheduled_for_at", "status", "reason",
                        ))
                        if key in seen:
                            continue
                        seen.add(key)
                        records.append(row)
                        if len(records) >= 20:
                            return records
    return records


def _diagnose_scheduled_run(
    *, repository: str, token: str, slot: str, anchor_local: datetime, now: datetime,
    opener: Any = urlopen,
) -> dict[str, Any]:
    """Read matching Actions terminal evidence; this function cannot dispatch or resend."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or not token:
        return {"status": "unavailable", "reason": "github_read_credentials_missing", "no_resend": True}
    anchor_utc = anchor_local.astimezone(UTC)
    current = now.astimezone(UTC)
    lower_bound = max(anchor_utc - timedelta(minutes=15), current - timedelta(hours=72))
    query = urlencode({
        "branch": "main",
        "created": f"{lower_bound.date().isoformat()}..{current.date().isoformat()}",
    })
    base = f"https://api.github.com/repos/{repository}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    def get(url: str, *, limit: int) -> bytes:
        request = Request(url, headers=headers)
        parsed_url = urlparse(url)
        is_github_artifact = bool(re.fullmatch(
            r"/repos/[^/]+/[^/]+/actions/(?:artifacts/\d+/zip|runs/\d+/logs)",
            parsed_url.path,
        ))
        open_response = (
            _open_artifact_url
            if opener is urlopen and is_github_artifact
            else opener
        )
        with open_response(request, timeout=15) as response:
            body = response.read(limit + 1)
        if len(body) > limit:
            raise ValueError("github_response_too_large")
        return body

    def get_collection(
        endpoint: str, *, collection_key: str, limit: int,
    ) -> list[dict[str, Any]]:
        """Read a complete, stable, bounded GitHub collection or fail closed."""
        rows: list[dict[str, Any]] = []
        seen_ids: set[int] = set()
        expected_total: int | None = None
        for page in range(1, 11):
            separator = "&" if "?" in endpoint else "?"
            url = f"{endpoint}{separator}per_page=100&page={page}"
            payload = json.loads(get(url, limit=limit).decode("utf-8"))
            page_rows = payload.get(collection_key) if isinstance(payload, dict) else None
            total = payload.get("total_count") if isinstance(payload, dict) else None
            if (
                not isinstance(page_rows, list)
                or not isinstance(total, int)
                or total < 0
                or (expected_total is not None and total != expected_total)
            ):
                raise ValueError("github_collection_identity_or_count_invalid")
            expected_total = total
            for row in page_rows:
                if not isinstance(row, dict) or not isinstance(row.get("id"), int):
                    raise ValueError("github_collection_row_identity_invalid")
                row_id = row["id"]
                if row_id in seen_ids:
                    raise ValueError("github_collection_changed_during_pagination")
                seen_ids.add(row_id)
                rows.append(row)
            if len(rows) > expected_total:
                raise ValueError("github_collection_count_overflow")
            if len(rows) == expected_total:
                return rows
        raise ValueError("github_collection_pagination_incomplete")

    def terminal_rows_for_run(run: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Prefer the exact run/attempt artifact; use bounded historical logs otherwise."""
        run_id = run.get("id")
        if not isinstance(run_id, int):
            return []
        attempt = str(run.get("run_attempt") or "1")
        expected_name = f"scheduled-terminal-{run_id}-attempt-{attempt}"
        try:
            artifacts = get_collection(
                f"{base}/actions/runs/{run_id}/artifacts",
                collection_key="artifacts",
                limit=2 * 1024 * 1024,
            )
        except (HTTPError, URLError, OSError, UnicodeError, json.JSONDecodeError, ValueError):
            artifacts = []
        matching = [item for item in artifacts if item.get("name") == expected_name]
        if len(matching) > 1:
            raise ValueError("workflow_terminal_artifact_ambiguous")
        if matching:
            artifact = matching[0]
            artifact_id = artifact.get("id")
            workflow_run = artifact.get("workflow_run")
            if (
                not isinstance(artifact_id, int)
                or artifact.get("expired") is True
                or (isinstance(workflow_run, dict) and workflow_run.get("id") != run_id)
            ):
                raise ValueError("workflow_terminal_artifact_identity_invalid")
            body = get(f"{base}/actions/artifacts/{artifact_id}/zip", limit=20 * 1024 * 1024)
            rows = _terminal_records_from_logs(body)
            head_sha = str(run.get("head_sha") or "")
            attempt = str(run.get("run_attempt") or "1")
            if not any(
                str(row.get("run_id") or "") == str(run_id)
                and str(row.get("workflow_sha") or "") == head_sha
                and str(row.get("run_attempt") or "1") == attempt
                for row in rows
            ):
                raise ValueError("workflow_terminal_artifact_payload_identity_invalid")
            return rows
        return _terminal_records_from_logs(
            get(f"{base}/actions/runs/{run_id}/logs", limit=20 * 1024 * 1024),
        )

    def execution_diagnostic(run: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
        """Read the exact run's complete jobs and, when needed, runner annotations."""
        run_id_value = run.get("id")
        if not isinstance(run_id_value, int):
            return {"classification": "unknown", "reason": "workflow_run_id_invalid"}, "unavailable"
        try:
            jobs = get_collection(
                f"{base}/actions/runs/{run_id_value}/jobs",
                collection_key="jobs",
                limit=4 * 1024 * 1024,
            )
        except (HTTPError, URLError, OSError, UnicodeError, json.JSONDecodeError, ValueError):
            return {"classification": "unknown", "reason": "workflow_jobs_unavailable_or_incomplete"}, "unavailable"
        diagnostic = classify_workflow_execution(run, jobs)
        if diagnostic.get("classification") != "pre_step_failure_unclassified":
            return diagnostic, "not_required"
        check_suite_id = run.get("check_suite_id")
        if not isinstance(check_suite_id, int) or check_suite_id <= 0:
            return diagnostic, "unavailable"
        try:
            checks = get_collection(
                f"{base}/check-suites/{check_suite_id}/check-runs",
                collection_key="check_runs",
                limit=4 * 1024 * 1024,
            )
            annotations: list[dict[str, Any]] = []
            for check in checks:
                if not isinstance(check, dict) or not isinstance(check.get("id"), int):
                    continue
                raw_output = check.get("output")
                output = raw_output if isinstance(raw_output, dict) else {}
                expected_annotations = output.get("annotations_count", 0)
                if not isinstance(expected_annotations, int) or expected_annotations < 0:
                    return diagnostic, "invalid_count"
                check_annotations: list[dict[str, Any]] = []
                for page in range(1, min(20, (expected_annotations + 99) // 100) + 1):
                    page_rows = json.loads(get(
                        f"{base}/check-runs/{check['id']}/annotations?per_page=100&page={page}",
                        limit=2 * 1024 * 1024,
                    ).decode("utf-8"))
                    if not isinstance(page_rows, list):
                        return diagnostic, "invalid_response"
                    check_annotations.extend(row for row in page_rows if isinstance(row, dict))
                    if not page_rows:
                        break
                if len(check_annotations) != expected_annotations:
                    return diagnostic, "incomplete"
                annotations.extend(check_annotations)
            return classify_workflow_execution(run, jobs, annotations), "available"
        except (HTTPError, URLError, OSError, UnicodeError, json.JSONDecodeError, ValueError):
            return diagnostic, "unavailable"

    try:
        runs = get_collection(
            f"{base}/actions/workflows/scheduled-brief.yml/runs?{query}",
            collection_key="workflow_runs",
            limit=2 * 1024 * 1024,
        )
        candidates: list[dict[str, Any]] = []
        for run in runs:
            if not isinstance(run, dict) or run.get("path") != ".github/workflows/scheduled-brief.yml":
                continue
            created_at = run.get("created_at")
            try:
                created = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
            except ValueError:
                continue
            if created.tzinfo is None or created.utcoffset() is None:
                continue
            if lower_bound <= created.astimezone(UTC) <= current + timedelta(minutes=5):
                candidates.append(run)
        if len(candidates) > 50:
            return {"status": "unavailable", "reason": "too_many_candidate_runs", "no_resend": True}

        matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for run in candidates:
            run_id = run.get("id")
            if not isinstance(run_id, int):
                continue
            for terminal in terminal_rows_for_run(run):
                try:
                    terminal_anchor = datetime.fromisoformat(
                        str(terminal.get("scheduled_for_at") or "").replace("Z", "+00:00")
                    )
                except ValueError:
                    continue
                if (
                    terminal.get("slot") == slot
                    and terminal_anchor.tzinfo is not None
                    and terminal_anchor.astimezone(UTC) == anchor_utc
                    and str(terminal.get("run_id") or "") == str(run_id)
                    and str(terminal.get("workflow_sha") or "") == str(run.get("head_sha") or "")
                    and str(terminal.get("run_attempt") or run.get("run_attempt") or "1") == str(run.get("run_attempt") or "1")
                ):
                    matches.append((run, terminal))
        scheduled_matches = [item for item in matches if item[0].get("event") == "schedule"]
        selected_matches = scheduled_matches or [
            item for item in matches if item[0].get("event") == "repository_dispatch"
        ]
        if len(selected_matches) != 1:
            return {
                "status": "ambiguous" if len(selected_matches) > 1 else "not_found",
                "reason": "scheduled_terminal_not_unique",
                "candidate_run_count": len(candidates),
                "matching_terminal_count": len(matches),
                "no_resend": True,
            }
        run, terminal = selected_matches[0]
        execution, annotation_evidence_status = execution_diagnostic(run)
        stages_value = terminal.get("stages")
        stages: dict[str, Any] = stages_value if isinstance(stages_value, dict) else {}
        status_raw = str(terminal.get("status") or "unknown")
        reason_raw = str(terminal.get("reason") or "unknown")
        status = status_raw[:80] if re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", status_raw) else "untrusted_terminal_status"
        reason = reason_raw[:160] if re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", reason_raw) else "untrusted_terminal_reason"
        durable = terminal.get("durable_receipt_verified") is True
        terminal_no_resend = terminal.get("no_resend") is True
        head_sha = str(run.get("head_sha") or "")
        result = {
            "status": "matched",
            "reason": "exact_slot_terminal_found",
            "run_id": run.get("id"),
            "workflow_sha": head_sha if re.fullmatch(r"[0-9a-fA-F]{40}", head_sha) else "unknown",
            "run_url": f"https://github.com/{repository}/actions/runs/{run_id}",
            "run_conclusion": str(run.get("conclusion") or run.get("status") or "unknown")[:40],
            "terminal_status": status,
            "terminal_reason": reason,
            "execution_diagnostic": execution,
            "annotation_evidence_status": annotation_evidence_status,
            "expected": terminal.get("expected") is True,
            "sender_status": str(terminal.get("sender_status") or "unknown")[:80],
            "receipt_status": str(terminal.get("receipt_status") or "unknown")[:80],
            "durable_receipt_verified": durable,
            "no_resend": terminal_no_resend or status in {
                "delivered", "delivered_reconciliation_incomplete",
            },
            "stages": {
                key: str(stages.get(key) or "unknown")[:80]
                for key in ("writer_queue", "prepare", "deployment", "public_gate", "sender", "receipt", "ledger")
            },
        }
        if status in {"delivered", "delivered_reconciliation_incomplete"} and not durable:
            result["status"] = "receipt_ledger_conflict_no_resend"
            result["reason"] = "run_terminal_claims_delivery_without_verified_ledger_receipt"
            result["no_resend"] = True
        return result
    except (HTTPError, URLError, OSError, UnicodeError, json.JSONDecodeError, ValueError, zipfile.BadZipFile) as exc:
        return {
            "status": "unavailable",
            "reason": f"github_run_diagnosis_unavailable_{type(exc).__name__}",
            "no_resend": True,
        }


def _external_slot_anchor(
    *, slot: str, slot_date: str, scheduled_for_at: str, dispatch_unix: str = "",
) -> tuple[str, datetime] | None:
    if slot not in {"morning", "pre_open", "post_close", "us_premarket"}:
        return None
    try:
        if not slot_date and dispatch_unix:
            dispatch_time = datetime.fromtimestamp(int(dispatch_unix), tz=UTC)
            local_zone = NEW_YORK if slot == "us_premarket" else TAIPEI
            slot_date = dispatch_time.astimezone(local_zone).date().isoformat()
        if not slot_date:
            return None
        day = datetime.fromisoformat(f"{slot_date}T00:00:00").date()
        if slot == "us_premarket":
            # The pre-install timing gate uses only the nominal NY local
            # anchor. The exchange calendar is checked later by audit_slot,
            # after the workflow has installed its declared dependencies.
            expected = datetime.combine(day, day_time(9, 0), tzinfo=NEW_YORK)
        else:
            taiwan_anchors = {
                "morning": day_time(6, 0),
                "pre_open": day_time(8, 45),
                "post_close": day_time(14, 20),
            }
            expected_time = taiwan_anchors.get(slot)
            if expected_time is None:
                return None
            expected = datetime.combine(day, expected_time, tzinfo=TAIPEI)
        declared = (
            datetime.fromisoformat(str(scheduled_for_at).replace("Z", "+00:00"))
            if scheduled_for_at else expected
        )
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    if declared.tzinfo is None or declared.utcoffset() is None:
        return None
    if declared.astimezone(expected.tzinfo) != expected:
        return None
    if dispatch_unix:
        try:
            dispatched = datetime.fromtimestamp(int(dispatch_unix), tz=expected.tzinfo)
        except (TypeError, ValueError, OverflowError, OSError):
            return None
        if dispatched.date().isoformat() != slot_date:
            return None
    return slot, expected


def _parse_requested_at(value: str) -> datetime | None:
    text = str(value or "").strip()
    if text.isdigit():
        try:
            return datetime.fromtimestamp(int(text), tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def external_audit_timing(
    *, slot: str, slot_date: str, scheduled_for_at: str,
    dispatch_unix: str, requested_at: str, now: datetime,
) -> dict[str, Any]:
    """Validate external clock skew and state how long a read-only audit must wait."""
    selected = _external_slot_anchor(
        slot=slot,
        slot_date=slot_date,
        scheduled_for_at=scheduled_for_at,
        dispatch_unix=dispatch_unix,
    )
    if selected is None:
        return {"status": "blocked", "reason": "external_audit_slot_identity_invalid"}
    resolved_slot, anchor = selected
    requested = _parse_requested_at(requested_at)
    if requested is None:
        return {"status": "blocked", "reason": "external_audit_requested_at_invalid"}
    due = anchor + timedelta(minutes=45)
    skew = (requested.astimezone(UTC) - due.astimezone(UTC)).total_seconds()
    if skew < -120:
        return {
            "status": "blocked", "reason": "external_audit_requested_too_early",
            "slot": resolved_slot, "audit_due_at": due.isoformat(),
            "requested_at": requested.isoformat(), "clock_skew_seconds": int(skew),
        }
    current = now.astimezone(UTC)
    if requested.astimezone(UTC) > current + timedelta(minutes=5):
        return {"status": "blocked", "reason": "external_audit_requested_at_in_future"}
    wait_seconds = max(0, int((due.astimezone(UTC) - current).total_seconds() + 0.999))
    if wait_seconds > 120:
        return {
            "status": "blocked", "reason": "external_audit_wait_exceeds_tolerance",
            "slot": resolved_slot, "audit_due_at": due.isoformat(),
            "requested_at": requested.isoformat(), "clock_skew_seconds": int(skew),
        }
    return {
        "status": "ready", "reason": "external_audit_time_valid",
        "slot": resolved_slot, "audit_due_at": due.isoformat(),
        "requested_at": requested.isoformat(), "clock_skew_seconds": int(skew),
        "wait_seconds": wait_seconds,
    }


def audit_slot(
    *,
    ledger_path: Path,
    schedule: str,
    now: datetime,
    run_created_at: datetime | str | None = None,
    expected_recipient_hashes: set[str] | None = None,
    ledger_source: str = "data-release",
    ledger_commit_sha: str = "",
    trigger_source: str = "github_schedule",
    audit_started_at: str = "",
    external_slot: str = "",
    external_slot_date: str = "",
    external_scheduled_for_at: str = "",
    external_requested_at: str = "",
    external_dispatch_unix: str = "",
    expected_recipient_set_version: str = "",
    expected_recipient_set_effective_at: str = "",
    require_recipient_set_metadata: bool = False,
    expected_recipient_set_manifest_error: str = "",
    recipient_manifest: RecipientManifest | None = None,
    github_repository: str = "",
    github_token: str = "",
) -> dict[str, Any]:
    """Audit the immutable scheduled occurrence; never mutate or resend."""
    source_fields = {
        "read_only": True,
        "ledger_source": ledger_source,
        "ledger_commit_sha": ledger_commit_sha if re.fullmatch(r"[0-9a-fA-F]{40}", ledger_commit_sha) else "unknown",
        "audit_started_at": audit_started_at,
        "trigger_source": trigger_source,
        "recipient_set_version": "unknown",
        "recipient_set_effective_at": "unknown",
    }
    if external_slot or external_slot_date or external_scheduled_for_at:
        selected = _external_slot_anchor(
            slot=external_slot,
            slot_date=external_slot_date,
            scheduled_for_at=external_scheduled_for_at,
            dispatch_unix=external_dispatch_unix,
        )
        if selected is None:
            return {"status": "blocked", "reason": "external_audit_slot_identity_invalid", **source_fields}
        slot, anchor_local = selected
        if not external_requested_at:
            return {"status": "blocked", "reason": "external_audit_requested_at_missing", **source_fields}
        requested_at = _parse_requested_at(external_requested_at)
        if requested_at is None:
            return {"status": "blocked", "reason": "external_audit_requested_at_invalid", **source_fields}
        timing = external_audit_timing(
            slot=slot,
            slot_date=anchor_local.date().isoformat(),
            scheduled_for_at=anchor_local.isoformat(),
            dispatch_unix=external_dispatch_unix,
            requested_at=external_requested_at,
            now=now,
        )
        if timing.get("status") != "ready":
            return {"status": "blocked", "reason": timing.get("reason"), **source_fields}
        source_fields.update({
            "external_requested_at": timing["requested_at"],
            "external_clock_skew_seconds": timing["clock_skew_seconds"],
            "audit_due_at": timing["audit_due_at"],
        })
        request_utc = requested_at.astimezone(UTC)
        if request_utc > now.astimezone(UTC) + timedelta(minutes=5):
            return {"status": "blocked", "reason": "external_audit_requested_at_in_future", **source_fields}
        request_age_limit = timedelta(hours=72) if external_slot_date else timedelta(hours=12)
        if now.astimezone(UTC) - request_utc > request_age_limit:
            return {"status": "blocked", "reason": "external_audit_request_expired", **source_fields}
        if now.astimezone(UTC) < datetime.fromisoformat(str(timing["audit_due_at"])).astimezone(UTC):
            return {
                "status": "not_due", "reason": "audit_deadline_not_passed",
                "slot": slot, "wait_seconds": timing["wait_seconds"], **source_fields,
            }
        slot_date = anchor_local.date().isoformat()
        anchor = scheduled_anchor_key(slot, slot_date)
        selection = (slot, anchor_local)
    else:
        selection = None
    reference: datetime | None
    if isinstance(run_created_at, datetime):
        reference = run_created_at
    elif isinstance(run_created_at, str):
        try:
            reference = datetime.fromisoformat(run_created_at.replace("Z", "+00:00"))
        except ValueError:
            return {"status": "blocked", "reason": "workflow_run_created_at_invalid", **source_fields}
    else:
        reference = None
    if selection is None and reference is None:
        reference = now
    if selection is None:
        if not isinstance(reference, datetime) or reference.tzinfo is None or reference.utcoffset() is None:
            return {"status": "blocked", "reason": "workflow_run_created_at_invalid", **source_fields}
        occurrence = _candidate_occurrence(schedule, reference)
        selection = _candidate_slot(schedule, occurrence) if occurrence else None
    if selection is None:
        return {
            "status": "not_applicable", "reason": "schedule_candidate_not_applicable",
            "receipt_verified": False, **source_fields,
        }
    slot, anchor_local = selection
    current = now.astimezone(UTC)
    slot_date = anchor_local.date().isoformat()
    try:
        original_slot_anchor = fixed_scheduled_for(slot, slot_date)
    except ValueError as exc:
        if slot != "us_premarket" or str(exc) != "market_closed":
            return {
                "status": "blocked", "reason": "original_slot_anchor_unavailable",
                "slot": slot, "market_date": slot_date, **source_fields,
            }
        original_slot_anchor = datetime.fromisoformat(f"{slot_date}T09:00:00").replace(tzinfo=NEW_YORK)
    audit_due_at = original_slot_anchor + timedelta(minutes=45)
    source_fields["audit_due_at"] = audit_due_at.isoformat()
    source_fields["scheduled_slot_at"] = original_slot_anchor.isoformat()
    source_fields["audit_delay_seconds"] = max(
        0, int((current - audit_due_at.astimezone(UTC)).total_seconds()),
    )
    if current < audit_due_at.astimezone(UTC):
        return {"status": "not_due", "reason": "audit_deadline_not_passed", "slot": slot, **source_fields}
    slot_date = anchor_local.date().isoformat()
    anchor = scheduled_anchor_key(slot, slot_date)
    try:
        from src.scheduled_delivery import _resolve_delivery_obligation

        snapshot = _calendar_snapshot(slot, anchor_local)
        obligation, policy_reason, _states = _resolve_delivery_obligation(
            snapshot,
            slot,
            {
                "slot_date": slot_date,
                "delivery_intent": "notify_candidate",
                "resolution_reason": "scheduled_receipt_audit",
                "contract_status": "valid",
            },
            notification_requested=True,
        )
    except Exception as exc:
        return {
            "status": "blocked", "reason": f"market_calendar_unavailable_{type(exc).__name__}",
            "slot": slot, "market_date": slot_date, "anchor": anchor, **source_fields,
        }
    if obligation == "expected_skip":
        return {
            "status": "expected_skip", "reason": policy_reason, "slot": slot,
            "obligation": obligation, "market_date": slot_date, "anchor": anchor, **source_fields,
        }
    if obligation == "blocked":
        return {
            "status": "blocked", "reason": policy_reason, "slot": slot,
            "obligation": obligation, "market_date": slot_date, "anchor": anchor, **source_fields,
        }
    if recipient_manifest is not None:
        selected_recipient_set = recipient_manifest.for_anchor(original_slot_anchor)
        if selected_recipient_set is None:
            expected_recipient_set_manifest_error = "expected_recipient_set_not_effective_for_slot"
        else:
            expected_recipient_hashes = set(selected_recipient_set.recipient_hashes)
            expected_recipient_set_version = selected_recipient_set.version
            expected_recipient_set_effective_at = selected_recipient_set.effective_at
    metadata_error, effective_label = _recipient_set_metadata_error(
        expected_recipient_set_version,
        expected_recipient_set_effective_at,
        original_slot_anchor,
        expected_recipient_hashes or set(),
    )
    if expected_recipient_set_manifest_error:
        metadata_error = expected_recipient_set_manifest_error
    normalized_version = str(expected_recipient_set_version or "").strip()
    source_fields["recipient_set_version"] = (
        normalized_version
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", normalized_version)
        else "unknown"
    )
    source_fields["recipient_set_effective_at"] = effective_label
    if require_recipient_set_metadata and metadata_error:
        blocked_result: dict[str, Any] = {
            "status": "blocked", "reason": metadata_error, "slot": slot,
            "obligation": obligation, "market_date": slot_date, "anchor": anchor, **source_fields,
        }
        if github_repository and github_token:
            blocked_result["run_diagnosis"] = _diagnose_scheduled_run(
                repository=github_repository,
                token=github_token,
                slot=slot,
                anchor_local=anchor_local,
                now=now,
            )
        return blocked_result
    try:
        payload = _load_ledger(ledger_path)
    except (OSError, ValueError, UnicodeError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else f"scheduled_receipt_ledger_unavailable_{type(exc).__name__}"
        return {
            "status": "blocked", "reason": reason, "slot": slot, "obligation": obligation,
            "market_date": slot_date, "anchor": anchor, **source_fields,
        }
    result = _receipt_result(
        payload,
        anchor=anchor,
        slot_date=slot_date,
        expected_recipient_hashes=expected_recipient_hashes,
    )
    result.update({"slot": slot, "obligation": obligation, "policy_reason": policy_reason})
    result.update(source_fields)
    if result.get("status") in {"missing_receipt", "incomplete_receipt"} and github_repository and github_token:
        diagnosis = _diagnose_scheduled_run(
            repository=github_repository,
            token=github_token,
            slot=slot,
            anchor_local=anchor_local,
            now=now,
        )
        result["run_diagnosis"] = diagnosis
        if diagnosis.get("status") == "receipt_ledger_conflict_no_resend":
            result["reason"] = "run_terminal_claims_delivery_but_durable_ledger_receipt_missing_no_resend"
            result["no_resend"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only audit for scheduled notification receipts")
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--wait-until-due", action="store_true")
    parser.add_argument("--schedule", default=os.getenv("GITHUB_EVENT_SCHEDULE", ""))
    parser.add_argument("--run-created-at", default=os.getenv("RUN_CREATED_AT", ""))
    parser.add_argument("--ledger-source", default=os.getenv("LEDGER_SOURCE", "data-release"))
    parser.add_argument("--ledger-commit-sha", default=os.getenv("LEDGER_COMMIT_SHA", ""))
    parser.add_argument("--trigger-source", default=os.getenv("TRIGGER_SOURCE", "github_schedule"))
    parser.add_argument("--audit-started-at", default=os.getenv("AUDIT_STARTED_AT", ""))
    parser.add_argument("--slot", default=os.getenv("AUDIT_SLOT", ""))
    parser.add_argument("--slot-date", default=os.getenv("AUDIT_SLOT_DATE", ""))
    parser.add_argument("--scheduled-for-at", default=os.getenv("AUDIT_SCHEDULED_FOR_AT", ""))
    parser.add_argument("--requested-at", default=os.getenv("AUDIT_REQUESTED_AT", ""))
    parser.add_argument("--dispatch-unix", default=os.getenv("AUDIT_DISPATCH_UNIX", ""))
    parser.add_argument("--recipient-set-manifest", default=os.getenv("SCHEDULED_RECIPIENT_SET_MANIFEST", ""))
    parser.add_argument("--repository", default=os.getenv("GITHUB_REPOSITORY", ""))
    parser.add_argument("--github-token", default=os.getenv("GITHUB_TOKEN", ""))
    parser.add_argument("--now", help="UTC timestamp override for deterministic tests")
    args = parser.parse_args()
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(UTC)
    if args.wait_until_due:
        timing = external_audit_timing(
            slot=args.slot,
            slot_date=args.slot_date,
            scheduled_for_at=args.scheduled_for_at,
            dispatch_unix=args.dispatch_unix,
            requested_at=args.requested_at,
            now=now,
        )
        if timing.get("status") != "ready":
            print(f"::error::{timing.get('reason', 'external_audit_time_invalid')}")
            return 1
        wait_seconds = int(timing.get("wait_seconds") or 0)
        if not args.now and wait_seconds:
            due = datetime.fromisoformat(str(timing["audit_due_at"])).astimezone(UTC)
            time_module.sleep(wait_seconds)
            while datetime.now(UTC) < due:
                time_module.sleep(min(1.0, max(0.05, (due - datetime.now(UTC)).total_seconds())))
        actual_start = datetime.now(UTC) if not args.now else now.astimezone(UTC)
        if actual_start < datetime.fromisoformat(str(timing["audit_due_at"])).astimezone(UTC):
            print("::error::external_audit_not_due_after_wait")
            return 1
        output_path = os.environ.get("GITHUB_OUTPUT", "").strip()
        if output_path:
            with Path(output_path).open("a", encoding="utf-8") as output:
                output.write(f"audit_due_at={timing['audit_due_at']}\n")
                output.write(f"external_clock_skew_seconds={timing['clock_skew_seconds']}\n")
                output.write(f"actual_audit_ready_at={actual_start.isoformat()}\n")
                output.write(f"waited_seconds={wait_seconds}\n")
        print(json.dumps({**timing, "actual_audit_ready_at": actual_start.isoformat()}, sort_keys=True))
        return 0
    if args.ledger is None:
        parser.error("--ledger is required unless --wait-until-due is used")
    try:
        recipient_manifest = parse_recipient_manifest(args.recipient_set_manifest)
        expected_recipient_hashes = set(recipient_manifest.latest.recipient_hashes)
        recipient_set_version_value = recipient_manifest.latest.version
        recipient_set_effective_at = recipient_manifest.latest.effective_at
        recipient_manifest_error = ""
    except ValueError as exc:
        recipient_manifest = None
        expected_recipient_hashes = set()
        recipient_set_version_value = ""
        recipient_set_effective_at = ""
        recipient_manifest_error = str(exc)
    result = audit_slot(
        ledger_path=args.ledger,
        schedule=args.schedule,
        now=now,
        run_created_at=args.run_created_at or None,
        expected_recipient_hashes=expected_recipient_hashes,
        ledger_source=args.ledger_source,
        ledger_commit_sha=args.ledger_commit_sha,
        trigger_source=args.trigger_source,
        audit_started_at=args.audit_started_at,
        external_slot=args.slot,
        external_slot_date=args.slot_date,
        external_scheduled_for_at=args.scheduled_for_at,
        external_requested_at=args.requested_at,
        external_dispatch_unix=args.dispatch_unix,
        expected_recipient_set_version=recipient_set_version_value,
        expected_recipient_set_effective_at=recipient_set_effective_at,
        require_recipient_set_metadata=True,
        expected_recipient_set_manifest_error=recipient_manifest_error,
        recipient_manifest=recipient_manifest,
        github_repository=args.repository,
        github_token=args.github_token,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    summary_path = os.getenv("GITHUB_STEP_SUMMARY", "")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write("## Scheduled slot recipient receipt audit\n\n")
            for key in (
                "status", "reason", "slot", "obligation", "market_date", "anchor",
                "ledger_source", "ledger_commit_sha", "audit_due_at", "audit_started_at",
                "scheduled_slot_at", "audit_delay_seconds", "trigger_source",
                "recipient_set_version", "recipient_set_effective_at",
            ):
                summary.write(f"- {key}: {result.get(key, 'not_applicable')}\n")
            diagnosis = result.get("run_diagnosis")
            if isinstance(diagnosis, dict):
                summary.write("\n### Matching scheduled workflow run (read-only)\n\n")
                for key in (
                    "status", "reason", "run_id", "workflow_sha", "run_url",
                    "run_conclusion", "terminal_status", "terminal_reason",
                    "sender_status", "receipt_status", "durable_receipt_verified", "no_resend",
                    "annotation_evidence_status",
                ):
                    if key in diagnosis:
                        summary.write(f"- {key}: {diagnosis[key]}\n")
                execution = diagnosis.get("execution_diagnostic")
                if isinstance(execution, dict):
                    summary.write(
                        "- execution_diagnostic: "
                        f"{execution.get('classification', 'unknown')} / "
                        f"{execution.get('reason', 'unknown')} "
                        f"(runner_started={execution.get('runner_started', 'unknown')}; "
                        f"install={execution.get('install_state', 'unknown')}; "
                        f"sync={execution.get('sync_state', 'unknown')}; "
                        f"source_health={execution.get('source_health', 'unknown')}; "
                        f"result_contract={execution.get('result_contract', 'unknown')}; "
                        f"cursor_effect={execution.get('cursor_effect', 'unknown')})\n"
                    )
                stages = diagnosis.get("stages")
                if isinstance(stages, dict):
                    summary.write("- stages: " + json.dumps(stages, sort_keys=True) + "\n")
                if diagnosis.get("no_resend"):
                    summary.write("- recovery: prohibited; this audit is read-only\n")
            summary.write(
                f"- recipient_receipt: {result.get('delivered_count', 0)}/{result.get('recipient_count', 0)}\n"
            )
            summary.write(
                f"- receipt_verified: {str(result.get('status') == 'delivered').lower()}\n"
            )
            summary.write("- mode: read-only; no dispatch, repair, or delivery attempted\n")
    return 1 if result.get("status") in {"blocked", "missing_receipt", "incomplete_receipt"} else 0


__all__ = ["audit_slot"]


if __name__ == "__main__":
    raise SystemExit(main())
