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
    # Reuters and GDELT are corroboration/discovery identities.  They are
    # intentionally not enabled as official feeds: a story may be accepted
    # from a public URL, but neither provider can silently become an official
    # fact source or bypass the cross-check/release gate.
    {"provider_id": "reuters", "display_name": "Reuters", "authority_tier": "trusted_media", "markets": ("global", "taiwan", "us"), "domains": ("reuters.com",), "content_types": ("discovery", "market_news"), "fetch_method": "public_url", "cache_ttl_seconds": 900, "enabled": False, "disabled_reason": "no stable documented public feed endpoint; use as corroboration", "failure_isolation": True},
    {"provider_id": "gdelt", "display_name": "GDELT", "authority_tier": "discovery", "markets": ("global", "taiwan", "us"), "domains": ("gdeltproject.org",), "content_types": ("discovery",), "fetch_method": "configured_endpoint", "cache_ttl_seconds": 900, "enabled": False, "disabled_reason": "discovery-only endpoint; bounded backoff and cache policy applies", "failure_isolation": True},
    {"provider_id": "nasdaq", "display_name": "Nasdaq", "authority_tier": "market", "markets": ("us",), "domains": ("nasdaq.com",), "content_types": ("market_news",), "fetch_method": "configured_endpoint", "feed_url": "", "feed_kind": "rss", "timeout_seconds": 8, "cache_ttl_seconds": 300, "enabled": False, "disabled_reason": "no stable documented public feed endpoint", "failure_isolation": True},
    {"provider_id": "anue", "display_name": "Anue", "authority_tier": "market", "markets": ("taiwan", "us"), "domains": ("cnyes.com",), "content_types": ("market_news",), "fetch_method": "html", "timeout_seconds": 15, "cache_ttl_seconds": 300, "enabled": True, "failure_isolation": True},
    {"provider_id": "yahoo_finance", "display_name": "Yahoo Taiwan Finance", "authority_tier": "market", "markets": ("taiwan", "us"), "domains": ("finance.yahoo.com", "tw.stock.yahoo.com"), "content_types": ("market_news",), "fetch_method": "rss", "timeout_seconds": 15, "cache_ttl_seconds": 300, "enabled": True, "failure_isolation": True},
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
    "provider", "key", "legacy_key", "label", "status", "source_tier", "source_url",
    "item_count", "checked_at", "last_parsed_at", "latency_ms", "data_gap",
    "stale_used", "fallback_used", "raw_item_count", "filtered_item_count", "funnel",
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


def _alias_matches(text: str, alias: str) -> bool:
    """Match Latin identifiers as tokens, avoiding false substring hits."""
    normalized = str(alias).casefold().strip()
    if not normalized:
        return False
    if re.fullmatch(r"[a-z0-9]+", normalized):
        return re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", text) is not None
    return normalized in text


_SEC_FORM_ONLY_RE = re.compile(r"^\s*(?:[1-9]\d*-[A-Z]+|8-K|6-K)\s*[-:]?.*\(\s*filer\s*\)\s*$", re.IGNORECASE)
_LISTICLE_RE = re.compile(
    r"\b(?:in\s+focus|top\s+pick|stocks?\s+to\s+buy|these\s+\d+|how\s+to\s+invest|best\s+stocks?)\b"
    r"|(?:選股|最受惠|目標價完整看|買進時機|投資早知道)",
    re.IGNORECASE,
)
_TICKER_LIST_RE = re.compile(
    r"^\s*(?:ticker\s+list|watchlist|symbols?)\s*[:：-]"
    r"|\b(?:stocks?|tickers?)\s*[:：-]\s*(?:[A-Z]{1,5}(?:\s+|,|/)){2,}",
    re.IGNORECASE,
)
_MARKET_MATERIAL_RE = re.compile(
    r"\b(?:rise|rises|fell|fall|higher|lower|surge|surges|jump|jumps|drop|drops|"
    r"rally|rallies|selloff|sell-off|record|records|volatile|volatility|futures|"
    r"yield|yields|rate|rates|jobs|payroll|inflation|tariff|sanction|oil|crude)\b"
    r"|(?:上漲|下跌|暴漲|暴跌|殖利率|利率|通膨|就業|非農|關稅|制裁|原油|油價|能源)",
    re.IGNORECASE,
)
_US_INDEX_RE = re.compile(r"\b(?:nasdaq|s&p\s*500|sp500|sox|nyse|dow\s+jones)\b|(?:那斯達克|標普|費半|道瓊)", re.IGNORECASE)
_SPECIFIC_MARKET_CAUSE_RE = re.compile(
    r"\b(?:after|as|due to|because|jobs?|payrolls?|earnings?|inflation|rates?|yield|yields|fed|oil|tariff|sanction|guidance|data|forecast)\b"
    r"|(?:因|由於|由…|數據|數據|財報|通膨|利率|殖利率|就業|非農|油價|制裁|財測|展望)",
    re.IGNORECASE,
)
_COMPANY_ACTION_RE = re.compile(
    r"\b(?:announces?|reported?|reports?|earnings?|guidance|outlook|revenue|"
    r"profit|loss|acquisition|merger|capex|orders?|forecast|results?)\b"
    r"|(?:財報|財測|展望|營收|獲利|併購|資本支出|訂單|預測|公布)",
    re.IGNORECASE,
)
_MATERIAL_CATEGORIES = frozenset({"fed", "macro", "policy", "conflict", "energy", "semiconductor", "market"})
NEWS_ELIGIBILITY_RULESET = "public_market_news_gate_v2"
NEWS_SELECTION_LANES = frozenset({"current", "inventory"})


