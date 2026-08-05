"""Evidence-backed event-to-market transmission paths.

The graph is deliberately conditional: it describes a plausible transmission
route and the observations that would support it; it never turns a headline
into a directional trading instruction.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Iterable


PATHWAYS: tuple[dict[str, Any], ...] = (
    {
        "key": "export-controls-semiconductor",
        "terms": ("export control", "出口管制", "晶片", "semiconductor", "ai chip"),
        "nodes": ("政策／出口管制", "AI 晶片供應", "半導體權值", "費半", "台股電子權值"),
        "tickers": ("NVDA", "AMD", "TSM", "SOX", "TAIEX"),
        "direction": "conditional_risk",
        "horizon": "days_to_weeks",
        "invalidation": "官方政策未生效，或相關市場價格與成交量未確認方向。",
    },
    {
        "key": "conflict-energy-shipping",
        "terms": ("war", "conflict", "iran", "伊朗", "戰爭", "航運", "hormuz", "荷姆茲"),
        "nodes": ("地緣衝突", "航運／能源供給", "原油", "通膨預期", "利率／股市風險偏好"),
        "tickers": ("WTI", "BRENT", "GOLD", "DXY", "NASDAQ", "TAIEX"),
        "direction": "conditional_risk",
        "horizon": "hours_to_days",
        "invalidation": "官方資訊撤回或降級，且油價／股市未出現同步確認。",
    },
    {
        "key": "central-bank-rates",
        "terms": ("fed", "fomc", "ecb", "央行", "利率", "monetary policy", "interest rate"),
        "nodes": ("央行政策", "利率", "美元／美債", "科技股估值", "全球風險偏好"),
        "tickers": ("US10Y", "DXY", "NASDAQ", "SOX", "TAIEX"),
        "direction": "conditional_macro",
        "horizon": "hours_to_months",
        "invalidation": "政策聲明與市場定價方向不一致，或報價已逾時。",
    },
)


def _text(record: dict[str, Any]) -> str:
    values = [record.get(key) for key in ("title", "summary", "brief_summary", "traditional_chinese_summary", "event_type")]
    return " ".join(str(value or "") for value in values).lower()


def _observed_tickers(observations: Iterable[dict[str, Any]] | None) -> set[str]:
    return {
        str(item.get("ticker") or "").upper()
        for item in (observations or ())
        if item.get("ticker") and item.get("price") is not None and not item.get("stale_used")
    }


def build_market_impact_graph(
    event: dict[str, Any], observations: Iterable[dict[str, Any]] | None = None, *, validated_at: str | None = None
) -> dict[str, Any]:
    """Return matching transmission paths with explicit evidence and caveats."""
    text = _text(event)
    observed = _observed_tickers(observations)
    now = validated_at or datetime.now(UTC).isoformat()
    paths: list[dict[str, Any]] = []
    for pathway in PATHWAYS:
        if not any(term.lower() in text for term in pathway["terms"]):
            continue
        matched = sorted(set(pathway["tickers"]) & observed)
        evidence = [{"type": "event", "source_url": str(event.get("source_url") or ""), "published_at": event.get("published_at")}]
        if matched:
            evidence.append({"type": "market_sync", "tickers": matched, "observation_count": len(matched)})
        paths.append({
            "key": pathway["key"],
            "nodes": list(pathway["nodes"]),
            "edges": [{"from": left, "to": right, "direction": pathway["direction"]} for left, right in zip(pathway["nodes"], pathway["nodes"][1:])],
            "confidence": 0.8 if matched else 0.55,
            "evidence": evidence,
            "time_horizon": pathway["horizon"],
            "last_validated": now,
            "invalidation_condition": pathway["invalidation"],
            "market_sync": bool(matched),
        })
    return {"graph_version": "p2-05.v1", "event_key": str(event.get("event_cluster_key") or event.get("source_url") or event.get("title") or "unknown"), "paths": paths}

