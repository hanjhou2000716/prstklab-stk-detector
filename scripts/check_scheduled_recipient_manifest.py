"""Read-only drift check between active Telegram subscribers and the audit manifest."""

from __future__ import annotations

import json
import os
import re
import sys

from src.alert_orchestrator import recipient_hash
from src.scheduled_recipient_manifest import parse_recipient_manifest
from src.telegram_subscriptions import TelegramSubscriptionError, fetch_active_chat_ids


def main() -> int:
    try:
        manifest = parse_recipient_manifest(os.getenv("SCHEDULED_RECIPIENT_SET_MANIFEST", ""))
        active_chat_ids = fetch_active_chat_ids()
        active_hashes = {recipient_hash(chat_id) for chat_id in active_chat_ids}
        if not active_hashes:
            raise ValueError("active_recipient_set_empty")
        latest = manifest.latest
        status = "in_sync" if active_hashes == set(latest.recipient_hashes) else "drift"
        result = {
            "status": status,
            "manifest_version": latest.version,
            "manifest_effective_at": latest.effective_at,
            "expected_recipient_count": len(latest.recipient_hashes),
            "active_recipient_count": len(active_hashes),
            "drift_detected": status == "drift",
            "read_only": True,
        }
    except (TelegramSubscriptionError, ValueError) as exc:
        reason = str(exc)
        if not re.fullmatch(r"[a-z0-9_]{1,100}", reason):
            reason = "recipient_manifest_drift_check_failed"
        result = {"status": "unavailable", "reason": reason, "read_only": True}
    print(json.dumps(result, sort_keys=True))
    summary_path = os.getenv("GITHUB_STEP_SUMMARY", "")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write("## Scheduled recipient manifest drift (read-only)\n\n")
            for key, value in result.items():
                summary.write(f"- {key}: {value}\n")
            summary.write("- raw_chat_ids: never emitted\n- Telegram sending: not configured\n")
    return 1 if result.get("status") != "in_sync" else 0


if __name__ == "__main__":
    raise SystemExit(main())
