"""Deterministic multi-source market briefings.

The digest is deliberately rule based.  It combines already reviewed market
observations and public events into one release-bound object; it never invents
facts, infers causality, or calls an external model.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from src.market_assessment import (
    build_market_assessment,
    normalize_headline,
    project_overview,
    project_public_message,
    topic_label,
)
from src.market_scope import SCOPE_TICKERS, market_scope_for_slot, scope_snapshot
from src.telegram_client import PUBLIC_SUMMARY_VERSION

PUBLIC_MESSAGE_MAX_CHARS = 60
DASHBOARD_SUMMARY_MAX_CHARS = 140
_UNUSABLE_FRESHNESS = frozenset({"stale", "delayed", "unavailable", "unknown", "failed"})
_SLOT_LABELS = {
    "morning": "晨報",
    "pre_open": "台股盤前",
    "intraday": "台股盤中",
    "midday": "台股午盤",
    "afternoon": "台股收盤前",
    "post_close": "台股盤後",
    "us_premarket": "美股盤前",
    "us_open": "美股開盤",
}
_TICKER_NAMES = {
    "TAIEX": "加權指數",
    "TPEx": "櫃買",
    "TXF": "台指期",
    "NASDAQ": "那斯達克",
    "SOX": "費半",
    "DJIA": "道瓊",
    "NIKKEI": "日經",
    "KOSPI": "韓股",
    "US10Y": "美國10年債殖利率",
    "DXY": "美元指數",
    "GOLD": "黃金",
    "WTI": "油價",
    "BRENT": "布蘭特油",
    "BTC": "BTC",
    "ETH": "ETH",
    "ES": "S&P 500 E-mini期貨",
    "NQ": "Nasdaq-100期貨",
    "YM": "道瓊期貨",
}
_TICKER_ALIASES = {
    "TPEX": "TPEx",
    "NASDAQ綜合指數": "NASDAQ",
    "那斯達克": "NASDAQ",
    "那斯達克綜合指數": "NASDAQ",
    "SOX": "SOX",
    "費半": "SOX",
    "費城半導體": "SOX",
    "費城半導體指數": "SOX",
    "道瓊": "DJIA",
    "道瓊工業": "DJIA",
    "道瓊工業指數": "DJIA",
    "台股": "TAIEX",
    "加權指數": "TAIEX",
    "台灣加權": "TAIEX",
}


def _normalise(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _clean_text(value: Any) -> str:
    text = _normalise(value)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\s*[-–—|｜]\s*[A-Za-z0-9.-]+\.(?:com|net|org)\b", "", text, flags=re.I)
    text = re.sub(r"^(?:Google News|Yahoo Finance|Bloomberg)\s*[｜|:]\s*", "", text, flags=re.I)
    text = re.sub(r"^(?:據|根據)\s*[《「][^》」]{1,60}[》」]\s*(?:報導|指出|消息)?[：:，,]?\s*", "", text)
    text = re.sub(r"^(?:FJ\s*\d+(?:\.\d+)?\s*/\s*10\s*[｜|:]\s*)", "", text, flags=re.I)
    text = re.sub(r"^(?:FJ快訊|FJ速報|FinancialJuice)\s*[｜|:]\s*", "", text, flags=re.I)
    text = re.sub(r"\b(?:Embed|Live|Video|Morning Juice)\b\s*[-:：]?", "", text, flags=re.I)
    text = re.sub(r"(?:…|\.\.\.)+", "", text)
    text = re.sub(r"^[🔴🟠🟡🟢🟣⚪️\s|｜:：,，。]+", "", text)
    text = re.sub(r"(?:直播影片|開啟.*?系統|資訊待核對|資料待更新)", "", text, flags=re.I)
    return text.strip(" ｜|:：,，")


_GENERIC_DETAIL_MARKERS = (
    "此公開事件可能影響市場預期",
    "可能連動主要股市、利率或商品市場",
    "觀察主要市場是否出現持續、同步且可核對的價格變化",
    "持續核對公開資料",
    "等待相關市場價格與後續公開資料核對",
)


def _specific_detail(value: Any) -> str:
    """Keep event detail only when it contains an event-specific explanation."""
    text = _clean_text(value)
    if not text or any(marker in text for marker in _GENERIC_DETAIL_MARKERS):
        return ""
    return text


def _is_fragment(text: str) -> bool:
    value = _clean_text(text)
    if not value or value.lower() in {"undefined", "null", "nan", "the", "financialjuice"}:
        return True
    if value.startswith(("據《", "根據《", "《")) or value.count("《") != value.count("》"):
        return True
    if re.fullmatch(r"https?://\S+", value):
        return True
    conditional = re.match(r"^(?:如果|若)\s*([^。！？.!?]*)", value)
    if conditional and not re.search(r"(?:則|就|將|會|可能|因此|would|will|then)", conditional.group(1), flags=re.I):
        return True
    if re.fullmatch(r"[🔴🟠🟡🟢🟣⚪️\s|｜:：,，。\-–.]+", value):
        return True
    if len(value) < 6 and not re.search(r"[\u4e00-\u9fff]", value):
        return True
    return False


def _event_projection(event: dict[str, Any]) -> dict[str, Any]:
    source = str(event.get("source_key") or event.get("source") or "").casefold()
    fields = (
        ("event", "what_happened", "summary", "brief_summary", "traditional_chinese_summary", "chinese_translation", "headline", "original_headline", "title", "public_short_message")
        if source != "financialjuice"
        else ("event", "what_happened", "chinese_translation", "headline", "summary", "brief_summary", "public_short_message", "original_headline", "title")
    )
    for field in fields:
        candidate = _clean_text(event.get(field))
        if not _is_fragment(candidate):
            normalized = normalize_headline(event, candidate)
            if normalized.get("normalization_complete"):
                return normalized
    return normalize_headline(event, "")


def _event_fact(event: dict[str, Any]) -> str:
    """Select a complete normalized fact without mutating the snapshot."""
    projection = _event_projection(event)
    # An event without a subject/action fact is retained for audit but cannot
    # become a public market theme.  The caller can therefore fail closed
    # without losing the raw observation.
    return str(projection.get("normalized_fact") or "") if projection.get("normalization_complete") else ""


def _event_timestamp(event: dict[str, Any]) -> datetime | None:
    for field in ("published_at", "published_time", "event_time", "fetched_at", "created_at"):
        value = str(event.get(field) or "").strip()
        if not value:
            continue
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            continue
        return (parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC))
    return None


def _within_lookback(event: dict[str, Any], as_of: datetime) -> bool:
    timestamp = _event_timestamp(event)
    return timestamp is None or as_of - timedelta(hours=24) <= timestamp <= as_of + timedelta(minutes=5)


def _event_source(event: dict[str, Any]) -> str:
    source = str(event.get("source_key") or event.get("source") or "公開來源").strip().casefold()
    return "FinancialJuice" if source == "financialjuice" else str(event.get("source") or "官方／公開來源")


def _event_key(event: dict[str, Any], fact: str) -> str:
    existing = str(
        event.get("canonical_event_key")
        or event.get("event_cluster_key")
        or event.get("event_key")
        or ""
    ).strip()
    if existing:
        return existing
    # The same public event may be present in FJ, a news feed and an official
    # lane with different transport identities.  The canonical fact is the
    # stable fallback; source/observation IDs remain provenance only.
    return hashlib.sha256(_normalise(fact).casefold().encode("utf-8")).hexdigest()[:20]


_QUOTE_EVIDENCE_FIELDS = (
    "ticker", "name", "market", "instrument_id", "instrument_master_id",
    "price", "change", "change_percent", "currency", "quote_date",
    "quote_time", "fetched_at", "freshness", "data_status", "source_label",
    "quote_source", "source_domain", "source_url", "cross_checked",
    "quote_delayed", "stale_used", "session", "contract_month", "contract_basis",
)


def _quote_evidence(items: Any) -> list[dict[str, Any]]:
    """Keep release-bound numeric quotes, plus explicitly failed observations.

    A ticker-only reference is not quote evidence.  Explicit failure rows are
    retained as provenance so the UI can distinguish an unavailable source
    from a producer that simply forgot to hydrate a quote.
    """
    if not isinstance(items, list):
        return []
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        ticker = _normalise_ticker(item.get("ticker"))
        if not ticker or ticker in seen:
            continue
        numeric = item.get("price") is not None and item.get("change_percent") is not None
        if numeric:
            try:
                numeric = math.isfinite(float(item["price"])) and math.isfinite(float(item["change_percent"]))
            except (TypeError, ValueError):
                numeric = False
        freshness = str(item.get("freshness") or item.get("data_status") or "").casefold()
        explicit_failure = freshness in _UNUSABLE_FRESHNESS or item.get("quote_delayed") is True or item.get("stale_used") is True
        if not numeric and not explicit_failure:
            continue
        seen.add(ticker)
        row = {key: item[key] for key in _QUOTE_EVIDENCE_FIELDS if key in item}
        row["ticker"] = ticker
        result.append(row)
    return result


def _normalise_ticker(value: Any) -> str:
    raw = _normalise(value).upper()
    return _TICKER_ALIASES.get(raw, raw)


def _event_tickers(event: dict[str, Any]) -> list[str]:
    """Read only structured instrument references; never infer from prose."""
    values: list[Any] = []
    for field in ("ticker", "instrument_id", "instrument_master_id"):
        values.append(event.get(field))
    for field in ("linked_markets", "tickers"):
        candidate = event.get(field)
        values.extend(candidate if isinstance(candidate, list) else [candidate])
    for field in ("instrument", "market_evidence", "related"):
        candidate = event.get(field)
        candidates = candidate if isinstance(candidate, list) else [candidate]
        values.extend(item.get("ticker") for item in candidates if isinstance(item, dict))
    result: list[str] = []
    for value in values:
        ticker = _normalise_ticker(value)
        if ticker and ticker in _TICKER_NAMES and ticker not in result:
            result.append(ticker)
    return result


def _bind_event_quotes(event: dict[str, Any], snapshot_quotes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bind event quotes to the same release snapshot, without generic fallback."""
    by_ticker = {
        _normalise_ticker(item.get("ticker")): item
        for item in snapshot_quotes
        if _normalise_ticker(item.get("ticker"))
    }
    direct = event.get("market_evidence")
    direct_rows = direct if isinstance(direct, list) else ([direct] if isinstance(direct, dict) else [])
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in direct_rows:
        if not isinstance(item, dict):
            continue
        ticker = _normalise_ticker(item.get("ticker"))
        if not ticker or ticker in seen:
            continue
        bound = by_ticker.get(ticker)
        # A complete event-specific quote is kept as-is.  A compact
        # ticker-only reference is hydrated only from this same snapshot.
        merged = {**bound, **item} if bound and not _usable_quote(item) and str(
            item.get("freshness") or item.get("data_status") or ""
        ).casefold() not in _UNUSABLE_FRESHNESS else item
        if merged is not item:
            merged["ticker"] = ticker
        rows.append(merged)
        seen.add(ticker)
    for ticker in _event_tickers(event):
        if ticker in seen or ticker not in by_ticker:
            continue
        rows.append(by_ticker[ticker])
        seen.add(ticker)
    return _quote_evidence(rows)


