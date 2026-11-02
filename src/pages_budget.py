"""Enforce the bounded public Pages working set before upload."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

DEFAULT_MAX_BYTES = 512 * 1024 * 1024
MAX_FILES = 50_000


class PagesBudgetError(RuntimeError):
    pass


def measure_pages_tree(root: Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> tuple[int, int]:
    root = root.resolve(strict=True)
    total = 0
    count = 0
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(directory)
        for name in list(dirnames):
            path = current / name
            if path.is_symlink():
                raise PagesBudgetError("Pages working set contains a symbolic link")
        for name in filenames:
            path = current / name
            if path.is_symlink() or not path.is_file():
                raise PagesBudgetError("Pages working set contains an unsupported file type")
            count += 1
            if count > MAX_FILES:
                raise PagesBudgetError("Pages working set contains too many files")
            total += path.stat().st_size
            if total > max_bytes:
                raise PagesBudgetError("Pages working set exceeds the configured byte budget")
    return total, count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("site"))
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    args = parser.parse_args()
    if args.max_bytes <= 0:
        print("pages_budget_invalid_limit", file=sys.stderr)
        return 2
    try:
        total, files = measure_pages_tree(args.root, max_bytes=args.max_bytes)
    except (OSError, PagesBudgetError) as exc:
        print(f"pages_budget_failed:{str(exc)[:180]}", file=sys.stderr)
        return 1
    print(f"pages_budget_ok bytes={total} files={files} max_bytes={args.max_bytes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
