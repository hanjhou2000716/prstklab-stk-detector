"""Compare linked Supabase migration history with repository migrations."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

VERSION_RE = re.compile(r"20\d{10}")


def local_versions(root: Path) -> set[str]:
    return {
        path.name.split("_", 1)[0]
        for path in (root / "supabase" / "migrations").glob("*.sql")
        if VERSION_RE.fullmatch(path.name.split("_", 1)[0])
    }


def local_version_counts(root: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in (root / "supabase" / "migrations").glob("*.sql"):
        version = path.name.split("_", 1)[0]
        if VERSION_RE.fullmatch(version):
            counts[version] = counts.get(version, 0) + 1
    return counts


def remote_versions(text: str) -> set[str]:
    """Read only the remote column from `supabase migration list` output.

    The CLI prints a table containing both Local and Remote versions.  Treating
    every timestamp in the output as remote makes an unapplied local migration
    look already registered.  Plain one-version-per-line input remains
    supported for tests and older CLI output.
    """
    lines = text.splitlines()
    header_index = None
    remote_index = None
    for index, line in enumerate(lines):
        columns = [column.strip().casefold() for column in line.split("|")]
        if "remote" in columns:
            header_index = index
            remote_index = columns.index("remote")
            break
    if remote_index is None:
        return {version for version in VERSION_RE.findall(text)}
    versions: set[str] = set()
    for line in lines[header_index + 1 :]:
        columns = line.split("|")
        if remote_index >= len(columns):
            continue
        versions.update(VERSION_RE.findall(columns[remote_index]))
    return versions


def compare(root: Path, remote_text: str) -> dict[str, object]:
    local = local_versions(root)
    local_counts = local_version_counts(root)
    remote = remote_versions(remote_text)
    unknown = sorted(remote - local)
    pending = sorted(local - remote)
    duplicates = sorted(version for version, count in local_counts.items() if count > 1)
    return {
        "status": "diverged" if unknown or duplicates else "ready",
        "local_count": len(local),
        "remote_count": len(remote),
        "pending_count": len(pending),
        "unknown_remote_versions": unknown,
        "pending_local_versions": pending,
        "duplicate_local_versions": duplicates,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--remote-file", type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.root, args.remote_file.read_text(encoding="utf-8", errors="replace"))
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result["status"] != "ready" else 0


if __name__ == "__main__":
    raise SystemExit(main())