def _public_news_decision(item: dict[str, Any]) -> tuple[bool, str | None, list[str], str]:
    """Apply the investor-facing US/Taiwan news quality gate.

    Provider authority and a market label are useful evidence, but neither is
    sufficient public decision value.  Keep the gate deterministic and retain
    its reason in the release so exclusions can be audited without exposing
    provider payloads.
    """
    title = " ".join(str(item.get(field) or "") for field in ("title", "summary", "description"))
    provider = str(item.get("provider") or "").casefold()
    source_tier = str(item.get("source_tier") or "").casefold()
    category = str((item.get("event_classification") or {}).get("category") or "").casefold()
    reasons = [str(reason) for reason in item.get("relevance_reasons") or [] if str(reason).strip()]
    contextual = [reason for reason in reasons if not reason.startswith("market:")]
    flags: list[str] = []
    eligibility: list[str] = []

    if not item.get("canonical_url"):
        return False, "unsafe_url", flags, "unclassified"
    if not item.get("market_compatible"):
        return False, "market_scope_mismatch", flags, "unclassified"
    if not item.get("published_at") and source_tier in {"market", "discovery"}:
        flags.append("missing_published_at")
        return False, "missing_published_at", flags, "unclassified"
    if provider == "sec" and _SEC_FORM_ONLY_RE.search(title):
        flags.append("sec_form_only")
        return False, "generic_official_filing", flags, "unclassified"
    if _LISTICLE_RE.search(title):
        flags.append("listicle_or_selection")
        return False, "listicle_or_selection", flags, "unclassified"
    if _TICKER_LIST_RE.search(title):
        flags.append("ticker_list")
        return False, "listicle_or_selection", flags, "unclassified"

    has_tracked_entity = any(
        reason.startswith(("tracked_ticker:", "research_candidate:", "tracked_sector:"))
        for reason in contextual
    ) or bool(item.get("entities"))
    has_active_topic = any(reason.startswith(("active_event:", "active_topic:")) for reason in contextual)
    has_category = category in _MATERIAL_CATEGORIES
    has_market_fact = bool(_MARKET_MATERIAL_RE.search(title))
    has_company_fact = has_tracked_entity and bool(_COMPANY_ACTION_RE.search(title))
    has_specific_index_event = bool(_US_INDEX_RE.search(title) and _SPECIFIC_MARKET_CAUSE_RE.search(title))
    has_specific_macro_event = bool(_SPECIFIC_MARKET_CAUSE_RE.search(title) and has_market_fact)

    if has_category:
        eligibility.append(f"event_category:{category}")
    if has_tracked_entity:
        eligibility.append("tracked_entity")
    if has_active_topic:
        eligibility.append("active_topic")
    if has_market_fact:
        eligibility.append("concrete_market_fact")
    if has_company_fact:
        eligibility.append("concrete_company_event")
    if has_specific_index_event or has_specific_macro_event:
        eligibility.append("concrete_market_event")

    if not (has_category or has_company_fact or has_specific_index_event or has_specific_macro_event or (has_active_topic and has_market_fact)):
        flags.append("no_material_market_relevance")
        # SEC rows remain available for audit, but a filing without a concrete
        # event fact is the generic-filing class used by legacy diagnostics.
        reason = "generic_official_filing" if provider == "sec" else "insufficient_market_relevance"
        return False, reason, flags, "unclassified"

    if category in {"fed", "macro"}:
        value_class = "macro"
    elif category == "semiconductor":
        value_class = "semiconductor_ai"
    elif category == "energy":
        value_class = "energy"
    elif category in {"conflict", "policy"}:
        value_class = "geopolitics_policy"
    elif has_company_fact:
        value_class = "company_event"
    else:
        value_class = "market_context"
    return True, None, flags, value_class


