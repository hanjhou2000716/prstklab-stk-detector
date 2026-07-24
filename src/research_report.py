"""Normalize public-scan artifacts into one browser- and report-friendly shape."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd


NOTICE = "不同策略的研究排序不可直接視為同一種分數；本報表僅統一欄位與資料狀態。"


def _value(value: Any) -> Any:
    return None if pd.isna(value) else value.item() if hasattr(value, "item") else value


def normalize_frame(frame: pd.DataFrame, market: str, strategy: str) -> list[dict[str, Any]]:
    """Map a known scan CSV to common fields without fabricating missing data."""
    if frame.empty or "ticker" not in frame.columns:
        return []
    candidates = []
    for rank, (_, row) in enumerate(frame.iterrows(), start=1):
        candidates.append({
            "market": market,
            "strategy": strategy,
            "rank": rank,
            "ticker": str(row["ticker"]),
            "name": _value(row.get("name")),
            "score": _value(row.get("score")),
            "turnover": _value(row.get("turnover")),
            "reference_price": _value(row.get("reference_close", row.get("close"))),
            "structural_stop": _value(row.get("reference_stop")),
            "structure": _value(row.get("funnel_labels")),
        })
    return candidates


def build_research_report(sources: list[dict[str, str]]) -> dict[str, Any]:
    """Read named CSV artifacts, disclosing unavailable or empty source files."""
    candidates: list[dict[str, Any]] = []
    sources_status: list[dict[str, Any]] = []
    for source in sources:
        path = Path(source["path"])
        base = {"market": source["market"], "strategy": source["strategy"], "path": str(path)}
        try:
            frame = pd.read_csv(path)
        except (FileNotFoundError, pd.errors.EmptyDataError, UnicodeDecodeError):
            sources_status.append({**base, "status": "資料暫時無法取得", "candidates": 0})
            continue
        rows = normalize_frame(frame, source["market"], source["strategy"])
        sources_status.append({**base, "status": "可用" if rows else "本次無研究候選", "candidates": len(rows)})
        candidates.extend(rows)
    counts = Counter(f"{item['market']}:{item['strategy']}" for item in candidates)
    return {
        "status": "跨市場研究摘要" if candidates else "目前沒有可整合的研究候選",
        "notice": NOTICE,
        "sources": sources_status,
        "candidates": candidates,
        "summary": {"total_candidates": len(candidates), "by_market_strategy": dict(counts)},
    }