def _source_evidence(event: dict[str, Any], source: str) -> list[dict[str, Any]]:
    evidence = {
        "source": source,
        "source_key": event.get("source_key") or event.get("source"),
        "observation_id": event.get("observation_id"),
        "notification_id": event.get("notification_id"),
        "published_at": event.get("published_at") or event.get("created_at"),
    }
    # Do not add empty provenance fields to legacy themes: otherwise merely
    # upgrading the projection would change their canonical briefing hash.
    source_url = event.get("source_url") or event.get("url")
    source_domain = event.get("source_domain")
    if source_url:
        evidence["source_url"] = source_url
    if source_domain:
        evidence["source_domain"] = source_domain
    result = [evidence]
    supporting = event.get("_supporting_sources")
    if isinstance(supporting, list):
        result.extend(item for item in supporting if isinstance(item, dict))
    return result


def _importance_score(event: dict[str, Any]) -> float:
    value = event.get("vendor_importance")
    if value is None:
        value = event.get("importance")
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return {"high-risk": 3.0, "warning": 2.0, "normal": 1.0}.get(str(value).casefold(), 0.0)


def _risk_score(event: dict[str, Any]) -> int:
    value = str(event.get("prstk_risk_level") or event.get("risk_level") or "").strip().upper()
    return {"R4": 4, "R3": 3, "R2": 2, "R1": 1, "R0": 0}.get(value, -1)


def _notification_priority(event: dict[str, Any]) -> int:
    source = str(event.get("source_key") or event.get("source") or event.get("kind") or "").casefold()
    return int(
        event.get("notification_status") == "eligible"
        and source not in {"financialjuice", "news"}
    )


def _quote_clause(item: dict[str, Any]) -> str:
    ticker = str(item.get("ticker") or "").strip()
    name = _TICKER_NAMES.get(ticker, ticker or "市場")
    price = item.get("price")
    change = item.get("change_percent")
    if change is None:
        return ""
    try:
        move = float(change)
    except (TypeError, ValueError):
        return ""
    freshness = str(item.get("freshness") or item.get("data_status") or "live").casefold()
    prefix = "最近收盤" if freshness in _UNUSABLE_FRESHNESS else ""
    if price is not None:
        try:
            return f"{prefix}{name}{float(price):,.2f}{move:+.2f}%".strip()
        except (TypeError, ValueError):
            pass
    return f"{prefix}{name}{move:+.2f}%".strip()


def _usable_quote(item: dict[str, Any]) -> bool:
    if item.get("change_percent") is None or item.get("price") is None:
        return False
    try:
        return math.isfinite(float(item["price"])) and math.isfinite(float(item["change_percent"]))
    except (TypeError, ValueError):
        return False


