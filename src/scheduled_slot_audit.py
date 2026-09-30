"""Read-only receipt audit for all four scheduled notification anchors."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import zipfile
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.schedule_contract import NEW_YORK, TAIPEI, fixed_scheduled_for, scheduled_anchor_key

SCHEDULE_TO_SLOT = {
    "45 22 * * *": "morning",
    "30 1 * * 1-5": "pre_open",
    "5 7 * * 1-5": "post_close",
    "45 13 * * 1-5": "us_premarket",
    "45 14 * * 1-5": "us_premarket",
}


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
        candidate = datetime.combine(day, time(hour, minute), UTC)
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


def _expected_recipient_hashes_from_env() -> set[str]:
    """Read a pre-hashed allowlist; never require subscriber IDs in audit logs."""
    raw_hashes = os.getenv("SCHEDULED_RECIPIENT_HASHES", "")
    hashes = {value.strip().casefold() for value in raw_hashes.split(",") if value.strip()}
    if hashes:
        return hashes if all(re.fullmatch(r"[0-9a-f]{12}", value) for value in hashes) else set()
    # Keep audit membership independent from sender configuration and secrets.
    return set()


def recipient_set_version(recipient_hashes: set[str], effective_at: str) -> str:
    """Bind the audited recipient hashes and effective timestamp into one version."""
    normalized_hashes = sorted({str(value).strip().casefold() for value in recipient_hashes if str(value).strip()})
    parsed = datetime.fromisoformat(str(effective_at).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("recipient set effective time must include a timezone")
    normalized_effective = parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    material = json.dumps(
        {"recipient_hashes": normalized_hashes, "effective_at": normalized_effective},
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return f"recipients-{hashlib.sha256(material).hexdigest()[:16]}"


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
    """Extract only the bounded, machine-readable terminal row from run logs."""
    if len(body) > 20 * 1024 * 1024:
        raise ValueError("workflow_logs_too_large")
    records: list[dict[str, Any]] = []
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        for member in archive.infolist():
            if not member.filename.endswith(".txt") or member.file_size > 5 * 1024 * 1024:
                continue
            with archive.open(member) as handle:
                for raw_line in handle:
                    if len(records) >= 20:
                        return records
                    try:
                        line = raw_line.decode("utf-8")
                        json_start = line.find("{")
                        row = json.loads(line[json_start:]) if json_start >= 0 else None
                    except (UnicodeError, json.JSONDecodeError):
                        continue
                    if (
                        isinstance(row, dict)
                        and row.get("schema_version") == "notification-terminal-v1"
                        and row.get("workflow") == "scheduled"
                    ):
                        records.append(row)
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
        "per_page": "100",
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
        with opener(request, timeout=15) as response:
            body = response.read(limit + 1)
        if len(body) > limit:
            raise ValueError("github_response_too_large")
        return body

    try:
        runs_body = get(f"{base}/actions/workflows/scheduled-brief.yml/runs?{query}", limit=2 * 1024 * 1024)
        payload = json.loads(runs_body.decode("utf-8"))
        runs = payload.get("workflow_runs") if isinstance(payload, dict) else None
        if not isinstance(runs, list):
            raise ValueError("github_workflow_runs_invalid")
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
            logs = get(f"{base}/actions/runs/{run_id}/logs", limit=20 * 1024 * 1024)
            for terminal in _terminal_records_from_logs(logs):
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
                ):
                    matches.append((run, terminal))
        if len(matches) != 1:
            return {
                "status": "ambiguous" if len(matches) > 1 else "not_found",
                "reason": "scheduled_terminal_not_unique",
                "candidate_run_count": len(candidates),
                "no_resend": True,
            }
        run, terminal = matches[0]
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
            "expected": terminal.get("expected") is True,
            "sender_status": str(terminal.get("sender_status") or "unknown")[:80],
            "receipt_status": str(terminal.get("receipt_status") or "unknown")[:80],
            "durable_receipt_verified": durable,
            "no_resend": terminal_no_resend or status in {
                "delivered", "delivered_reconciliation_incomplete",
            },
            "stages": {
                key: str(stages.get(key) or "unknown")[:80]
                for key in ("prepare", "deployment", "public_gate", "receipt", "ledger")
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
        try:
            expected = fixed_scheduled_for(slot, slot_date)
        except ValueError as exc:
            # A weekday NYSE holiday still has an auditable nominal 09:00
            # premarket anchor; the independent exchange calendar below will
            # classify it as expected_skip, never as a delivery obligation.
            if slot != "us_premarket" or str(exc) != "market_closed":
                return None
            expected = datetime.fromisoformat(f"{slot_date}T09:00:00").replace(tzinfo=NEW_YORK)
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
        due_time = anchor_local + timedelta(minutes=45)
        if requested_at.astimezone(UTC) < due_time.astimezone(UTC):
            return {"status": "blocked", "reason": "external_audit_requested_before_deadline", **source_fields}
        request_utc = requested_at.astimezone(UTC)
        if request_utc > now.astimezone(UTC) + timedelta(minutes=5):
            return {"status": "blocked", "reason": "external_audit_requested_at_in_future", **source_fields}
        request_age_limit = timedelta(hours=72) if external_slot_date else timedelta(hours=12)
        if now.astimezone(UTC) - request_utc > request_age_limit:
            return {"status": "blocked", "reason": "external_audit_request_expired", **source_fields}
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
    metadata_error, effective_label = _recipient_set_metadata_error(
        expected_recipient_set_version,
        expected_recipient_set_effective_at,
        original_slot_anchor,
        expected_recipient_hashes,
    )
    normalized_version = str(expected_recipient_set_version or "").strip()
    source_fields["recipient_set_version"] = (
        normalized_version
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", normalized_version)
        else "unknown"
    )
    source_fields["recipient_set_effective_at"] = effective_label
    if require_recipient_set_metadata and metadata_error:
        return {
            "status": "blocked", "reason": metadata_error, "slot": slot,
            "obligation": obligation, "market_date": slot_date, "anchor": anchor, **source_fields,
        }
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
    parser.add_argument("--ledger", type=Path, required=True)
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
    parser.add_argument("--recipient-set-version", default=os.getenv("SCHEDULED_RECIPIENT_SET_VERSION", ""))
    parser.add_argument("--recipient-set-effective-at", default=os.getenv("SCHEDULED_RECIPIENT_SET_EFFECTIVE_AT", ""))
    parser.add_argument("--repository", default=os.getenv("GITHUB_REPOSITORY", ""))
    parser.add_argument("--github-token", default=os.getenv("GITHUB_TOKEN", ""))
    parser.add_argument("--now", help="UTC timestamp override for deterministic tests")
    args = parser.parse_args()
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(UTC)
    expected_recipient_hashes = _expected_recipient_hashes_from_env()
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
        expected_recipient_set_version=args.recipient_set_version,
        expected_recipient_set_effective_at=args.recipient_set_effective_at,
        require_recipient_set_metadata=True,
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
                ):
                    if key in diagnosis:
                        summary.write(f"- {key}: {diagnosis[key]}\n")
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
