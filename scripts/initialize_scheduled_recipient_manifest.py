"""Generate one sanitized active-recipient manifest without sending or mutating."""

from __future__ import annotations

import json
import os
import re

from src.scheduled_recipient_manifest import build_recipient_manifest
from src.telegram_subscriptions import TelegramSubscriptionError, fetch_active_chat_ids


def main() -> int:
    try:
        active_chat_ids = fetch_active_chat_ids()
        manifest = build_recipient_manifest(
            active_chat_ids,
            prior_manifest_raw=os.getenv("CURRENT_SCHEDULED_RECIPIENT_SET_MANIFEST", ""),
        )
    except (TelegramSubscriptionError, ValueError) as exc:
        reason = str(exc)
        if not re.fullmatch(r"[a-z0-9_]{1,100}", reason):
            reason = "recipient_manifest_initialization_failed"
        result = {"status": "blocked", "reason": reason}
        print(json.dumps(result, sort_keys=True))
        return 1

    serialized = json.dumps(manifest, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    print(serialized)
    summary_path = os.getenv("GITHUB_STEP_SUMMARY", "")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write("## Scheduled recipient manifest (read-only initialization)\n\n")
            latest = manifest["versions"][-1]
            summary.write(f"- status: ready\n- version: {latest['version']}\n")
            summary.write(f"- effective_at: {latest['effective_at']}\n")
            summary.write(f"- recipient_count: {len(latest['recipient_hashes'])}\n")
            summary.write("- raw_chat_ids: never read into output; Telegram sending was not configured\n")
            summary.write("\nCopy the following single JSON value to repository variable ")
            summary.write("`SCHEDULED_RECIPIENT_SET_MANIFEST` after review:\n\n```json\n")
            summary.write(serialized + "\n```\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