def _usable_scoped_quote(item: dict[str, Any]) -> bool:
    if not _usable_quote(item) or item.get("stale_used") is True:
        return False
    freshness = str(item.get("freshness") or item.get("data_status") or "").casefold()
    return freshness not in _UNUSABLE_FRESHNESS and bool(item.get("quote_time") or item.get("quote_date"))


def _theme_for_event(event: dict[str, Any], fact: str, snapshot_quotes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    source = _event_source(event)
    normalized = _event_projection(event)
    market_topic = str(normalized.get("market_topic") or "company_industry")
    public_fact = str(normalized.get("normalized_fact") or fact)
    why = _specific_detail(event.get("why_important") or event.get("importance_detail") or event.get("trigger"))
    impact = _specific_detail(event.get("possible_linkage") or event.get("possible_impact") or event.get("market_context"))
    watch = _specific_detail(event.get("stock_observation") or event.get("watch") or event.get("follow_up_observation"))
    detail_eligible = bool(why and impact and watch)
    source_evidence = _source_evidence(event, source)
    quote_evidence = _bind_event_quotes(event, snapshot_quotes or [])
    canonical_event_key = _event_key(event, fact)
    return {
        # The topic is the public heading; provider identity remains in the
        # evidence footer so a source name cannot masquerade as the analysis.
        "title": topic_label(market_topic),
        "market_topic": market_topic,
        "what_happened": public_fact,
        "why_important": why,
        "market_implication": impact,
        "stock_observation": watch,
        "detail_eligible": detail_eligible,
        "evidence": source_evidence,
        "source_evidence": source_evidence,
        "quote_evidence": quote_evidence,
        "event_key": canonical_event_key,
        "canonical_event_key": canonical_event_key,
        "source_event_keys": [
            str(value).strip()
            for value in (
                event.get("notification_key"),
                event.get("notification_id"),
                event.get("observation_id"),
                event.get("event_cluster_key"),
            )
            if str(value or "").strip()
        ],
        "source": source,
        "published_at": event.get("published_at") or event.get("created_at") or event.get("received_at"),
        "notification_status": event.get("notification_status"),
        "prstk_risk_level": event.get("prstk_risk_level") or event.get("risk_level"),
        "vendor_importance": event.get("vendor_importance"),
        "raw_title": normalized.get("raw_title"),
        "normalized_fact": public_fact,
        "linked_markets": list(normalized.get("linked_markets") or event.get("linked_markets") or []),
        "linked_market_details": list(normalized.get("linked_market_details") or event.get("linked_market_details") or []),
        "market_linkage_status": normalized.get("market_linkage_status") or event.get("market_linkage_status") or "unresolved",
        "actor_role": normalized.get("actor_role"),
        "actor_name": normalized.get("actor_name"),
        "headline_actor": normalized.get("headline_actor"),
        "byline_removed": normalized.get("byline_removed", False),
        "publisher_removed": normalized.get("publisher_removed", False),
        "normalization_ruleset": normalized.get("normalization_ruleset"),
        "normalization_complete": normalized.get("normalization_complete", False),
        "official_confirmed": event.get("official_confirmed") is True or event.get("official_confirmation") is True,
        "market_sync_confirmed": event.get("market_sync_confirmed") is True or event.get("market_confirmation") is True,
    }


def _theme_for_quotes(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    clauses = [_quote_clause(item) for item in items if _usable_quote(item)]
    clauses = [value for value in clauses if value]
    if not clauses:
        return None
    quote_evidence = _quote_evidence(items[:3])
    return {
        "title": "市場價格",
        "market_topic": "global_market",
        "normalization_complete": True,
        "what_happened": "、".join(clauses[:3]) + "。",
        "why_important": "價格資料提供目前市場狀態，仍需搭配事件與資料時間判讀。",
        "market_implication": "各市場若同向可作為價格確認；若分歧，暫不推論跨市場因果。",
        "stock_observation": "持續核對費半、那斯達克、道瓊與台股主要指數是否延續。",
        "evidence": [{
            "source": item.get("source_label") or item.get("quote_source") or "市場報價",
            "ticker": item.get("ticker"),
            "quote_time": item.get("quote_time") or item.get("quote_date"),
            "freshness": item.get("freshness") or item.get("data_status"),
        } for item in items[:3] if _usable_quote(item)],
        "source_evidence": [{
            "source": item.get("source_label") or item.get("quote_source") or "市場報價",
            "ticker": item.get("ticker"),
            "quote_time": item.get("quote_time") or item.get("quote_date"),
            "freshness": item.get("freshness") or item.get("data_status"),
        } for item in items[:3] if _usable_quote(item)],
        "quote_evidence": quote_evidence,
        "event_key": hashlib.sha256("|".join(clauses[:3]).encode("utf-8")).hexdigest()[:20],
        "canonical_event_key": hashlib.sha256("|".join(clauses[:3]).encode("utf-8")).hexdigest()[:20],
        "source": "市場報價",
        "published_at": next((item.get("quote_time") or item.get("quote_date") for item in items if _usable_quote(item)), None),
        "detail_eligible": True,
    }


def _dedupe_market_topics(themes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep at most one public theme per investor-facing market topic."""
    result: list[dict[str, Any]] = []
    seen_topics: set[str] = set()
    for theme in themes:
        if not isinstance(theme, dict):
            continue
        topic = str(theme.get("market_topic") or "").strip()
        if topic and topic in seen_topics:
            continue
        if topic:
            seen_topics.add(topic)
        result.append(theme)
    return result


def _news_events(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Project only public-gate-approved news into digest candidates.

    ``news.markets`` is a legacy/raw compatibility shape.  New releases use
    ``news.intelligence`` and fail closed when a story does not explicitly
    carry ``public_news_eligible=true``.
    """
    news = snapshot.get("news")
    if not isinstance(news, dict):
        return []
    rows: list[dict[str, Any]] = []
    intelligence = news.get("intelligence")
    if isinstance(intelligence, dict):
        legacy = False
        markets = intelligence
    elif isinstance(news.get("markets"), dict):
        # Retained reviewed market artifacts remain readable.  Raw top-level
        # provider arrays are diagnostic-only and cannot enter a digest.
        legacy = True
        markets = news["markets"]
    else:
        return []
    if isinstance(markets, dict):
        containers = [markets.get(key) for key in ("taiwan", "us") if isinstance(markets.get(key), dict)]
        if not containers and isinstance(markets.get("stories"), list):
            containers = [markets]
    else:
        containers = [markets]
    for container in containers:
        stories = container.get("stories") if isinstance(container, dict) else container
        if not isinstance(stories, list):
            continue
        for story in stories:
            if not isinstance(story, dict):
                continue
            if not legacy and story.get("public_news_eligible") is not True:
                continue
            projected = dict(story)
            projected.setdefault("source_key", "news")
            projected["_legacy_news_projection"] = legacy
            projected.setdefault("source", story.get("source_name") or "公開市場新聞")
            projected.setdefault("event", story.get("summary") or story.get("description") or story.get("headline") or story.get("title"))
            rows.append(projected)
    return rows


_NEWS_SOURCE_MARKERS = (
    "google news",
    "yahoo股市",
    "yahoo finance",
    "anue",
    "cnyes",
    "公開市場新聞",
)

_EVENT_DETAIL_FIELDS = (
    "why_important",
    "importance_detail",
    "trigger",
    "possible_linkage",
    "possible_impact",
    "market_context",
    "stock_observation",
    "watch",
    "follow_up_observation",
)


def _has_event_detail_input(event: dict[str, Any]) -> bool:
    """Tell legacy rows from rows that explicitly supplied a generic fallback."""
    return any(_normalise(event.get(field)) for field in _EVENT_DETAIL_FIELDS)


def _is_news_derived_event(event: dict[str, Any]) -> bool:
    source_key = str(event.get("source_key") or "").casefold().strip()
    source = str(event.get("source") or event.get("content_origin") or "").casefold()
    return source_key in {"news", "market_news", "public_news"} or any(
        marker in source for marker in _NEWS_SOURCE_MARKERS
    )


def _is_canonical_news_event(event: dict[str, Any]) -> bool:
    """Require the release-bound intelligence contract for news-derived rows."""
    if event.get("public_news_eligible") is not True:
        return False
    canonical_url = str(event.get("canonical_url") or "").strip().casefold()
    if not canonical_url.startswith("https://"):
        return False
    return event.get("normalization_complete") is True


def _fit_sentence(prefix: str, clauses: list[str], limit: int) -> str:
    chosen = prefix
    for clause in clauses:
        candidate = f"{chosen}{clause}" if chosen.endswith(("｜", "：", " ")) else f"{chosen}；{clause}"
        if len(candidate) <= limit:
            chosen = candidate
    return chosen.rstrip("；，、")


def build_market_digest(
    snapshot: dict[str, Any],
    slot: str,
    *,
    intelligence: dict[str, Any] | None = None,
    risk: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the shared dashboard/Telegram market assessment."""
    market_scope_key = market_scope_for_slot(slot)
    scoped_source = dict(snapshot)
    if risk is not None and market_scope_key:
        scoped_source["risk"] = risk
    snapshot = scope_snapshot(scoped_source, slot)
    if market_scope_key:
        # Aggregate regime/risk arguments do not carry a market-scoped proof;
        # routine market slots derive conclusions from their target projection.
        risk = snapshot.get("risk") if isinstance(snapshot.get("risk"), dict) else {}
        intelligence = None
    elif risk is None:
        risk = snapshot.get("risk") if isinstance(snapshot.get("risk"), dict) else None
    generated = str(snapshot.get("generated_at") or snapshot.get("fetched_at") or "")
    try:
        as_of = datetime.fromisoformat(generated.replace("Z", "+00:00"))
        as_of = as_of.replace(tzinfo=UTC) if as_of.tzinfo is None else as_of.astimezone(UTC)
    except ValueError:
        as_of = datetime.now(UTC)

    raw_events: list[dict[str, Any]] = []
    event_block = snapshot.get("events")
    if isinstance(event_block, dict) and isinstance(event_block.get("items"), list):
        raw_events.extend(item for item in event_block["items"] if isinstance(item, dict))
    raw_events.extend(item for item in snapshot.get("financialjuice_priority_events", []) if isinstance(item, dict))
    raw_events.extend(item for item in snapshot.get("external_observations", []) if isinstance(item, dict))
    raw_events.extend(_news_events(snapshot))

    candidates_by_key: dict[str, tuple[dict[str, Any], str]] = {}
    for event in raw_events:
        # Threshold market signals remain in the instant-alert lane.  Their
        # verbose machine-formatted event text is not a digest fact; the
        # canonical quote theme below presents the same move readably.
        if str(event.get("kind") or "").casefold() == "market_signal":
            continue
        source = str(event.get("source_key") or event.get("source") or event.get("content_origin") or "").casefold()
        if source in {"haojiao", "jenny", "gooaye", "creator"}:
            continue
        if source == "financialjuice" and str(event.get("freshness_status") or "") != "fresh":
            # Stale or untimestamped FJ remains available to diagnostic/UI
            # consumers but cannot become a briefing fact or market driver.
            continue
        if _is_news_derived_event(event) and not (
            event.get("_legacy_news_projection") is True
            or _is_canonical_news_event(event)
        ):
            continue
        if not _within_lookback(event, as_of):
            continue
        fact = _event_fact(event)
        if not fact:
            continue
        key = _event_key(event, fact)
        if key in candidates_by_key:
            existing = candidates_by_key[key][0]
            supporting = existing.setdefault("_supporting_sources", [])
            if isinstance(supporting, list):
                supporting.append({
                    "source": _event_source(event),
                    "source_key": event.get("source_key") or event.get("source"),
                    "observation_id": event.get("observation_id"),
                    "source_url": event.get("source_url") or event.get("url"),
                    "published_at": event.get("published_at") or event.get("created_at"),
                })
            continue
        candidates_by_key[key] = (event, fact)

    candidates = list(candidates_by_key.values())

    def candidate_sort_key(pair: tuple[dict[str, Any], str]) -> tuple[int, int, int, float, float, str]:
        timestamp = _event_timestamp(pair[0])
        event = pair[0]
        source = str(event.get("source_key") or event.get("source") or "").casefold()
        sync_rank = int(not (event.get("official_confirmed") is True and event.get("market_sync_confirmed") is True))
        return (
            -_notification_priority(event),
            -_risk_score(event),
            sync_rank,
            -(timestamp.timestamp() if timestamp else 0),
            -_importance_score(event) if source == "financialjuice" else 0.0,
            _event_key(event, pair[1]),
        )

    candidates.sort(key=candidate_sort_key)

    all_quotes = [
        item for item in [*(snapshot.get("indices") or []), *(snapshot.get("quotes") or []), *(snapshot.get("macro_quotes") or [])]
        if isinstance(item, dict)
    ]
    if market_scope_key:
        all_quotes = [item for item in all_quotes if _usable_scoped_quote(item)]
    quote_priority = [
        "TAIEX", "TXF", "S&P 500", "NASDAQ", "DJIA", "ES", "NQ", "YM", "SOX",
        "TPEx", "US10Y", "DXY", "GOLD", "WTI",
    ]
    quote_items = sorted(
        [item for item in all_quotes if _normalise_ticker(item.get("ticker")) in quote_priority],
        key=lambda item: quote_priority.index(_normalise_ticker(item.get("ticker"))),
    )
    quote_theme = _theme_for_quotes(quote_items)
    # Quote evidence belongs to an event only when the event carries a
    # structured ticker reference (or its own market_evidence).  In
    # particular, a geopolitical/FJ event must not inherit unrelated NASDAQ
    # and SOX cards merely because they happen to be present in the snapshot.
    event_themes_with_input = [
        (_theme_for_event(event, fact, all_quotes), _has_event_detail_input(event))
        for event, fact in candidates
    ]
    event_themes = [
        theme for theme, _has_detail_input in event_themes_with_input
        if theme.get("normalization_complete")
    ]
    # A headline becomes the report's main cause only when it has complete
    # context and either event-specific price evidence or explicit official
    # confirmation.  Otherwise the current market quotes own the first
    # screen and the article remains supporting evidence.
    lead_event_themes = [
        theme for theme in event_themes
        if theme.get("detail_eligible") is True
        and (theme.get("quote_evidence") or theme.get("official_confirmed") is True)
    ]
    fallback_event = next(
        (
            theme for theme, has_detail_input in event_themes_with_input
            if theme.get("normalization_complete")
            and (theme.get("detail_eligible") is True or not has_detail_input)
        ),
        None,
    )
    primary_theme = lead_event_themes[0] if lead_event_themes else quote_theme or fallback_event
    if primary_theme is None and market_scope_key:
        scope_label = "台股" if market_scope_key == "taiwan" else "美股"
        data_gap_key = f"scheduled-data-gap:{market_scope_key}:{as_of.date().isoformat()}"
        primary_theme = {
            "title": "市場資料狀態",
            "market_topic": "taiwan_market" if market_scope_key == "taiwan" else "global_market",
            "normalization_complete": True,
            "what_happened": f"{scope_label}指定行情本輪缺漏，不以其他市場或舊值代替。",
            "why_important": "市場資料缺漏時，先標示來源未提供；不據此推論市場方向。",
            "market_implication": "本輪無可核對價格，暫不形成方向或跨市場因果判讀。",
            "stock_observation": "待目標市場的同口徑行情可用後再更新。",
            "evidence": [],
            "source_evidence": [],
            "quote_evidence": [],
            "canonical_event_key": data_gap_key,
            "event_key": data_gap_key,
            "source": "市場資料狀態",
            "detail_eligible": False,
        }
    if primary_theme is None:
        return {
            "status": "suppressed",
            "notification_eligible": False,
            "notification_reason": "insufficient_evidence",
            "assessment_summary": "",
            "overview": "本輪公開市場證據不足，暫不形成判讀。",
            "public_short_message": "",
            "public_summary_version": PUBLIC_SUMMARY_VERSION,
            "public_summary_evidence_fields": [],
            "public_summary_reason": "summary_semantics_incomplete",
            "themes": [],
            "primary_theme": None,
            "secondary_signals": [],
            "displayed_event_keys": [],
            "evidence": [],
            "source_evidence": [],
            "quote_evidence": [],
        }
    themes = [primary_theme]
    primary_key = str(primary_theme.get("canonical_event_key") or "")
    event_secondary_themes = [
        theme for theme in event_themes
        if str(theme.get("canonical_event_key") or "") != primary_key
    ]
    secondary_themes = list(event_secondary_themes)
    if quote_theme and not primary_theme.get("quote_evidence"):
        secondary_themes.append(quote_theme)
    themes = _dedupe_market_topics([primary_theme, *secondary_themes])[:3]

    # Prices are evidence attached to the event, not a second copy of the
    # event's public narrative.  Keep quote-only briefings meaningful, while
    # preventing a refreshed quote from changing the identity of an event
    # briefing or making the Telegram summary oscillate between runs.
    summary_themes = _dedupe_market_topics([primary_theme, *event_secondary_themes])[:3]

    secondary_signals: list[dict[str, Any]] = []
    seen_secondary: set[str] = {str(primary_theme.get("canonical_event_key") or "")}
    # Secondary public signals are events only.  A quote-only theme is
    # supporting evidence for the briefing and must not become a duplicate
    # event row in the Mini App.
    for theme in event_secondary_themes:
        key = str(theme.get("canonical_event_key") or "").strip()
        if not key or key in seen_secondary:
            continue
        seen_secondary.add(key)
        secondary_signals.append({
            "canonical_event_key": key,
            "event_key": key,
            "title": theme.get("title"),
            "what_happened": theme.get("what_happened"),
            "public_short_message": theme.get("what_happened"),
            "source": theme.get("source"),
            "published_at": theme.get("published_at"),
            "prstk_risk_level": theme.get("prstk_risk_level"),
            "notification_status": theme.get("notification_status"),
            "vendor_importance": theme.get("vendor_importance"),
            "detail_eligible": theme.get("detail_eligible") is True,
            "official_confirmed": theme.get("official_confirmed") is True,
            "market_sync_confirmed": theme.get("market_sync_confirmed") is True,
            "source_event_keys": theme.get("source_event_keys") or [],
            "rank_reason": "重要度／核對狀態／發布時間／穩定事件鍵",
        })
        if len(secondary_signals) >= 3:
            break

    summary_themes = [theme for theme in summary_themes if theme and theme.get("normalization_complete", True)]
    if not summary_themes:
        return {
            "status": "suppressed",
            "notification_eligible": False,
            "notification_reason": "insufficient_evidence",
            "assessment_summary": "",
            "overview": "本輪公開市場證據不足，暫不形成判讀。",
            "public_short_message": "",
            "public_summary_version": PUBLIC_SUMMARY_VERSION,
            "public_summary_evidence_fields": [],
            "public_summary_reason": "summary_semantics_incomplete",
            "themes": [],
            "primary_theme": None,
            "secondary_signals": [],
            "displayed_event_keys": [],
            "evidence": [],
            "source_evidence": [],
            "quote_evidence": [],
        }

    label = _SLOT_LABELS.get(slot, "市場")
    assessment = build_market_assessment(
        slot=slot,
        as_of=as_of,
        quotes=quote_items,
        themes=summary_themes,
        intelligence=intelligence,
        market_status=snapshot.get("markets") if isinstance(snapshot.get("markets"), dict) else None,
        risk=risk,
    )
    assessment["market_scope_key"] = market_scope_key or (
        "taiwan" if assessment.get("market_scope") == "台股" else
        "us" if assessment.get("market_scope") == "美股" else "global"
    )
    assessment["scheduled_report"] = slot in {"morning", "pre_open", "post_close", "us_premarket"}
    required_tickers = sorted(SCOPE_TICKERS[market_scope_key]) if market_scope_key else []
    present_tickers = {_normalise_ticker(item.get("ticker")) for item in all_quotes}
    quote_gaps = [
        {"ticker": ticker, "reason": "quote_missing_or_unusable"}
        for ticker in required_tickers
        if ticker not in present_tickers or not any(
            _normalise_ticker(item.get("ticker")) == ticker and _usable_scoped_quote(item)
            for item in all_quotes
        )
    ]
    assessment["quote_gaps"] = quote_gaps
    overview = project_overview(assessment, DASHBOARD_SUMMARY_MAX_CHARS)
    public_message = project_public_message(label, assessment, PUBLIC_MESSAGE_MAX_CHARS)
    if public_message and not len(public_message) <= PUBLIC_MESSAGE_MAX_CHARS:
        public_message = ""
    if market_scope_key and required_tickers and len(quote_gaps) == len(required_tickers):
        from src.telegram_client import canonical_short_message

        scope_label = "台股盤後" if market_scope_key == "taiwan" else "美股盤前"
        assessment["summary_sections"].update({
            "summary": f"{scope_label}行情資料不足",
            "market_highlights": "指定行情本輪缺漏，未使用其他市場或舊值替代",
            "risk": "資料不足，不推論市場方向",
        })
        overview = project_overview(assessment, DASHBOARD_SUMMARY_MAX_CHARS)
        public_message = canonical_short_message(
            f"{scope_label}｜行情資料不足，本輪明確列示缺漏。",
            limit=PUBLIC_MESSAGE_MAX_CHARS,
        )
    elif market_scope_key:
        # Routine market reports are useful even without a major headline or
        # a high-confidence directional conclusion. Keep the Telegram text a
        # compact projection of this scoped snapshot, and leave missing rows
        # explicit in the linked card instead of suppressing the slot.
        from src.telegram_client import canonical_short_message

        scope_label = "台股盤後" if market_scope_key == "taiwan" else "美股盤前"
        available = []
        for item in quote_items:
            if not _usable_scoped_quote(item):
                continue
            ticker = _normalise_ticker(item.get("ticker"))
            name = _TICKER_NAMES.get(ticker, ticker)
            available.append(f"{name}{float(item['change_percent']):+.2f}%")
        missing = [
            _TICKER_NAMES.get(str(item.get("ticker") or ""), str(item.get("ticker") or ""))
            for item in quote_gaps
        ]
        compact = "、".join(available[:3]) if available else "行情資料不足"
        if missing:
            compact += "；缺漏 " + "、".join(missing[:3])
        public_message = canonical_short_message(
            f"{scope_label}｜{compact}", limit=PUBLIC_MESSAGE_MAX_CHARS,
        )
        if missing:
            existing_highlights = str(assessment["summary_sections"].get("market_highlights") or "").strip()
            missing_text = "缺漏 " + "、".join(missing[:3])
            assessment["summary_sections"]["market_highlights"] = "；".join(
                value for value in (existing_highlights, missing_text) if value
            )
        overview = project_overview(assessment, DASHBOARD_SUMMARY_MAX_CHARS)

    # A routine morning brief still goes out on Taiwan holidays and weekends.
    # State the local market closure and the actual TAIEX observation date in
    # the same release-bound summary instead of letting recent US data obscure
    # why Taiwan quotes are from an earlier session.
    markets = snapshot.get("markets") if isinstance(snapshot.get("markets"), dict) else {}
    taiwan_status = markets.get("taiwan") if isinstance(markets, dict) else None
    cash_status = markets.get("taiwan_cash") if isinstance(markets, dict) else None
    futures_status = markets.get("taiwan_futures") if isinstance(markets, dict) else None
    cash_open = cash_status.get("is_trading_day") if isinstance(cash_status, dict) else None
    futures_open = futures_status.get("is_trading_day") if isinstance(futures_status, dict) else None
    cash_calendar_verified = (
        isinstance(cash_status, dict)
        and cash_status.get("calendar_status")
        == ("confirmed_open" if cash_open is True else "confirmed_closed" if cash_open is False else "")
    )
    futures_calendar_verified = (
        isinstance(futures_status, dict)
        and futures_status.get("calendar_status")
        == ("confirmed_open" if futures_open is True else "confirmed_closed" if futures_open is False else "")
    )
    if slot == "morning" and (
        (
            cash_calendar_verified and futures_calendar_verified
            and (cash_open is False or futures_open is False)
        )
        or (
            cash_open is None and futures_open is None
            and isinstance(taiwan_status, dict)
            and taiwan_status.get("is_trading_day") is False
            and taiwan_status.get("calendar_status") == "confirmed_closed"
        )
    ):
        indices_value = snapshot.get("indices")
        taiwan_indices: list[Any] = indices_value if isinstance(indices_value, list) else []
        taiex = next(
            (
                item for item in taiwan_indices
                if isinstance(item, dict) and _normalise_ticker(item.get("ticker")) == "TAIEX"
            ),
            None,
        )
        observed = ""
        if isinstance(taiex, dict):
            raw_observed = str(taiex.get("quote_date") or taiex.get("quote_time") or "").strip()
            try:
                observed_date = datetime.fromisoformat(raw_observed.replace("Z", "+00:00")).date()
                observed = f"{observed_date.month}/{observed_date.day}"
            except (ValueError, OverflowError):
                pass
        if cash_open is False and futures_open is False:
            market_state = "台股現貨與台指期日盤休市"
        elif cash_open is False and futures_open is True:
            market_state = "台股現貨休市、台指期日盤交易"
        elif cash_open is True and futures_open is False:
            market_state = "台股現貨交易、台指期日盤休市"
        else:
            market_state = "台股休市"
        session_disclosure = (
            f"{market_state}；加權行情資料日 {observed}"
            if observed else f"{market_state}；加權行情資料日未取得"
        )
        from src.telegram_client import canonical_short_message

        public_message = canonical_short_message(
            f"晨報｜{session_disclosure}；{public_message or '今日市場行情與觀察'}",
            limit=PUBLIC_MESSAGE_MAX_CHARS,
        )
        sections = assessment.get("summary_sections")
        if not isinstance(sections, dict):
            sections = {}
            assessment["summary_sections"] = sections
        existing_highlights = str(sections.get("market_highlights") or "").strip()
        sections["market_highlights"] = "；".join(
            part for part in (session_disclosure, existing_highlights) if part
        )
        sections["market_session"] = session_disclosure
        assessment["market_session_state"] = session_disclosure
        overview = project_overview(assessment, DASHBOARD_SUMMARY_MAX_CHARS)

    canonical_material = {
        # Slot labels are presentation metadata.  Cross-anchor delivery
        # coalescing uses ``decision_fingerprint`` below, so changing from
        # morning to pre-open cannot by itself manufacture a new decision.
        "slot": slot,
        # The detailed market-highlights sentence is quote hydration.  Keep
        # the conclusion/risk projection in the identity, but do not let a
        # refreshed price value create a new alert identity.
        "overview": "總結｜{summary}。風險｜{risk}。".format(
            summary=((assessment.get("summary_sections") or {}).get("summary") or ""),
            risk=((assessment.get("summary_sections") or {}).get("risk") or ""),
        ),
        "public_short_message": public_message,
        "public_summary_version": PUBLIC_SUMMARY_VERSION,
        "public_summary_evidence_fields": [
            "summary_sections.summary",
            "summary_sections.market_highlights",
        ] if public_message else [],
        "public_summary_reason": "" if public_message else "summary_semantics_incomplete",
        # Quote hydration is release-bound evidence, not notification
        # identity.  Keep the values in the artifact, but exclude them from
        # the content hash so a refreshed quote cannot resend the same event.
        "market_assessment": {
            key: (
                {str(group): sorted(str(sign) for sign in signs) for group, signs in value.items()}
                if key == "evidence_groups" and isinstance(value, dict)
                else value
            ) for key, value in assessment.items()
            if key not in {
                "evidence_as_of", "factor_count", "evidence_dimensions",
                "score", "factor_source", "directional_quote_count",
                # This is a page-only projection.  It must not alter the
                # notification identity when quote hydration changes.
                "joint_market_signal",
            } and key != "summary_sections"
        } | {
            "summary_sections": {
                key: value
                for key, value in (assessment.get("summary_sections") or {}).items()
                if key != "market_highlights"
            },
        },
        "themes": [
            {key: value for key, value in theme.items() if key != "quote_evidence"}
            for theme in summary_themes
            if theme and theme.get("title") != "市場價格"
        ],
    }
    decision_themes: list[dict[str, str]] = []
    for theme in summary_themes:
        if not theme:
            continue
        if theme.get("title") == "市場價格":
            decision_themes.append({"market_topic": "global_market", "kind": "quote_state"})
            continue
        material_event = theme.get("detail_eligible") is True and (
            theme.get("official_confirmed") is True
            or theme.get("market_sync_confirmed") is True
            or str(theme.get("prstk_risk_level") or "").upper() in {"R3", "R4"}
        )
        if material_event:
            decision_themes.append({
                "canonical_event_key": str(theme.get("canonical_event_key") or ""),
                "market_topic": str(theme.get("market_topic") or ""),
                "kind": "material_event",
            })
    decision_material = {
        "stance": assessment.get("stance"),
        "market_scope": assessment.get("market_scope"),
        "dominant_driver": assessment.get("dominant_driver"),
        "dominant_driver_key": assessment.get("dominant_driver_key"),
        "conflict_flags": assessment.get("conflict_flags") or [],
        "supporting_theme_keys": [
            str(theme.get("canonical_event_key") or theme.get("event_key") or "")
            for theme in summary_themes
            if theme.get("detail_eligible") is True
            and (
                theme.get("official_confirmed") is True
                or theme.get("market_sync_confirmed") is True
                or str(theme.get("prstk_risk_level") or "").upper() in {"R3", "R4"}
            )
        ],
        "evidence_groups": {
            str(key): sorted(str(value) for value in values)
            for key, values in (assessment.get("evidence_groups") or {}).items()
        },
        "themes": decision_themes,
    }
    decision_fingerprint = hashlib.sha256(
        json.dumps(decision_material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    evidence_material = {
        "quotes": [
            {
                key: item.get(key)
                for key in ("ticker", "price", "change_percent", "quote_date", "quote_time", "source_label", "quote_source")
                if item.get(key) not in (None, "")
            }
            for item in sorted(_quote_evidence(quote_items), key=lambda row: str(row.get("ticker") or ""))
        ],
        "events": [
            {
                "canonical_event_key": theme.get("canonical_event_key"),
                "published_at": theme.get("published_at"),
                "source_evidence": theme.get("source_evidence") or [],
            }
            for theme in summary_themes
            if theme and theme.get("detail_eligible") is True
        ],
    }
    evidence_fingerprint = hashlib.sha256(
        json.dumps(evidence_material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    content_hash = hashlib.sha256(
        json.dumps(canonical_material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    briefing_id = f"briefing-{slot}-{content_hash[:20]}"
    return {
        "status": "ready" if public_message else "suppressed",
        "notification_eligible": bool(public_message),
        "notification_reason": "candidate_ready" if public_message else "content_incomplete",
        "briefing_id": briefing_id,
        "notification_key": f"scheduled_brief:{slot}:{briefing_id}",
        "observation_id": f"briefing-observation-{content_hash[:20]}",
        "trace_id": f"briefing-trace-{slot}-{content_hash[:16]}",
        "canonical_content_hash": content_hash,
        "canonical_hash_version": 2,
        "decision_fingerprint": decision_fingerprint,
        "evidence_fingerprint": evidence_fingerprint,
        "evidence_material": evidence_material,
        "decision_material": decision_material,
        "assessment_summary": overview,
        "overview": overview,
        "market_assessment": assessment,
        "market_scope_key": market_scope_key or assessment.get("market_scope_key"),
        "scheduled_report": assessment.get("scheduled_report") is True,
        "quote_gaps": quote_gaps,
        "data_gap_status": (
            "unavailable" if required_tickers and len(quote_gaps) == len(required_tickers)
            else "partial" if quote_gaps else "complete"
        ),
        "public_short_message": public_message,
        "themes": themes,
        "primary_theme": primary_theme,
        "secondary_signals": secondary_signals,
        "displayed_event_keys": list(dict.fromkeys(
            str(key).strip()
            for theme in [primary_theme, *secondary_signals]
            for key in [
                theme.get("canonical_event_key") or theme.get("event_key"),
                *(theme.get("source_event_keys") or []),
            ]
            if str(key or "").strip()
        )),
        "evidence": [evidence for theme in themes for evidence in theme.get("evidence", [])],
        "source_evidence": [evidence for theme in themes for evidence in theme.get("source_evidence", [])],
        "quote_evidence": list(primary_theme.get("quote_evidence") or [])[:2],
        "lookback_hours": 24,
        "as_of": generated or as_of.isoformat(),
        "slot": slot,
    }


def build_taiwan_holiday_notice_digest(
    *,
    slot: str,
    slot_date: str,
    next_trading_date: str,
    cash_is_trading_day: bool,
    futures_is_trading_day: bool,
    calendar_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a release-bound, non-directional holiday notice for Taiwan."""
    if slot != "pre_open":
        raise ValueError("Taiwan holiday notices are only valid for the pre-open slot")
    if cash_is_trading_day or futures_is_trading_day:
        raise ValueError("holiday notice requires both Taiwan day markets to be closed")
    parsed_date = datetime.fromisoformat(slot_date).date()
    parsed_next = datetime.fromisoformat(next_trading_date).date()
    if parsed_next <= parsed_date:
        raise ValueError("next trading date must follow the holiday date")
    if not isinstance(calendar_evidence, list) or len(calendar_evidence) != 2:
        raise ValueError("holiday notice requires exactly two exchange calendar evidence rows")
    evidence_by_market = {
        str(item.get("market") or ""): item
        for item in calendar_evidence
        if isinstance(item, dict)
    }
    expected_markets = {"taiwan_cash", "taifex_taiwan_index_futures_day_session"}
    if len(evidence_by_market) != 2 or set(evidence_by_market) != expected_markets:
        raise ValueError("holiday notice requires unique exchange calendar evidence rows")
    cash_evidence = evidence_by_market.get("taiwan_cash")
    futures_evidence = evidence_by_market.get("taifex_taiwan_index_futures_day_session")
    if not isinstance(cash_evidence, dict) or not isinstance(futures_evidence, dict):
        raise ValueError("holiday notice requires both exchange calendar evidence rows")
    if cash_evidence.get("is_trading_day") is not False or futures_evidence.get("is_trading_day") is not False:
        raise ValueError("holiday calendar evidence must confirm both markets closed")
    if any(str(item.get("date") or "") != parsed_date.isoformat() for item in (cash_evidence, futures_evidence)):
        raise ValueError("holiday calendar evidence date mismatch")
    if any(
        str(item.get("next_trading_date") or "") != parsed_next.isoformat()
        for item in (cash_evidence, futures_evidence)
    ):
        raise ValueError("holiday calendar next trading date mismatch")
    cash_provider = str(cash_evidence.get("provider") or "").strip()
    futures_provider = str(futures_evidence.get("provider") or "").strip()
    cash_calendar = str(cash_evidence.get("calendar_id") or "").strip()
    futures_calendar = str(futures_evidence.get("calendar_id") or "").strip().upper()
    futures_urls = futures_evidence.get("source_urls")
    futures_publication_dates = futures_evidence.get("source_published_on")
    try:
        coverage_start = datetime.fromisoformat(str(futures_evidence.get("coverage_start") or "")).date()
        coverage_end = datetime.fromisoformat(str(futures_evidence.get("coverage_end") or "")).date()
        datetime.fromisoformat(str(futures_evidence.get("verified_on") or "")).date()
        if isinstance(futures_publication_dates, list):
            for published_on in futures_publication_dates:
                datetime.fromisoformat(str(published_on)).date()
    except ValueError as exc:
        raise ValueError("holiday notice requires dated official TAIFEX source metadata") from exc
    if (
        cash_provider.casefold() != "pandas_market_calendars"
        or cash_calendar.upper() != "XTAI"
        or futures_provider.upper() != "TAIFEX"
        or futures_calendar != "TAIFEX"
        or futures_evidence.get("calendar_version") != f"TAIFEX-{parsed_date.year}"
        or coverage_start.year != parsed_date.year
        or coverage_end.year != parsed_date.year
        or coverage_start > parsed_date
        or coverage_end < parsed_date
        or not isinstance(futures_urls, list)
        or not futures_urls
        or any(not str(url).startswith("https://www.taifex.com.tw/") for url in futures_urls)
        or not isinstance(futures_publication_dates, list)
        or len(futures_publication_dates) != len(futures_urls)
        or not str(futures_evidence.get("source_document") or "").strip()
    ):
        raise ValueError("holiday notice requires independent official TAIFEX calendar evidence")
    if cash_provider.casefold() == futures_provider.casefold() and cash_calendar.casefold() == futures_calendar.casefold():
        raise ValueError("holiday notice calendars are not independent")

    date_label = f"{parsed_next.month}/{parsed_next.day}"
    public_message = f"台股休市提醒｜現貨與台指期日盤休市；次一交易日 {date_label}"
    event_key = f"taiwan-holiday:{parsed_date.isoformat()}"
    source_evidence = [
        {**cash_evidence, "calendar_basis": str(cash_evidence.get("calendar_basis") or cash_calendar)},
        {**futures_evidence, "calendar_basis": str(futures_evidence.get("calendar_basis") or futures_calendar)},
    ]
    calendar_basis = f"TWSE={cash_calendar}; TAIFEX={futures_calendar}"
    primary_theme = {
        "title": "台股休市提醒",
        "market_topic": "taiwan_market",
        "what_happened": public_message,
        "why_important": "今日台股現貨及台指期日盤休市，行情卡不代表今日有成交。",
        "market_implication": "下一個台灣共同交易日為 " + parsed_next.isoformat() + "。",
        "stock_observation": "下一交易日再核對加權指數與台指期近月日盤資料。",
        "canonical_event_key": event_key,
        "event_key": event_key,
        "source_evidence": source_evidence,
        "quote_evidence": [],
        "detail_eligible": True,
    }
    market_assessment = {
        "market_scope": "taiwan",
        "market_scope_key": "taiwan",
        "scheduled_report": True,
        "stance": "not_applicable",
        "confidence": "not_applicable",
        "factor_count": 0,
        "evidence_dimensions": ["exchange_calendar"],
        "summary_sections": {"summary": public_message, "risk": "市場休市，不提供當日方向判讀。"},
    }
    canonical_material = {
        "kind": "taiwan_holiday_notice",
        "slot": slot,
        "slot_date": parsed_date.isoformat(),
        "next_trading_date": parsed_next.isoformat(),
        "calendar_basis": str(calendar_basis),
        "calendar_evidence": source_evidence,
        "cash_is_trading_day": cash_is_trading_day,
        "futures_is_trading_day": futures_is_trading_day,
        "public_short_message": public_message,
        "market_assessment": market_assessment,
    }
    canonical_json = json.dumps(
        canonical_material, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    content_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    briefing_id = f"briefing-{slot}-{content_hash[:20]}"
    decision_material = {"kind": "taiwan_holiday_notice", "event_key": event_key}
    evidence_material = {"source_evidence": source_evidence}
    decision_fingerprint = hashlib.sha256(
        json.dumps(decision_material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    evidence_fingerprint = hashlib.sha256(
        json.dumps(evidence_material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "status": "ready",
        "digest_status": "ready",
        "notification_eligible": True,
        "notification_reason": "holiday_notice_required",
        "briefing_id": briefing_id,
        "notification_key": f"scheduled_brief:{slot}:{briefing_id}",
        "observation_id": f"briefing-observation-{content_hash[:20]}",
        "trace_id": f"briefing-trace-{slot}-{content_hash[:16]}",
        "canonical_content_hash": content_hash,
        "canonical_hash_version": 2,
        "decision_fingerprint": decision_fingerprint,
        "evidence_fingerprint": evidence_fingerprint,
        "decision_material": decision_material,
        "evidence_material": evidence_material,
        "assessment_summary": public_message,
        "overview": public_message,
        "market_assessment": market_assessment,
        "market_scope_key": "taiwan",
        "scheduled_report": True,
        "data_gap_status": "not_applicable",
        "public_short_message": public_message,
        "public_summary_version": PUBLIC_SUMMARY_VERSION,
        "public_summary_evidence_fields": ["exchange_calendar", "next_trading_date"],
        "public_summary_reason": "",
        "themes": [primary_theme],
        "primary_theme": primary_theme,
        "secondary_signals": [],
        "displayed_event_keys": [event_key],
        "evidence": source_evidence,
        "source_evidence": source_evidence,
        "quote_evidence": [],
        "lookback_hours": 0,
        "as_of": parsed_date.isoformat(),
        "slot": slot,
        "holiday_notice": {
            "date": parsed_date.isoformat(),
            "next_trading_date": parsed_next.isoformat(),
            "calendar_basis": str(calendar_basis),
            "cash_is_trading_day": cash_is_trading_day,
            "futures_is_trading_day": futures_is_trading_day,
        },
    }
