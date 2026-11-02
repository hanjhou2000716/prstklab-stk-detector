"""Send one explicit, fixed-recipient owner verification through the coordinator."""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.incident_ops_auth import IncidentOpsAuthError, fetch_oidc_token, worker_post_json

REPOSITORY = "hanjhou2000716/prstklab-stk-detector"
RECIPIENT = "hanjhou2000716@gmail.com"
CONFIRMATION = "SEND_ONE_VERIFICATION_EMAIL"
SCHEMA = "incident-mail-verification-v1"


class MailVerificationError(RuntimeError):
    """Raised when the owner verification cannot be safely established."""


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def send_owner_verification(*, environment: dict[str, str]) -> dict[str, Any]:
    if environment.get("GITHUB_REPOSITORY", "").casefold() != REPOSITORY.casefold():
        raise MailVerificationError("incident_mail_verification_repository_invalid")
    if environment.get("INPUT_CONFIRM_SEND", "").strip() != "yes":
        raise MailVerificationError("incident_mail_verification_explicit_confirmation_required")
    verification_id = environment.get("INPUT_VERIFICATION_ID", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{15,63}", verification_id):
        raise MailVerificationError("incident_mail_verification_id_invalid")
    base = environment.get("INCIDENT_OPS_URL", "")
    audience = environment.get("INCIDENT_OPS_AUDIENCE", "https://prstk-incident-ops")
    token = fetch_oidc_token(environment, audience=audience)
    result = worker_post_json(base, "/ops/mail/verify", {
        "confirmation": CONFIRMATION,
        "verification_id": verification_id,
    }, token=token)
    if result.get("verification_id") != verification_id or result.get("recipient") != RECIPIENT:
        raise MailVerificationError("incident_mail_verification_identity_mismatch")
    if not re.fullmatch(r"[0-9a-f]{64}", str(result.get("delivery_id") or "")):
        raise MailVerificationError("incident_mail_verification_delivery_id_invalid")
    state = str(result.get("state") or "")
    if state not in {"sent_verified", "reserved", "draft_creating", "draft_ready", "sending", "reconciling", "delivery_unknown", "failed_not_sent"}:
        raise MailVerificationError("incident_mail_verification_state_invalid")
    return {
        "schema_version": SCHEMA,
        "repository": REPOSITORY,
        "workflow_run_id": environment.get("GITHUB_RUN_ID", ""),
        "workflow_attempt": environment.get("GITHUB_RUN_ATTEMPT", ""),
        "workflow_sha": environment.get("GITHUB_SHA", ""),
        "verification_id": verification_id,
        "delivery_id": result["delivery_id"],
        "recipient": RECIPIENT,
        "state": state,
        "delivery_verified": result.get("delivery_verified") is True,
        "inbox_verified": result.get("inbox_verified") is True,
        "message_id": str(result.get("message_id") or ""),
        "content_sha256": str(result.get("content_sha256") or ""),
        "observed_at": datetime.now(UTC).isoformat(),
    }


def main() -> int:
    path = Path(os.environ.get("INCIDENT_MAIL_VERIFICATION_RESULT_PATH", "incident-mail-verification.json"))
    try:
        result = send_owner_verification(environment=dict(os.environ))
        _write(path, result)
    except (IncidentOpsAuthError, MailVerificationError, OSError, ValueError) as exc:
        result = {
            "schema_version": SCHEMA,
            "repository": os.environ.get("GITHUB_REPOSITORY", ""),
            "workflow_run_id": os.environ.get("GITHUB_RUN_ID", ""),
            "workflow_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
            "workflow_sha": os.environ.get("GITHUB_SHA", ""),
            "status": "failed_or_unverified",
            "error": str(exc)[:180],
            "observed_at": datetime.now(UTC).isoformat(),
        }
        try:
            _write(path, result)
        except OSError:
            pass
        print(f"incident_mail_verification_failed:{str(exc)[:180]}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    if result["delivery_verified"] is not True:
        return 1
    if result["inbox_verified"] is not True:
        print("incident_mail_sent_but_inbox_receipt_pending", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
