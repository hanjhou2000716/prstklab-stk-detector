"""Create or renew the canonical Gmail Watch using Supabase state."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAILWAY = ROOT / "railway-monitor"
for path in (ROOT, RAILWAY):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from gmail_watch import GmailWatchConfig, GmailWatchManager  # noqa: E402
from supabase_email_store import SupabaseEmailStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="renew even when the current lease is healthy")
    args = parser.parse_args()
    config = GmailWatchConfig.from_env()
    store = SupabaseEmailStore()
    result = GmailWatchManager(config, store).ensure_watch(force=args.force)
    safe = {key: result[key] for key in ("status", "renewed", "watch_expiration", "missing", "error", "retry_suppressed", "retry_after_seconds") if key in result}
    print(json.dumps(safe, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") in {"healthy", "configuration_missing"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
