"""CLI for verifying an imported historical backtest archive."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.backtest_archive import audit_backtest_archive


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit PRStK point-in-time backtest archive")
    parser.add_argument("--root", default="data/backtest")
    parser.add_argument("--market", choices=("taiwan", "us"), required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    report = audit_backtest_archive(Path(args.root), args.market)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        destination = Path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8")
    print(rendered)
    if report["status"] != "ready":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
