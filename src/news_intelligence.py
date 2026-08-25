"""Canonical public market-news contract.

This module keeps provider identity, URL safety, relevance and deduplication
outside the UI.  It is deliberately deterministic so a release can be
replayed without contacting a provider or inventing market context.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from src.event_classifier import classify_event_fields

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

# Bounded aliases are used only to build deterministic identity and relevance.
# They do not classify severity and cannot qualify a notification by themselves.
_TICKER_ALIASES: dict[str, tuple[str, ...]] = {
    "NVDA": ("nvda", "nvidia", "輝達", "英偉達"),
    "TSM": ("tsm", "tsmc", "台積電", "臺積電"),
    "AMD": ("amd", "超微"),
    "AVGO": ("avgo", "broadcom", "博通"),
    "2330": ("2330", "台積電", "臺積電"),
    "TAIEX": ("taiex", "twii", "台股", "加權指數"),
    "NASDAQ": ("nasdaq", "那斯達克"),
    "SOX": ("sox", "費半", "費城半導體"),
}
_EVENT_TOPIC_ALIASES: dict[str, tuple[str, ...]] = {
    "earnings": ("earnings", "revenue", "quarterly", "財報", "獲利", "營收"),
    "guidance": ("guidance", "財測", "展望"),
    "rates": ("fed", "fomc", "rate", "利率", "央行"),
    "tariff": ("tariff", "關稅"),
    "sanctions": ("sanction", "制裁", "出口管制"),
    "energy": ("oil", "crude", "原油", "石油", "能源"),
    "conflict": ("war", "conflict", "strike", "戰爭", "衝突", "攻擊"),
    "semiconductor": ("semiconductor", "chip", "半導體", "晶片"),
    "ai": ("ai", "artificial intelligence", "人工智慧", "生成式"),
}

_SOURCE_FAILURE_STATES = frozenset({
    "failed", "rate_limited", "parse_failed", "provider_failed", "scan_failed",
    "configuration_missing", "configuration_required", "critical",
})
_SOURCE_HEALTH_FIELDS = (
    "provider", "key", "label", "status", "source_tier", "source_url",
    "item_count", "checked_at", "last_parsed_at", "latency_ms", "data_gap",
    "stale_used", "fallback_used",
)


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


def provider_supports_market(provider: dict[str, Any], market: str | None) -> bool:
    """Return whether a provider is allowed in a market-scoped news feed.

    Provider identity is evidence about coverage, not merely a display label.
    A US-only provider (for example Federal Reserve) must not leak into the
    Taiwan tab just because a caller supplied ``market="taiwan"``.  Global
    and cross-market stories remain valid in either scoped feed.
    """
    if market in (None, "global", "cross_market"):
        return True
    markets = {str(item).strip().lower() for item in (provider.get("markets") or ())}
    return market in markets or "global" in markets or "cross_market" in markets


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


def _matched_tickers(title: str, tickers: Iterable[str]) -> set[str]:
    text = str(title).casefold()
    matched = {str(item).upper() for item in tickers if str(item).strip()}
    for ticker, aliases in _TICKER_ALIASES.items():
        if any(alias in text for alias in aliases):
            matched.add(ticker)
    return matched


def _matched_topics(title: str, topics: Iterable[str]) -> set[str]:
    text = str(title).casefold()
    matched = {str(item).casefold() for item in topics if str(item).strip()}
    for topic, aliases in _EVENT_TOPIC_ALIASES.items():
        if any(alias in text for alias in aliases):
            matched.add(topic)
    return matched


def _time_bucket(value: str | None, *, minutes: int = 120) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    parsed = parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)
    bucket = parsed - timedelta(minutes=parsed.minute % minutes, seconds=parsed.second, microseconds=parsed.microsecond)
    return bucket.isoformat()


def _event_cluster_key(*, entities: Iterable[str], topics: Iterable[str], published_at: str | None) -> str:
    entities_key = ",".join(sorted({str(item).upper() for item in entities if str(item).strip()}))
    topics_key = ",".join(sorted({str(item).casefold() for item in topics if str(item).strip()}))
    # A lone generic ticker is not enough to merge different same-day stories.
    if not topics_key and "," not in entities_key:
        return ""
    material = "|".join((entities_key, topics_key, _time_bucket(published_at) or "unknown"))
    return f"event-{hashlib.sha256(material.encode()).hexdigest()[:20]}"


def _story_id(provider: str, canonical_url: str, title: str) -> str:
    material = f"{provider}|{canonical_url}|{_headline_key(title)}".encode()
    return f"news-{hashlib.sha256(material).hexdigest()[:20]}"


def _event_classification_input(raw: Mapping[str, Any], *, title: str, summary: str, description: str) -> tuple[dict[str, Any], list[str]]:
    """Build the bounded, shared-classifier input for a news story.

    News routing and event classification are deliberately separate contracts:
    the former decides which regional feed may display a story, while the
    latter uses the same evidence fields as live events.  Keep the input
    explicit so an adapter cannot accidentally classify from only a headline
    or leak an entire provider payload into a public release.
    """
    fields: dict[str, Any] = {
        "title": title,
        "summary": summary,
        "description": description,
    }
    aliases = (
        "what_happened", "event", "impact", "market_impact", "possible_impact",
        "watch", "follow_up", "event_type", "category", "topics", "tickers",
        "market_data", "market_evidence", "related_quotes", "quotes",
        "price_change", "change_percent", "direction",
    )
    for key in aliases:
        value = raw.get(key)
        if value not in (None, "", [], {}):
            fields[key] = value
    return fields, sorted(fields)


def normalize_news_story(raw: dict[str, Any], market: str | None = None) -> dict[str, Any]:
    """Normalize one public headline without trusting provider supplied labels."""
    title = " ".join(str(raw.get("title") or "").split())
    summary = " ".join(str(
        raw.get("summary")
        or raw.get("brief_summary")
        or raw.get("chinese_translation")
        or ""
    ).split())
    description = " ".join(str(raw.get("description") or raw.get("body") or "").split())
    url = canonicalize_url(str(raw.get("canonical_url") or raw.get("url") or ""))
    provider = provider_for_url(url)
    chosen_market = str(market or raw.get("market") or "").strip().lower() or None
    if chosen_market not in {"taiwan", "us", "global", "cross_market", None}:
        chosen_market = None
    published = _published(raw.get("published_at") or raw.get("published"))
    tier = str(raw.get("source_tier") or provider["authority_tier"])
    authority = str(raw.get("authority_tier") or provider["authority_tier"])
    safe = bool(url and provider["provider_id"] != "unknown")
    market_compatible = provider_supports_market(provider, chosen_market)
    raw_tickers = sorted({str(item).upper() for item in (raw.get("tickers") or []) if str(item).strip()})
    raw_topics = sorted({str(item) for item in (raw.get("topics") or []) if str(item).strip()})
    entities = sorted(_matched_tickers(title, raw_tickers))
    topics_normalized = sorted(_matched_topics(title, raw_topics))
    classifier_input, classifier_fields = _event_classification_input(
        raw, title=title, summary=summary, description=description,
    )
    classification = classify_event_fields(classifier_input)
    # ``text`` is an internal haystack and must never be copied into a release
    # artifact.  The public subset is enough to reproduce the decision and to
    # show why the news story and live event took the same classification path.
    event_classification = {
        "schema_version": "1.0",
        "classifier": "src.event_classifier.classify_event_fields",
        "category": classification.get("category"),
        "reason": str(classification.get("reason") or "keyword_no_match"),
        "matched_terms": [str(item) for item in (classification.get("matched_terms") or []) if str(item).strip()],
        "input_fields": classifier_fields,
    }
    return {
        "story_id": _story_id(provider["provider_id"], url, title),
        "provider": provider["provider_id"],
        "provider_name": provider["display_name"],
        "source_tier": tier,
        "authority_tier": authority,
        "title": title,
        "summary": summary,
        "description": description,
        "canonical_url": url,
        "url": url,
        "published_at": published,
        "market": chosen_market,
        "market_compatible": market_compatible,
        "tickers": raw_tickers,
        "entities": entities,
        "sectors": sorted({str(item) for item in (raw.get("sectors") or []) if str(item).strip()}),
        "topics": topics_normalized,
        "event_classification": event_classification,
        "relevance_reasons": list(dict.fromkeys(str(item) for item in (raw.get("relevance_reasons") or []) if str(item).strip())),
        "freshness": str(raw.get("freshness") or ("published" if published else "unknown")),
        "dedupe_key": _headline_key(title),
        "event_cluster_key": _event_cluster_key(entities=entities, topics=topics_normalized, published_at=published),
        "published_time_bucket": _time_bucket(published),
        "public_safe": safe,
        "source": str(raw.get("source") or provider["display_name"]),
    }


def build_interest_graph(
    stories: Iterable[dict[str, Any]],
    *,
    tracked_tickers: Iterable[str] = (),
    tracked_sectors: Iterable[str] = (),
    topics: Iterable[str] = (),
    research_tickers: Iterable[str] = (),
    active_event_topics: Iterable[str] = (),
    creator_mentions: Iterable[str] = (),
) -> dict[str, Any]:
    """Attach auditable reasons for why a story is relevant to this release.

    Context is supplied by the producer rather than inferred by the frontend.
    Ticker/topic matching intentionally scans the normalized title and
    summary as well as structured fields so RSS stories without entity tags
    can still be linked to a tracked candidate.  The source buckets are
    additive and never change market routing or risk severity.
    """
    ticker_set = {str(item).upper() for item in tracked_tickers if str(item).strip()}
    research_set = {str(item).upper() for item in research_tickers if str(item).strip()}
    sector_set = {str(item).casefold() for item in tracked_sectors if str(item).strip()}
    topic_set = {str(item).casefold() for item in topics if str(item).strip()}
    event_set = {str(item).casefold() for item in active_event_topics if str(item).strip()}
    creator_set = {str(item).casefold() for item in creator_mentions if str(item).strip()}
    graph: dict[str, Any] = {
        "ticker_interest": {},
        "sector_interest": {},
        "topic_interest": {},
        "market_interest": {},
        "context": {
            "tracked_tickers": sorted(ticker_set),
            "research_tickers": sorted(research_set),
            "tracked_sectors": sorted(sector_set),
            "active_event_topics": sorted(event_set),
            "creator_mentions": sorted(creator_set),
        },
        "source_interest": {
            "tracked_ticker": {},
            "research_candidate": {},
            "tracked_sector": {},
            "active_event": {},
            "creator_mentioned": {},
        },
    }
    for story in stories:
        reasons = list(story.get("relevance_reasons") or [])
        text = " ".join(
            str(story.get(field) or "")
            for field in ("title", "summary", "description")
        ).casefold()
        story_tickers = {str(item).upper() for item in story.get("tickers") or []}
        def ticker_hit(ticker: str, haystack: str = text, tagged: set[str] = story_tickers) -> bool:
            aliases = _TICKER_ALIASES.get(ticker, (ticker,))
            return ticker in tagged or any(alias.casefold() in haystack for alias in aliases)

        hit_tickers = sorted(ticker for ticker in ticker_set if ticker_hit(ticker))
        hit_research = sorted(ticker for ticker in research_set if ticker_hit(ticker))
        hit_sectors = sorted(
            item for item in sector_set
            if item in {str(value).casefold() for value in story.get("sectors") or []}
            or item in text
        )
        hit_topics = sorted(
            item for item in topic_set
            if item in {str(value).casefold() for value in story.get("topics") or []}
            or item in text
        )
        hit_events = sorted(item for item in event_set if item in text)
        hit_creators = sorted(item for item in creator_set if item in text)
        if hit_tickers:
            reasons.extend(f"tracked_ticker:{item}" for item in hit_tickers)
        if hit_research:
            reasons.extend(f"research_candidate:{item}" for item in hit_research)
        if hit_sectors:
            reasons.extend(f"tracked_sector:{item}" for item in hit_sectors)
        if hit_topics:
            reasons.extend(f"active_topic:{item}" for item in hit_topics)
        if hit_events:
            reasons.extend(f"active_event:{item}" for item in hit_events)
        if hit_creators:
            reasons.extend(f"creator_mentioned:{item}" for item in hit_creators)
        if story.get("market"):
            reasons.append(f"market:{story['market']}")
            graph["market_interest"].setdefault(story["market"], 0)
            graph["market_interest"][story["market"]] += 1
        story["relevance_reasons"] = list(dict.fromkeys(reasons))
        for key, values in (
            ("ticker_interest", sorted(set(hit_tickers) | set(hit_research))),
            ("sector_interest", hit_sectors),
            ("topic_interest", sorted(set(hit_topics) | set(hit_events))),
        ):
            for value in values:
                graph[key][value] = graph[key].get(value, 0) + 1
        for bucket, values in (
            ("tracked_ticker", hit_tickers),
            ("research_candidate", hit_research),
            ("tracked_sector", hit_sectors),
            ("active_event", hit_events),
            ("creator_mentioned", hit_creators),
        ):
            for value in values:
                graph["source_interest"][bucket][value] = graph["source_interest"][bucket].get(value, 0) + 1
    return graph


def deduplicate_and_rank(stories: Iterable[dict[str, Any]], *, limit: int = 5, max_per_provider: int = 2) -> list[dict[str, Any]]:
    """Prefer authoritative/fresh stories and retain supporting source IDs."""
    weights = {"official": 40, "market": 25, "discovery": 10, "unknown": 0}
    groups: list[dict[str, Any]] = []
    for story in stories:
        item = normalize_news_story(story, story.get("market"))
        # Unknown or non-HTTPS sources may remain in the legacy compatibility
        # arrays for diagnostics, but can never enter the canonical public
        # intelligence contract or ranking output.
        if not item["title"] or not item["canonical_url"] or not item["public_safe"] or not item["market_compatible"]:
            continue
        key = item["dedupe_key"] or item["canonical_url"]
        current = next((candidate for candidate in groups if candidate.get("dedupe_key") == key or (
            item.get("event_cluster_key") and candidate.get("event_cluster_key") == item.get("event_cluster_key")
        )), None)
        score = weights.get(item["authority_tier"], 0) + min(20, len(item["relevance_reasons"]) * 5) + (5 if item["published_at"] else 0)
        item["ranking_score"] = score
        if current is None or score > current["ranking_score"]:
            if current is not None:
                item["supporting_sources"] = [{"provider": current["provider"], "url": current["canonical_url"]}, *(current.get("supporting_sources") or [])]
                groups[groups.index(current)] = item
            else:
                groups.append(item)
        else:
            current.setdefault("supporting_sources", []).append({"provider": item["provider"], "url": item["canonical_url"]})
    ordered = sorted(groups, key=lambda item: (-item["ranking_score"], item["story_id"]))
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


def summarize_source_diversity(stories: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Summarize independent evidence behind the ranked news stories.

    A provider count alone is not sufficient: two aliases can resolve to the
    same domain, while one story can carry an independently retained source in
    ``supporting_sources``.  The public contract therefore counts canonical
    source domains (falling back to provider IDs when a supporting URL is not
    available) and makes the cross-check state explicit.  This is descriptive
    evidence only; it never upgrades event severity or qualifies an alert.
    """
    providers: set[str] = set()
    domains: set[str] = set()
    supporting_count = 0

    def add_source(provider: Any, url: Any) -> None:
        provider_id = str(provider or "").strip().casefold()
        host = _host(str(url or ""))
        if host:
            domains.add(host)
        elif provider_id:
            providers.add(provider_id)

    materialized = [item for item in stories if isinstance(item, dict)]
    for story in materialized:
        provider = story.get("provider")
        if provider:
            providers.add(str(provider).strip().casefold())
        add_source(provider, story.get("canonical_url") or story.get("url"))
        supporting = story.get("supporting_sources")
        if not isinstance(supporting, list):
            continue
        for source in supporting:
            if not isinstance(source, Mapping):
                continue
            supporting_count += 1
            provider = source.get("provider")
            if provider:
                providers.add(str(provider).strip().casefold())
            add_source(provider, source.get("url") or source.get("canonical_url"))

    independent_count = len(domains) or len(providers)
    status = (
        "no_event" if not materialized
        else "multi_source" if independent_count >= 2
        else "single_source"
    )
    return {
        "schema_version": "1.0",
        "status": status,
        "cross_checked": independent_count >= 2,
        "minimum_required": 2,
        "independent_source_count": independent_count,
        "provider_count": len(providers),
        "provider_ids": sorted(providers),
        "source_domains": sorted(domains),
        "supporting_source_count": supporting_count,
    }


