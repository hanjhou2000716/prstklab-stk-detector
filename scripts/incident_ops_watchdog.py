"""Read the private coordinator's readiness without exposing secret values."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.incident_ops_auth import IncidentOpsAuthError, fetch_oidc_token, worker_get_json

REPOSITORY = "hanjhou2000716/prstklab-stk-detector"
SCHEMA = "incident-ops-watchdog-v1"


class OpsWatchdogError(RuntimeError):
    """Raised when coordinator status is unavailable or violates its contract."""


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


def inspect_ops_health(*, environment: dict[str, str]) -> dict[str, Any]:
    repository = environment.get("GITHUB_REPOSITORY", "").strip()
    if repository.casefold() != REPOSITORY.casefold():
        raise OpsWatchdogError("incident_ops_repository_identity_invalid")
    token = fetch_oidc_token(environment, audience=environment.get("INCIDENT_OPS_AUDIENCE", "https://prstk-incident-ops"))
    body = worker_get_json(environment.get("INCIDENT_OPS_URL", ""), "/ops/health", token=token, require_ok=False)
    mode = body.get("mode")
    expected_mode = environment.get("INCIDENT_OPS_MODE", "shadow").strip().lower()
    if expected_mode not in {"shadow", "live"} or mode != expected_mode:
        raise OpsWatchdogError("incident_ops_mode_mismatch")
    if mode not in {"shadow", "live"} or body.get("recipient_fixed") != "hanjhou2000716@gmail.com":
        raise OpsWatchdogError("incident_ops_health_identity_invalid")
    for key in ("ready_to_cutover", "ok", "gmail_configured", "receipt_gmail_configured", "telegram_admin_fallback_configured"):
        if not isinstance(body.get(key), bool):
            raise OpsWatchdogError(f"incident_ops_health_field_invalid:{key}")
    if mode == "shadow":
        if body.get("ok") is not True or body.get("operational_status") != "shadow":
            raise OpsWatchdogError("incident_ops_shadow_health_invalid")
        state = "shadow_ready_for_observation"
    elif body.get("ok") is True and body.get("ready_to_cutover") is True and body.get("operational_status") == "ready":
        state = "live_ready"
    else:
        state = "live_degraded"
    return {
        "schema_version": SCHEMA,
        "repository": repository,
        "consumer_run_id": environment.get("GITHUB_RUN_ID", ""),
        "consumer_attempt": environment.get("GITHUB_RUN_ATTEMPT", ""),
        "consumer_sha": environment.get("GITHUB_SHA", ""),
        "status": state,
        "health": body,
        "observed_at": datetime.now(UTC).isoformat(),
    }


def main() -> int:
    path = Path(os.environ.get("INCIDENT_OPS_HEALTH_RESULT_PATH", "incident-ops-health.json"))
    try:
        result = inspect_ops_health(environment=dict(os.environ))
        _write(path, result)
    except (IncidentOpsAuthError, OpsWatchdogError, OSError, ValueError) as exc:
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
            print(f"incident_ops_health_result_preservation_failed:{type(write_error).__name__}", file=sys.stderr)
        print(f"incident_ops_watchdog_failed:{str(exc)[:180]}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write("## PRStK incident service health\n\n")
            summary.write(f"- status: {result['status']}\n")
            summary.write(f"- mode: {result['health']['mode']}\n")
            summary.write(f"- ready to cut over: {str(result['health']['ready_to_cutover']).lower()}\n")
            summary.write(f"- delivery unknown: {result['health'].get('delivery_unknown', 'unknown')}\n")
            summary.write(f"- stale inbox receipts: {result['health'].get('stale_inbox_receipts', 'unknown')}\n")
    return 1 if result["status"] == "live_degraded" else 0


if __name__ == "__main__":
    raise SystemExit(main())
