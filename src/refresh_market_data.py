"""Generate the dashboard's public market-data JSON file."""

from __future__ import annotations

import json
from pathlib import Path

from src.market_data import build_market_snapshot


def write_snapshot(snapshot: dict) -> None:
    """Write the latest browser-friendly data without exposing any secrets."""
    destination = Path("site/data/market.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    snapshot = build_market_snapshot()
    write_snapshot(snapshot)
    print(
        f"已產生 {len(snapshot['quotes'])} 筆報價；"
        f"資料狀態：{snapshot['data_status']}。"
    )


if __name__ == "__main__":
    main()
