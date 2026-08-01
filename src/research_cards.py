"""Load the latest full-universe research artifact for the public Mini App."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.research_health import assess_research_health


REPORT_PATH = Path("site/data/research-report.json")
ALLOWED_STRATEGIES = {"momentum", "price_action", "resonance", "value"}
ALLOWED_MARKETS = {"taiwan", "us"}


def load_research_cards(path: Path = REPORT_PATH, *, now: datetime | None = None) -> dict[str, Any]:
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

    health = assess_research_health(raw, now=now or datetime.now(ZoneInfo("Asia/Taipei")))
    expired = bool(health["is_expired"])
    blocked_sources = {
        (str(item.get("market")), str(item.get("strategy")))
        for item in raw.get("sources", [])
        if isinstance(item, dict)
        and (
            item.get("scan_state") in {"failed", "building"}
            or item.get("status") in {"掃描失敗", "資料暫時無法取得", "建檔中"}
        )
    }
    candidates = []
    for item in raw.get("candidates", []):
        if not isinstance(item, dict) or item.get("strategy") not in ALLOWED_STRATEGIES or item.get("market") not in ALLOWED_MARKETS:
            continue
        if expired:
            continue
        if (str(item.get("market")), str(item.get("strategy"))) in blocked_sources:
            continue
        candidates.append({key: item.get(key) for key in (
            "market", "strategy", "rank", "ticker", "name", "score", "close", "previous_close", "change_percent", "turnover", "as_of", "signal_labels", "volume_ratio", "range_contraction", "breakout_20", "vcp_breakout", "new_high_days", "fgi_score", "fgi_status", "conditions_matched", "condition_count", "structure", "status",
            "roe", "pe", "payout_ratio", "metrics_available", "moat_review"
        )})
    sources = [
        {key: source.get(key) for key in (
            "market", "strategy", "status", "candidates", "requested", "data_complete", "failed",
            "scan_state", "history_cached", "history_expected", "notice", "error_details",
        )}
        for source in raw.get("sources", [])
        if isinstance(source, dict) and source.get("strategy") in ALLOWED_STRATEGIES
    ]
    return {
        "status": raw.get("status", "研究報告"),
        "notice": raw.get("notice", "全市場公開資料研究。"),
        "generated_at": raw.get("generated_at"),
        "sources": sources,
        "candidates": candidates,
        "health": health,
        "availability": "expired" if expired else "available",
        "notice": "研究資料已逾時，候選清單已隱藏；等待下一次全市場掃描完成。" if expired else raw.get("notice"),
    }
