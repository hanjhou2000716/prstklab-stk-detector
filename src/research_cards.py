"""Load the latest full-universe research artifact for the public Mini App."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REPORT_PATH = Path("site/data/research-report.json")
ALLOWED_STRATEGIES = {"momentum", "price_action"}
ALLOWED_MARKETS = {"taiwan", "us"}


def load_research_cards(path: Path = REPORT_PATH) -> dict[str, Any]:
    """Return only non-actionable fields from the newest research artifact."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "status": "資料暫時無法取得",
            "notice": "全市場研究報告尚未產生，請等待下一次掃描完成。",
            "generated_at": None,
            "sources": [],
            "candidates": [],
        }

    candidates = []
    for item in raw.get("candidates", []):
        if not isinstance(item, dict) or item.get("strategy") not in ALLOWED_STRATEGIES or item.get("market") not in ALLOWED_MARKETS:
            continue
        candidates.append({key: item.get(key) for key in (
            "market", "strategy", "rank", "ticker", "name", "score", "turnover", "structure"
        )})
    sources = [
        {key: source.get(key) for key in ("market", "strategy", "status", "candidates", "requested", "data_complete", "failed")}
        for source in raw.get("sources", [])
        if isinstance(source, dict) and source.get("strategy") in ALLOWED_STRATEGIES
    ]
    return {
        "status": raw.get("status", "研究報告"),
        "notice": raw.get("notice", "全市場公開資料研究。"),
        "generated_at": raw.get("generated_at"),
        "sources": sources,
        "candidates": candidates,
    }
