"""Compare linked Supabase migration history with repository migrations."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

VERSION_RE = re.compile(r"\b20\d{10}\b")


def local_versions(root: Path) -> set[str]:
    return {
        path.name.split("_", 1)[0]
        for path in (root / "supabase" / "migrations").glob("*.sql")
        if VERSION_RE.fullmatch(path.name.split("_", 1)[0])
    }


def remote_versions(text: str) -> set[str]:
    return set(VERSION_RE.findall(text))


def compare(root: Path, remote_text: str) -> dict[str, object]:
    local = local_versions(root)
    remote = remote_versions(remote_text)
    unknown = sorted(remote - local)
    pending = sorted(local - remote)
    return {
        "status": "diverged" if unknown else "ready",
        "local_count": len(local),
        "remote_count": len(remote),
        "pending_count": len(pending),
        "unknown_remote_versions": unknown,
        "pending_local_versions": pending,
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