def build_news_intelligence(
    stories: Iterable[dict[str, Any]],
    *,
    market: str | None = None,
    tracked_tickers: Iterable[str] = (),
    tracked_sectors: Iterable[str] = (),
    topics: Iterable[str] = (),
    research_tickers: Iterable[str] = (),
    active_event_topics: Iterable[str] = (),
    creator_mentions: Iterable[str] = (),
    source_health: Iterable[Mapping[str, Any]] | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    normalized = [normalize_news_story(story, market or story.get("market")) for story in stories]
    graph = build_interest_graph(
        normalized,
        tracked_tickers=tracked_tickers,
        tracked_sectors=tracked_sectors,
        topics=topics,
        research_tickers=research_tickers,
        active_event_topics=active_event_topics,
        creator_mentions=creator_mentions,
    )
    ranked = deduplicate_and_rank(normalized, limit=limit)
    source_diversity = summarize_source_diversity(ranked)
    excluded = [item for item in normalized if item.get("market_compatible") is False]
    health_rows: list[dict[str, Any]] = []
    for raw_health in source_health or ():
        if not isinstance(raw_health, Mapping):
            continue
        # Keep only the public source-health contract.  In particular, do not
        # copy provider exceptions, response bodies, or request headers into a
        # release-bound artifact.
        row = {
            field: raw_health[field]
            for field in _SOURCE_HEALTH_FIELDS
            if field in raw_health and raw_health[field] is not None
        }
        if row:
            health_rows.append(row)
    failure_count = sum(
        1 for row in health_rows
        if str(row.get("status") or "").casefold() in _SOURCE_FAILURE_STATES
    )
    if ranked:
        collection_state = "degraded" if failure_count else "ready"
    elif failure_count:
        collection_state = "source_failed"
    elif health_rows:
        collection_state = "no_event"
    else:
        collection_state = "no_event"
    return {
        "schema_version": "1.0",
        "provider_registry": provider_registry(),
        "stories": ranked,
        "source_diversity": source_diversity,
        "interest_graph": graph,
        "excluded_count": len(excluded),
        "exclusion_reasons": {"market_scope_mismatch": len(excluded)} if excluded else {},
        "status": "ready" if ranked else "no_event",
        "collection_state": collection_state,
        "source_failure_count": failure_count,
        "source_health": health_rows,
    }