def _matched_tickers(title: str, tickers: Iterable[str]) -> set[str]:
    text = str(title).casefold()
    matched = {str(item).upper() for item in tickers if str(item).strip()}
    for ticker, aliases in _TICKER_ALIASES.items():
        if any(_alias_matches(text, alias) for alias in aliases):
            matched.add(ticker)
    return matched


def _matched_topics(title: str, topics: Iterable[str]) -> set[str]:
    text = str(title).casefold()
    matched = {str(item).casefold() for item in topics if str(item).strip()}
    for topic, aliases in _EVENT_TOPIC_ALIASES.items():
        if any(_alias_matches(text, alias) for alias in aliases):
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
    selection_lane = str(raw.get("selection_lane") or "current").strip().casefold()
    if selection_lane not in NEWS_SELECTION_LANES:
        selection_lane = "current"
    inventory_age = raw.get("inventory_age_trading_sessions")
    try:
        inventory_age = int(str(inventory_age)) if inventory_age not in (None, "") else None
    except (TypeError, ValueError):
        inventory_age = None
    inventory_saved_at = _published(raw.get("inventory_saved_at"))
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
        "public_news_eligible": bool(raw.get("public_news_eligible", safe and market_compatible)),
        "decision_value_class": raw.get("decision_value_class", ""),
        "quality_flags": [str(item) for item in (raw.get("quality_flags") or []) if str(item).strip()],
        "eligibility_reasons": [str(item) for item in (raw.get("eligibility_reasons") or []) if str(item).strip()],
        "exclusion_reason": raw.get("exclusion_reason"),
        "source": str(raw.get("source") or provider["display_name"]),
        # Public market/discovery headlines are useful observations, but they
        # are never confirmation evidence by themselves.  Keep this explicit
        # in the release so downstream cards and alert gates cannot infer a
        # stronger state from a provider label.
        "evidence_state": "official" if authority == "official" else "observation",
        "confirmation_required": authority != "official",
        "selection_lane": selection_lane,
        "inventory_used": bool(raw.get("inventory_used", selection_lane == "inventory")),
        "inventory_age_trading_sessions": inventory_age,
        "inventory_saved_at": inventory_saved_at,
        "eligibility_ruleset": str(raw.get("eligibility_ruleset") or NEWS_ELIGIBILITY_RULESET),
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
            return ticker in tagged or any(_alias_matches(haystack, alias) for alias in aliases)

        hit_tickers = sorted(ticker for ticker in ticker_set if ticker_hit(ticker))
        hit_research = sorted(ticker for ticker in research_set if ticker_hit(ticker))
        hit_sectors = sorted(
            item for item in sector_set
            if item in {str(value).casefold() for value in story.get("sectors") or []}
            or _alias_matches(text, item)
        )
        hit_topics = sorted(
            item for item in topic_set
            if item in {str(value).casefold() for value in story.get("topics") or []}
            or _alias_matches(text, item)
        )
        hit_events = sorted(item for item in event_set if _alias_matches(text, item))
        hit_creators = sorted(item for item in creator_set if _alias_matches(text, item))
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
        ) or (
            item.get("canonical_url") and candidate.get("canonical_url") == item.get("canonical_url")
        )), None)
        # SEC is authoritative for filings, but authority alone is not topical
        # relevance.  A generic 8-K with only ``market:us`` must not outrank a
        # tracked ticker, research candidate, or active event topic.
        contextual_reasons = [
            reason for reason in item["relevance_reasons"]
            if not str(reason).startswith("market:")
        ]
        generic_sec = item["provider"] == "sec" and not contextual_reasons and not item.get("entities") and not item.get("topics")
        # Current-run evidence always fills before retained inventory.  The
        # lane bonus is deliberately larger than authority/relevance weights:
        # inventory can supplement a sparse run, but it cannot displace a
        # current eligible story merely because an older provider has a
        # higher tier label.
        lane_bonus = 100 if item.get("selection_lane") == "current" else 0
        inventory_age = item.get("inventory_age_trading_sessions")
        inventory_penalty = 0
        if item.get("selection_lane") == "inventory":
            try:
                inventory_penalty = min(12, max(0, int(inventory_age or 1) - 1) * 3)
            except (TypeError, ValueError):
                inventory_penalty = 12
        score = lane_bonus + weights.get(item["authority_tier"], 0) + min(20, len(contextual_reasons) * 5) + (5 if item["published_at"] else 0) - inventory_penalty
        if generic_sec:
            score -= 35
            item["relevance_class"] = "generic_official_filing"
        else:
            item["relevance_class"] = "contextual"
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
    selected_ids: set[str] = set()
    # First pass is diversity-first: every eligible provider gets one slot.
    for story in ordered:
        provider = story["provider"]
        if provider in counts:
            continue
        result.append(story)
        selected_ids.add(story["story_id"])
        counts[provider] = 1
        if len(result) >= limit:
            return result
    # Second pass honours the historical per-provider cap.
    for story in ordered:
        if story["story_id"] in selected_ids:
            continue
        provider = story["provider"]
        if counts.get(provider, 0) >= max_per_provider:
            continue
        result.append(story)
        selected_ids.add(story["story_id"])
        counts[provider] = counts.get(provider, 0) + 1
        if len(result) >= limit:
            return result
    # Final fill pass prevents a provider cap from making a healthy feed look
    # empty.  Safety, URL validation and ranking have already happened above.
    for story in ordered:
        if story["story_id"] in selected_ids:
            continue
        result.append(story)
        selected_ids.add(story["story_id"])
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


