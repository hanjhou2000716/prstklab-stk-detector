"""Offline Creator Consensus V2 and market-scoped news acceptance lane.

The lane exercises the canonical creator consensus, creator-to-PRStK evidence
correlation, and news routing contracts together.  It deliberately uses only
synthetic public-safe records and never contacts Gmail, providers, Railway,
Pages, or Telegram.
"""

from __future__ import annotations

from typing import Any

from src.creator_consensus import build_creator_consensus
from src.creator_correlation import correlate_creator_insight
from src.news_intelligence import build_news_intelligence

_AS_OF = "2026-08-22T03:00:00+00:00"


def _creator_records() -> list[dict[str, Any]]:
    """Return two latest creator views plus an older superseded view."""
    return [
        {
            "creator_id": "haojiao",
            "episode_key": "haojiao-old",
            "published_at": "2026-08-21T00:00:00+00:00",
            "topics": ["oil"],
            "consensus_stance": "risk_on",
            "parse_status": "parsed",
            "public_safe": True,
        },
        {
            "creator_id": "haojiao",
            "episode_key": "haojiao-latest",
            "published_at": "2026-08-22T02:00:00+00:00",
            "topics": ["原油", "半導體"],
            "consensus_stance": "risk_off",
            "risk_topics": ["oil", "semiconductor"],
            "parse_status": "parsed",
            "public_safe": True,
            "prstk_correlation": {"evidence_alignment": "aligned"},
        },
        {
            "creator_id": "jenny",
            "episode_key": "jenny-latest",
            "published_at": "2026-08-22T02:10:00+00:00",
            "topics": ["oil", "semiconductor"],
            "consensus_stance": "risk_off",
            "risk_topics": ["oil", "semiconductor"],
            "parse_status": "parsed",
            "public_safe": True,
            "prstk_correlation": {"evidence_alignment": "aligned"},
        },
    ]


def _news_records() -> list[dict[str, Any]]:
    return [
        {
            "title": "TSMC raises capital spending outlook",
            "summary": "TSMC announced higher capital spending for semiconductor capacity.",
            "url": "https://www.twse.com.tw/news/semiconductor?utm_source=e2e",
            "published_at": _AS_OF,
            "market": "taiwan",
            "tickers": ["2330"],
            "topics": ["semiconductor"],
        },
        {
            "title": "Federal Reserve policy statement",
            "url": "https://www.federalreserve.gov/pressreleases/policy.htm",
            "published_at": _AS_OF,
            "market": "us",
            "topics": ["rates"],
        },
        {
            "title": "Taiwan semiconductor filing (market copy)",
            "url": "https://www.cnyes.com/news/semiconductor-copy",
            "published_at": _AS_OF,
            "market": "taiwan",
            "tickers": ["2330"],
            "topics": ["semiconductor"],
        },
    ]


def run_creator_intelligence_e2e() -> dict[str, Any]:
    """Return deterministic evidence for consensus, correlation, and routing."""
    records = _creator_records()
    consensus = build_creator_consensus(records, as_of=_AS_OF)
    divergent = build_creator_consensus(
        [*records[:-1], {**records[-1], "consensus_stance": "neutral"}],
        as_of=_AS_OF,
    )
    insight = {
        "creator_id": "haojiao",
        "topics": ["semiconductor"],
        "tickers": ["TSM"],
        "sectors": ["semiconductor"],
    }
    correlation = correlate_creator_insight(
        insight,
        market_snapshot={
            "snapshot_id": "creator-e2e-market",
            "generated_at": _AS_OF,
            "quotes": [{"ticker": "TSM", "sector": "semiconductor"}],
        },
        research_snapshot={
            "snapshot_id": "creator-e2e-research",
            "generated_at": _AS_OF,
            "candidates": [{"ticker": "TSM", "sector": "semiconductor"}],
        },
        as_of=_AS_OF,
    )
    taiwan_news = build_news_intelligence(
        _news_records(),
        market="taiwan",
        tracked_tickers=("2330",),
        tracked_sectors=("semiconductor",),
        topics=("semiconductor",),
        limit=5,
    )
    us_news = build_news_intelligence(_news_records(), market="us", topics=("rates",), limit=5)
    checks = {
        "latest_per_creator": consensus["source_count"] == 2 and consensus["coverage"] == "2/2",
        "aligned_consensus_is_not_signal": (
            consensus["consensus_state"] == "aligned"
            and consensus["directional_consensus"] == "aligned"
            and consensus["is_investment_signal"] is False
        ),
        "divergence_visible": divergent["consensus_state"] == "mixed" and bool(divergent["divergent_views"]),
        "creator_market_correlation": (
            correlation["correlation_state"] == "aligned"
            and correlation["evidence_alignment"] == "aligned"
            and correlation["is_investment_signal"] is False
        ),
        "taiwan_news_is_scoped": (
            taiwan_news["status"] == "ready"
            and all(item["market"] == "taiwan" for item in taiwan_news["stories"])
            and taiwan_news["excluded_count"] >= 1
        ),
        "us_news_is_scoped": (
            us_news["status"] == "ready"
            and any(item["provider"] == "fed" for item in us_news["stories"])
            and all(item["market"] == "us" for item in us_news["stories"])
        ),
        "news_dedupe_is_bounded": len(taiwan_news["stories"]) <= 5,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "consensus": {
            "state": consensus["consensus_state"],
            "contributors": consensus["contributors"],
            "topic_count": len(consensus["topic_consensus"]),
            "is_investment_signal": consensus["is_investment_signal"],
        },
        "divergent_consensus": {"state": divergent["consensus_state"], "views": divergent["divergent_views"]},
        "correlation": {
            "state": correlation["correlation_state"],
            "evidence_alignment": correlation["evidence_alignment"],
            "matched_entities": sorted(
                set(correlation.get("matched_tickers") or [])
                | set(correlation.get("matched_sectors") or [])
                | set(correlation.get("matched_event_entities") or [])
            ),
        },
        "news": {
            "taiwan_count": len(taiwan_news["stories"]),
            "taiwan_excluded": taiwan_news["excluded_count"],
            "us_count": len(us_news["stories"]),
            "us_providers": sorted({item["provider"] for item in us_news["stories"]}),
        },
        "network_used": False,
        "secrets_used": False,
        "production_side_effects": False,
    }


__all__ = ["run_creator_intelligence_e2e"]
