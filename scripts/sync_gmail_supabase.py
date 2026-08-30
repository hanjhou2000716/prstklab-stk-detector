"""Synchronise bounded Gmail history using Supabase-backed private state."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RAILWAY = ROOT / "railway-monitor"
for path in (ROOT, RAILWAY):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from gmail_history_sync import sync_gmail_history  # noqa: E402
from gmail_watch import GmailWatchConfig  # noqa: E402
from supabase_email_store import SupabaseEmailStore  # noqa: E402

from gmail_ingress import GmailIngressService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-messages", type=int, default=50)
    args = parser.parse_args()
    config = GmailWatchConfig.from_env()
    store: Any = SupabaseEmailStore()
    cursor = store.cursor()
    pending = str(cursor.get("pending_history_id") or "").strip()
    if pending and pending != str(cursor.get("last_history_id") or "").strip():
        # Keep the Pub/Sub cursor private and let the canonical history sync
        # advance the durable baseline only after a successful API read.
        store.save_cursor(last_notification_at=cursor.get("last_notification_at"), last_sync_at=cursor.get("last_sync_at"))
    result = asyncio.run(sync_gmail_history(config, store, GmailIngressService(store, config), max_messages=args.max_messages))
    if result.get("status") in {"healthy", "no_history_cursor"}:
        store.save_cursor(pending_history_id=None)
    safe = {key: result[key] for key in ("status", "processed", "failed", "duplicate", "history_gap") if key in result}
    print(json.dumps(safe, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