def _news_provider_observability(
    normalized: list[dict[str, Any]],
    deduped: list[dict[str, Any]],
    ranked: list[dict[str, Any]],
    health_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build bounded provider metrics for source-health and release audits.

    Counts are derived from the same normalized stories that feed ranking.  A
    provider cannot report a healthy ingestion count merely by returning an
    HTTP 200 response, and failed providers remain visible even when another
    provider supplies the ranked result.
    """
    def by_provider(rows: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            provider = str(row.get("provider") or "unknown").strip().casefold()
            grouped.setdefault(provider, []).append(row)
        return grouped

    normalized_by = by_provider(normalized)
    deduped_by = by_provider(deduped)
    ranked_by = by_provider(ranked)

    def relevance_distribution(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
        distribution: dict[str, int] = {}
        for row in rows:
            buckets = {
                str(reason).split(":", 1)[0]
                for reason in row.get("relevance_reasons") or []
                if str(reason).strip()
            }
            if not buckets:
                buckets = {"unmatched"}
            for bucket in sorted(buckets):
                distribution[bucket] = distribution.get(bucket, 0) + 1
        return dict(sorted(distribution.items()))

    provider_ids = set(normalized_by) | set(deduped_by) | set(ranked_by)
    health_by = by_provider(health_rows)
    provider_ids.update(health_by)
    rows: list[dict[str, Any]] = []
    for provider in sorted(provider_ids):
        source = health_by.get(provider, [{}])[-1]
        status = str(source.get("status") or ("healthy" if normalized_by.get(provider) else "no_event"))
        checked_at = source.get("checked_at")
        success = source.get("last_success_at")
        failure = source.get("last_failure_at")
        if success is None and status in {"healthy", "no_event", "stale", "disabled"}:
            success = checked_at
        if failure is None and status in _SOURCE_FAILURE_STATES:
            failure = checked_at
        raw_fetched_count = source.get("item_count")
        try:
            fetched_count = max(
                int(str(raw_fetched_count)) if raw_fetched_count is not None else 0,
                len(normalized_by.get(provider, [])),
            )
        except (TypeError, ValueError):
            fetched_count = len(normalized_by.get(provider, []))
        normalized_count = len(normalized_by.get(provider, []))
        compatible_count = sum(1 for item in normalized_by.get(provider, []) if item.get("market_compatible") is not False)
        eligible_count = sum(1 for item in normalized_by.get(provider, []) if item.get("public_news_eligible", True))
        funnel = {
            "fetched_count": fetched_count,
            "normalized_count": normalized_count,
            "market_compatible_count": compatible_count,
            "eligible_count": eligible_count,
            "excluded_count": max(normalized_count - eligible_count, 0),
            "deduped_count": len(deduped_by.get(provider, [])),
            "ranked_count": len(ranked_by.get(provider, [])),
        }
        rows.append({
            "provider": provider,
            "status": status,
            "last_success_at": success,
            "last_failure_at": failure,
            "stories_ingested": len(normalized_by.get(provider, [])),
            "stories_deduped": len(deduped_by.get(provider, [])),
            "ranked_count": len(ranked_by.get(provider, [])),
            "relevance_distribution": relevance_distribution(normalized_by.get(provider, [])),
            "funnel": funnel,
        })
    return {
        "stories_ingested": len(normalized),
        "stories_deduped": len(deduped),
        "ranked_count": len(ranked),
        "relevance_distribution": relevance_distribution(normalized),
        "providers": rows,
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
    inventory_stories: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    current_raw = [dict(story) for story in stories if isinstance(story, dict)]
    inventory_raw = [dict(story) for story in inventory_stories if isinstance(story, dict)]
    if str(market or "").casefold() != "us":
        inventory_raw = []
    for story in current_raw:
        story.setdefault("selection_lane", "current")
        story.setdefault("inventory_used", False)
        story.setdefault("eligibility_ruleset", NEWS_ELIGIBILITY_RULESET)
    for story in inventory_raw:
        story["selection_lane"] = "inventory"
        story["inventory_used"] = True
        story.setdefault("eligibility_ruleset", NEWS_ELIGIBILITY_RULESET)
    normalized_current = [normalize_news_story(story, market or story.get("market")) for story in current_raw]
    normalized_inventory = [normalize_news_story(story, market or story.get("market")) for story in inventory_raw]
    normalized = [*normalized_current, *normalized_inventory]
    graph = build_interest_graph(
        normalized,
        tracked_tickers=tracked_tickers,
        tracked_sectors=tracked_sectors,
        topics=topics,
        research_tickers=research_tickers,
        active_event_topics=active_event_topics,
        creator_mentions=creator_mentions,
    )
    for item in normalized:
        is_eligible, exclusion_reason, quality_flags, value_class = _public_news_decision(item)
        item["public_news_eligible"] = is_eligible
        item["decision_value_class"] = value_class
        item["quality_flags"] = quality_flags
        item["eligibility_reasons"] = [
            str(reason) for reason in item.get("eligibility_reasons") or [] if str(reason).strip()
        ]
        if is_eligible:
            item["eligibility_reasons"] = list(dict.fromkeys([
                *item["eligibility_reasons"], "public_market_news_gate",
            ]))
            item["relevance_class"] = "contextual"
        else:
            item["exclusion_reason"] = exclusion_reason
            item["relevance_class"] = exclusion_reason or "excluded"
    eligible = [item for item in normalized_current if item.get("public_news_eligible", True)]
    inventory_eligible = [item for item in normalized_inventory if item.get("public_news_eligible", True)]
    ranked_current = deduplicate_and_rank(eligible, limit=limit)
    ranked_inventory = deduplicate_and_rank(
        inventory_eligible, limit=max(len(inventory_eligible), 1), max_per_provider=max(len(inventory_eligible), 1),
    )
    # Current stories are authoritative for this run.  Inventory only fills
    # unused slots, and duplicate event/article identities are suppressed.
    ranked: list[dict[str, Any]] = []
    seen_identity_keys: set[str] = set()
    for item in [*ranked_current, *ranked_inventory]:
        identity_keys = {
            str(item.get(key) or "").strip()
            for key in ("event_cluster_key", "dedupe_key", "canonical_url")
            if str(item.get(key) or "").strip()
        }
        if identity_keys & seen_identity_keys:
            continue
        ranked.append(item)
        seen_identity_keys.update(identity_keys)
        if len(ranked) >= limit:
            break
    deduped = deduplicate_and_rank(
        eligible,
        limit=max(len(eligible), 1),
        max_per_provider=max(len(eligible), 1),
    )
    # Source diversity is evidence about the current scan only.  Retained
    # inventory must never masquerade as same-run corroboration.
    source_diversity = summarize_source_diversity(ranked_current)
    excluded = [item for item in normalized_current if item.get("market_compatible") is False or item.get("public_news_eligible") is False]
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
    # The market aggregate row is derived from the provider rows and must not
    # count as a second failure.  A failed SEC/Fed endpoint alongside a
    # healthy discovery feed is a degraded scan, not a completely unavailable
    # market feed.
    aggregate_key = f"news_{market}" if market else ""
    provider_health = [
        row for row in health_rows
        if str(row.get("key") or "") != aggregate_key
    ]
    observability = _news_provider_observability(normalized_current, deduped, ranked_current, provider_health)
    health_by_provider = {
        str(row.get("provider") or "").casefold(): row
        for row in provider_health
        if str(row.get("provider") or "").strip()
    }
    for provider_metrics in observability["providers"]:
        source = health_by_provider.get(provider_metrics["provider"])
        if source is not None:
            source.update({
                key: provider_metrics[key]
                for key in (
                    "last_success_at", "last_failure_at", "stories_ingested",
                    "stories_deduped", "ranked_count", "relevance_distribution", "funnel",
                )
            })
    failure_count = sum(
        1 for row in provider_health
        if str(row.get("status") or "").casefold() in _SOURCE_FAILURE_STATES
    )
    success_count = sum(
        1 for row in provider_health
        if str(row.get("status") or "").casefold() in {"healthy", "no_event", "stale"}
    )
    disabled_count = sum(
        1 for row in provider_health
        if str(row.get("status") or "").casefold() == "disabled"
    )
    scan_summary = {
        "provider_count": len(provider_health),
        "successful_provider_count": success_count,
        "failed_provider_count": failure_count,
        "disabled_provider_count": disabled_count,
        # Keep concise funnel keys for the public audit contract alongside the
        # older *_story_count names consumed by existing readers.
        "fetched": len(normalized_current),
        "normalized": len(normalized_current),
        "eligible": len(eligible),
        "excluded": len(excluded),
        "deduped": len(deduped),
        "publicly_ranked": len(ranked),
        "current_eligible": len(eligible),
        "inventory_considered": len(normalized_inventory),
        "inventory_eligible": len(inventory_eligible),
        "inventory_selected": sum(1 for item in ranked if item.get("selection_lane") == "inventory"),
        "final_public_count": len(ranked),
        "filtered_story_count": len(excluded),
        "fetched_story_count": len(normalized_current),
        "normalized_story_count": len(normalized_current),
        "eligible_story_count": len(eligible),
        "deduped_story_count": len(deduped),
        "ranked_story_count": len(ranked),
    }
    if ranked:
        collection_state = "degraded" if failure_count else "ready"
    elif failure_count:
        collection_state = "degraded" if success_count else "source_failed"
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
        "exclusion_reasons": dict(sorted({
            str(item.get("exclusion_reason") or "excluded"): sum(
                1 for candidate in normalized
                if not candidate.get("public_news_eligible", True)
                and str(candidate.get("exclusion_reason") or "excluded") == str(item.get("exclusion_reason") or "excluded")
            )
            for item in normalized_current
            if not item.get("public_news_eligible", True)
        }.items())),
        "status": "ready" if ranked else "no_event",
        "collection_state": collection_state,
        "source_failure_count": failure_count,
        "scan_summary": scan_summary,
        "inventory": {
            "enabled": str(market or "").casefold() == "us",
            "retention_trading_sessions": 3,
            "max_calendar_days": 7,
            "considered": len(normalized_inventory),
            "eligible": len(inventory_eligible),
            "selected": sum(1 for item in ranked if item.get("selection_lane") == "inventory"),
        },
        "source_health": health_rows,
        "observability": observability,
    }

