"""Read-only verification of Gmail inbox receipts through IncidentCoordinator."""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.incident_ops_auth import IncidentOpsAuthError, fetch_oidc_token, worker_get_json, worker_post_json

REPOSITORY = "hanjhou2000716/prstklab-stk-detector"
RECIPIENT = "hanjhou2000716@gmail.com"
SCHEMA = "incident-mail-receipt-audit-v1"
ALLOWED_STATES = {"inbox_verified", "awaiting_inbox", "not_visible_after_grace", "verification_unavailable"}


class MailReceiptError(RuntimeError):
    """Raised when a receipt audit cannot complete with verified identity."""


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass


def audit_pending_receipts(*, environment: dict[str, str]) -> dict[str, Any]:
    repository = environment.get("GITHUB_REPOSITORY", "").strip()
    if repository.casefold() != REPOSITORY.casefold():
        raise MailReceiptError("incident_receipt_repository_identity_invalid")
    base = environment.get("INCIDENT_OPS_URL", "")
    audience = environment.get("INCIDENT_OPS_AUDIENCE", "https://prstk-incident-ops")
    token = fetch_oidc_token(environment, audience=audience)
    pending = worker_get_json(base, "/ops/mail/pending-receipts", token=token)
    if pending.get("recipient") != RECIPIENT or not isinstance(pending.get("pending"), list) or len(pending["pending"]) > 100:
        raise MailReceiptError("incident_receipt_pending_contract_invalid")
    rows: list[dict[str, Any]] = []
    for item in pending["pending"]:
        if not isinstance(item, dict):
            raise MailReceiptError("incident_receipt_pending_row_invalid")
        delivery_id = str(item.get("delivery_id") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", delivery_id):
            raise MailReceiptError("incident_receipt_delivery_identity_invalid")
        result = worker_post_json(base, "/ops/mail/receipt", {"delivery_id": delivery_id}, token=token)
        state = str(result.get("receipt_state") or "")
        if result.get("delivery_id") != delivery_id or state not in ALLOWED_STATES:
            raise MailReceiptError("incident_receipt_result_identity_invalid")
        rows.append({
            "delivery_id": delivery_id,
            "state": state,
            "gmail_message_id_present": bool(result.get("gmail_message_id")),
            "checked_at": datetime.now(UTC).isoformat(),
        })
        if result.get("ok") is not True or state == "verification_unavailable":
            raise MailReceiptError(f"incident_receipt_not_verified:{state}")
    verified = sum(row["state"] == "inbox_verified" for row in rows)
    waiting = sum(row["state"] == "awaiting_inbox" for row in rows)
    delayed = sum(row["state"] == "not_visible_after_grace" for row in rows)
    return {
        "schema_version": SCHEMA,
        "repository": repository,
        "consumer_run_id": environment.get("GITHUB_RUN_ID", ""),
        "consumer_attempt": environment.get("GITHUB_RUN_ATTEMPT", ""),
        "consumer_sha": environment.get("GITHUB_SHA", ""),
        "status": "audited" if rows else "no_pending_receipts",
        "checked_count": len(rows),
        "inbox_verified_count": verified,
        "awaiting_inbox_count": waiting,
        "not_visible_after_grace_count": delayed,
        "receipts": rows,
        "observed_at": datetime.now(UTC).isoformat(),
    }


def main() -> int:
    path = Path(os.environ.get("INCIDENT_MAIL_RECEIPT_RESULT_PATH", "incident-mail-receipts.json"))
    try:
        result = audit_pending_receipts(environment=dict(os.environ))
        _write(path, result)
    except (IncidentOpsAuthError, MailReceiptError, OSError, ValueError) as exc:
        result = {
            "schema_version": SCHEMA,
            "repository": os.environ.get("GITHUB_REPOSITORY", ""),
            "consumer_run_id": os.environ.get("GITHUB_RUN_ID", ""),
            "consumer_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
            "consumer_sha": os.environ.get("GITHUB_SHA", ""),
            "status": "failed",
            "failure_reason": str(exc)[:180],
            "observed_at": datetime.now(UTC).isoformat(),
        }
        try:
            _write(path, result)
        except OSError as write_error:
            print(f"incident_mail_receipt_result_preservation_failed:{type(write_error).__name__}", file=sys.stderr)
        print(f"incident_mail_receipt_audit_failed:{str(exc)[:180]}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write("## PRStK Gmail receipt audit\n\n")
            summary.write(f"- status: {result['status']}\n")
            summary.write(f"- verified inbox receipts: {result['inbox_verified_count']}\n")
            summary.write(f"- waiting receipts: {result['awaiting_inbox_count']}\n")
            summary.write(f"- delayed/unseen receipts: {result['not_visible_after_grace_count']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
