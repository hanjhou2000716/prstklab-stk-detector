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

from gmail_history_sync import sync_gmail_history, sync_latest_financialjuice  # noqa: E402
from gmail_watch import GmailWatchConfig  # noqa: E402
from supabase_email_store import SupabaseEmailStore  # noqa: E402

from gmail_ingress import GmailIngressService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-messages", type=int, default=50)
    parser.add_argument("--history-id", default=None, help="Pub/Sub cursor supplied by the Worker")
    parser.add_argument("--latest-financialjuice", action="store_true", help="Reprocess only the newest FJ mail without moving the cursor")
    args = parser.parse_args()
    config = GmailWatchConfig.from_env()
    store: Any = SupabaseEmailStore()
    cursor = store.cursor()
    pending = str(args.history_id or cursor.get("pending_history_id") or "").strip()
    baseline = str(cursor.get("last_history_id") or "").strip()
    if not baseline and pending:
        # A freshly-created Watch returns a baseline cursor.  If an operator
        # invokes this workflow before the first renewal persisted it, use the
        # notification cursor as a fail-closed baseline (no historical replay).
        store.save_cursor(last_history_id=pending)
    elif pending and pending == baseline:
        store.save_cursor(pending_history_id=None)
    ingress = GmailIngressService(store, config)
    if args.latest_financialjuice:
        result = asyncio.run(sync_latest_financialjuice(config, store, ingress))
    else:
        result = asyncio.run(sync_gmail_history(config, store, ingress, max_messages=args.max_messages))
    if result.get("status") in {"healthy", "no_history_cursor"}:
        store.save_cursor(pending_history_id=None)
    safe = {key: result[key] for key in ("status", "processed", "failed", "duplicate", "skipped", "history_gap", "failure_types") if key in result}
    print(json.dumps(safe, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
