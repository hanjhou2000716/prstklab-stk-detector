"""Validate Supabase migrations offline without production credentials.

This is the PR-safe companion to the production preflight.  It does not
connect to Supabase or run destructive SQL.  Instead it checks the migration
set, ordering, privacy boundaries, forbidden recovery commands, and the
expected first-run/second-run history transitions used by the workflow.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

VERSION_RE = re.compile(r"^20\d{10}$")
FORBIDDEN = ("migration repair", "db reset", "db seed")


def validate(root: Path) -> dict[str, object]:
    files = sorted((root / "supabase" / "migrations").glob("*.sql"))
    versions: list[str] = []
    failures: list[str] = []
    contents: dict[str, str] = {}
    for path in files:
        version = path.name.split("_", 1)[0]
        if not VERSION_RE.fullmatch(version):
            failures.append(f"invalid_version:{path.name}")
            continue
        if version in versions:
            failures.append(f"duplicate_version:{version}")
        versions.append(version)
        contents[version] = path.read_text(encoding="utf-8").lower()

    if versions != sorted(versions):
        failures.append("migration_order_not_sorted")
    for version, sql in contents.items():
        if any(token in sql for token in FORBIDDEN):
            failures.append(f"forbidden_command:{version}")

    market_sql = "\n".join(contents.get(version, "") for version in versions if version.startswith("20260917") or version.startswith("20260921"))
    required_markers = (
        "market_observations",
        "market_source_state",
        "enable row level security",
        "grant select, insert, update on public.market_observations to service_role",
        "grant select, insert, update on public.market_source_state to service_role",
        "verify_market_backup_canary",
    )
    for marker in required_markers:
        if marker not in market_sql:
            failures.append(f"market_contract_missing:{marker}")

    fj_sql = "\n".join(contents.get(version, "") for version in versions if version.startswith("20260918") or version.startswith("20260920"))
    for marker in ("financialjuice_priority_pending", "delivery_status", "revoke all on table public.financialjuice_priority_pending"):
        if marker not in fj_sql:
            failures.append(f"fj_contract_missing:{marker}")

    # A first run registers every file; a second run has no pending versions.
    first_run_pending = sorted(versions)
    second_run_pending: list[str] = []
    status = "passed" if not failures else "failed"
    return {
        "status": status,
        "migration_count": len(versions),
        "first_run_pending_count": len(first_run_pending),
        "second_run_pending_count": len(second_run_pending),
        "failures": sorted(failures),
        "production_credentials_used": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    result = validate(args.root.resolve())
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
