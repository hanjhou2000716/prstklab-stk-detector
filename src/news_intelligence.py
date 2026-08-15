"""Canonical public market-news contract.

This module keeps provider identity, URL safety, relevance and deduplication
outside the UI.  It is deliberately deterministic so a release can be
replayed without contacting a provider or inventing market context.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

PROVIDER_REGISTRY: tuple[dict[str, Any], ...] = (
    # ``feed_url``/``feed_kind`` are the canonical adapter contract.  The
    # fetch layer must derive its catalog from this registry instead of
    # maintaining a second provider identity table.
    {"provider_id": "twse", "display_name": "TWSE", "authority_tier": "official", "markets": ("taiwan",), "domains": ("twse.com.tw",), "content_types": ("market_news", "company_notice"), "fetch_method": "json", "feed_url": "https://openapi.twse.com.tw/v1/news/newsList", "feed_kind": "json", "timeout_seconds": 8, "cache_ttl_seconds": 300, "enabled": True, "failure_isolation": True},
    {"provider_id": "mops", "display_name": "MOPS", "authority_tier": "official", "markets": ("taiwan",), "domains": ("mops.twse.com.tw",), "content_types": ("company_notice",), "fetch_method": "json", "feed_url": "https://mops.twse.com.tw/mops/api/t05st02", "feed_kind": "json", "timeout_seconds": 8, "cache_ttl_seconds": 300, "enabled": True, "failure_isolation": True},
    {"provider_id": "sec", "display_name": "SEC EDGAR", "authority_tier": "official", "markets": ("us",), "domains": ("sec.gov",), "content_types": ("company_filing", "market_news"), "fetch_method": "atom", "feed_url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-k&count=100&output=atom", "feed_kind": "rss", "timeout_seconds": 8, "cache_ttl_seconds": 300, "enabled": True, "failure_isolation": True},
    {"provider_id": "fed", "display_name": "Federal Reserve", "authority_tier": "official", "markets": ("us",), "domains": ("federalreserve.gov",), "content_types": ("macro_event", "market_news"), "fetch_method": "rss", "feed_url": "https://www.federalreserve.gov/feeds/press_all.xml", "feed_kind": "rss", "timeout_seconds": 8, "cache_ttl_seconds": 300, "enabled": True, "failure_isolation": True},
    {"provider_id": "nasdaq", "display_name": "Nasdaq", "authority_tier": "market", "markets": ("us",), "domains": ("nasdaq.com",), "content_types": ("market_news",), "fetch_method": "configured_endpoint", "feed_url": "", "feed_kind": "rss", "timeout_seconds": 8, "cache_ttl_seconds": 300, "enabled": False, "disabled_reason": "no stable documented public feed endpoint", "failure_isolation": True},
    {"provider_id": "anue", "display_name": "Anue", "authority_tier": "market", "markets": ("taiwan", "us"), "domains": ("cnyes.com",), "content_types": ("market_news",), "fetch_method": "html", "timeout_seconds": 15, "cache_ttl_seconds": 300, "enabled": True, "failure_isolation": True},
    {"provider_id": "google_news", "display_name": "Google News", "authority_tier": "discovery", "markets": ("taiwan", "us"), "domains": ("news.google.com",), "content_types": ("discovery",), "fetch_method": "rss", "timeout_seconds": 15, "cache_ttl_seconds": 900, "enabled": True, "failure_isolation": True},
)

_TRACKING_PARAMS = frozenset({"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid", "oc"})
_WORD_RE = re.compile(r"[^\w\u3400-\u9fff]+", re.UNICODE)


def provider_registry() -> list[dict[str, Any]]:
    """Return a serialisable copy of the canonical provider registry."""
    return [dict(item, domains=list(item["domains"]), markets=list(item["markets"])) for item in PROVIDER_REGISTRY]


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def provider_for_url(url: str) -> dict[str, Any]:
    host = _host(url)
    for provider in PROVIDER_REGISTRY:
        if any(host == domain or host.endswith("." + domain) for domain in provider["domains"]):
            return provider
    return {"provider_id": "unknown", "display_name": "未知來源", "authority_tier": "unknown", "markets": (), "domains": ()}


def canonicalize_url(url: str) -> str:
    """Remove tracking-only query parameters while preserving the public URL."""
    parsed = urlsplit(str(url).strip())
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        return ""
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key.lower() not in _TRACKING_PARAMS]
    return urlunsplit(("https", parsed.netloc.lower(), parsed.path or "/", urlencode(query), ""))


def _published(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC).isoformat()


def _headline_key(title: str) -> str:
    return _WORD_RE.sub("", str(title).casefold())


def _story_id(provider: str, canonical_url: str, title: str) -> str:
    material = f"{provider}|{canonical_url}|{_headline_key(title)}".encode()
    return f"news-{hashlib.sha256(material).hexdigest()[:20]}"


def normalize_news_story(raw: dict[str, Any], market: str | None = None) -> dict[str, Any]:
    """Normalize one public headline without trusting provider supplied labels."""
    title = " ".join(str(raw.get("title") or "").split())
    url = canonicalize_url(str(raw.get("canonical_url") or raw.get("url") or ""))
    provider = provider_for_url(url)
    chosen_market = str(market or raw.get("market") or "").strip().lower() or None
    if chosen_market not in {"taiwan", "us", "global", "cross_market", None}:
        chosen_market = None
    published = _published(raw.get("published_at") or raw.get("published"))
    tier = str(raw.get("source_tier") or provider["authority_tier"])
    authority = str(raw.get("authority_tier") or provider["authority_tier"])
    safe = bool(url and provider["provider_id"] != "unknown")
    return {
        "story_id": _story_id(provider["provider_id"], url, title),
        "provider": provider["provider_id"],
        "provider_name": provider["display_name"],
        "source_tier": tier,
        "authority_tier": authority,
        "title": title,
        "canonical_url": url,
        "url": url,
        "published_at": published,
        "market": chosen_market,
        "tickers": sorted({str(item).upper() for item in (raw.get("tickers") or []) if str(item).strip()}),
        "sectors": sorted({str(item) for item in (raw.get("sectors") or []) if str(item).strip()}),
        "topics": sorted({str(item) for item in (raw.get("topics") or []) if str(item).strip()}),
        "relevance_reasons": list(dict.fromkeys(str(item) for item in (raw.get("relevance_reasons") or []) if str(item).strip())),
        "freshness": str(raw.get("freshness") or ("published" if published else "unknown")),
        "dedupe_key": _headline_key(title),
        "public_safe": safe,
        "source": str(raw.get("source") or provider["display_name"]),
    }


def build_interest_graph(stories: Iterable[dict[str, Any]], *, tracked_tickers: Iterable[str] = (), tracked_sectors: Iterable[str] = (), topics: Iterable[str] = ()) -> dict[str, Any]:
    """Attach explicit reasons for why a story is relevant to this release."""
    ticker_set = {str(item).upper() for item in tracked_tickers}
    sector_set = {str(item).casefold() for item in tracked_sectors}
    topic_set = {str(item).casefold() for item in topics}
    graph: dict[str, Any] = {"ticker_interest": {}, "sector_interest": {}, "topic_interest": {}, "market_interest": {}}
    for story in stories:
        reasons = list(story.get("relevance_reasons") or [])
        hit_tickers = sorted(ticker_set.intersection(story.get("tickers") or []))
        hit_sectors = sorted(item for item in story.get("sectors") or [] if item.casefold() in sector_set)
        hit_topics = sorted(item for item in story.get("topics") or [] if item.casefold() in topic_set)
        if hit_tickers:
            reasons.extend(f"tracked_ticker:{item}" for item in hit_tickers)
        if hit_sectors:
            reasons.extend(f"tracked_sector:{item}" for item in hit_sectors)
        if hit_topics:
            reasons.extend(f"active_topic:{item}" for item in hit_topics)
        if story.get("market"):
            reasons.append(f"market:{story['market']}")
            graph["market_interest"].setdefault(story["market"], 0)
            graph["market_interest"][story["market"]] += 1
        story["relevance_reasons"] = list(dict.fromkeys(reasons))
        for key, values in (("ticker_interest", hit_tickers), ("sector_interest", hit_sectors), ("topic_interest", hit_topics)):
            for value in values:
                graph[key][value] = graph[key].get(value, 0) + 1
    return graph


def deduplicate_and_rank(stories: Iterable[dict[str, Any]], *, limit: int = 5, max_per_provider: int = 2) -> list[dict[str, Any]]:
    """Prefer authoritative/fresh stories and retain supporting source IDs."""
    weights = {"official": 40, "market": 25, "discovery": 10, "unknown": 0}
    groups: dict[str, dict[str, Any]] = {}
    for story in stories:
        item = normalize_news_story(story, story.get("market"))
        # Unknown or non-HTTPS sources may remain in the legacy compatibility
        # arrays for diagnostics, but can never enter the canonical public
        # intelligence contract or ranking output.
        if not item["title"] or not item["canonical_url"] or not item["public_safe"]:
            continue
        key = item["dedupe_key"] or item["canonical_url"]
        current = groups.get(key)
        score = weights.get(item["authority_tier"], 0) + min(20, len(item["relevance_reasons"]) * 5) + (5 if item["published_at"] else 0)
        item["ranking_score"] = score
        if current is None or score > current["ranking_score"]:
            if current is not None:
                item["supporting_sources"] = [{"provider": current["provider"], "url": current["canonical_url"]}, *(current.get("supporting_sources") or [])]
            groups[key] = item
        else:
            current.setdefault("supporting_sources", []).append({"provider": item["provider"], "url": item["canonical_url"]})
    ordered = sorted(groups.values(), key=lambda item: (-item["ranking_score"], item["story_id"]))
    result: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for story in ordered:
        provider = story["provider"]
        if counts.get(provider, 0) >= max_per_provider and len(ordered) - len(result) > 0:
            continue
        counts[provider] = counts.get(provider, 0) + 1
        result.append(story)
        if len(result) >= limit:
            break
    return result


def build_news_intelligence(stories: Iterable[dict[str, Any]], *, market: str | None = None, tracked_tickers: Iterable[str] = (), tracked_sectors: Iterable[str] = (), topics: Iterable[str] = (), limit: int = 5) -> dict[str, Any]:
    normalized = [normalize_news_story(story, market or story.get("market")) for story in stories]
    graph = build_interest_graph(normalized, tracked_tickers=tracked_tickers, tracked_sectors=tracked_sectors, topics=topics)
    ranked = deduplicate_and_rank(normalized, limit=limit)
    return {"schema_version": "1.0", "provider_registry": provider_registry(), "stories": ranked, "interest_graph": graph, "status": "ready" if ranked else "no_event"}

