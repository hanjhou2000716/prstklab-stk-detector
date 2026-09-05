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

from src.telegram_client import summarize_public_message

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
    "TAIEX": "台指",
    "TPEx": "櫃買",
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


def _event_fact(event: dict[str, Any]) -> str:
    source = str(event.get("source_key") or event.get("source") or "").casefold()
    fields = (
        ("event", "summary", "chinese_translation", "headline", "original_headline", "title", "public_short_message")
        if source != "financialjuice"
        else ("event", "chinese_translation", "headline", "summary", "public_short_message", "original_headline", "title")
    )
    for field in fields:
        candidate = _clean_text(event.get(field))
        if not _is_fragment(candidate):
            return candidate.rstrip("。！？.!?") + "。"
    return ""


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
    "quote_delayed", "stale_used",
)


def _quote_evidence(items: Any) -> list[dict[str, Any]]:
    """Keep only release-bound quotes with enough values for a public card."""
    if not isinstance(items, list):
        return []
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or "").strip().upper()
        if not ticker or ticker in seen or item.get("price") is None or item.get("change_percent") is None:
            continue
        try:
            if not math.isfinite(float(item["price"])) or not math.isfinite(float(item["change_percent"])):
                continue
        except (TypeError, ValueError):
            continue
        seen.add(ticker)
        result.append({key: item[key] for key in _QUOTE_EVIDENCE_FIELDS if key in item})
    return result


def _source_evidence(event: dict[str, Any], source: str) -> list[dict[str, Any]]:
    return [{
        "source": source,
        "source_key": event.get("source_key") or event.get("source"),
        "observation_id": event.get("observation_id"),
        "notification_id": event.get("notification_id"),
        "published_at": event.get("published_at") or event.get("created_at"),
    }]


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


def _theme_for_event(event: dict[str, Any], fact: str) -> dict[str, Any]:
    source = _event_source(event)
    why = _clean_text(event.get("why_important") or event.get("importance_detail") or event.get("trigger"))
    impact = _clean_text(event.get("possible_linkage") or event.get("possible_impact") or event.get("market_context"))
    watch = _clean_text(event.get("stock_observation") or event.get("watch") or event.get("follow_up_observation"))
    source_evidence = _source_evidence(event, source)
    quote_evidence = _quote_evidence(event.get("market_evidence"))
    canonical_event_key = _event_key(event, fact)
    return {
        "title": source,
        "what_happened": fact,
        "why_important": why or "事件事實已完成公開來源核對。",
        "market_implication": impact or "等待相關市場價格與後續公開資料核對，不直接推定因果。",
        "stock_observation": watch or "持續觀察台美主要指數、利率與相關產業價格。",
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
    }


def _theme_for_quotes(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    clauses = [_quote_clause(item) for item in items if _usable_quote(item)]
    clauses = [value for value in clauses if value]
    if not clauses:
        return None
    quote_evidence = _quote_evidence(items[:3])
    return {
        "title": "市場價格",
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
    }


def _news_events(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Project the existing reviewed news artifact into digest candidates."""
    news = snapshot.get("news")
    if not isinstance(news, dict):
        return []
    rows: list[dict[str, Any]] = []
    markets = news.get("markets") or news.get("intelligence") or news
    if isinstance(markets, dict):
        containers = list(markets.values())
    else:
        containers = [markets]
    for container in containers:
        stories = container.get("stories") if isinstance(container, dict) else container
        if not isinstance(stories, list):
            continue
        for story in stories:
            if not isinstance(story, dict):
                continue
            projected = dict(story)
            projected.setdefault("source_key", "news")
            projected.setdefault("source", story.get("source_name") or "公開市場新聞")
            projected.setdefault("event", story.get("summary") or story.get("description") or story.get("headline") or story.get("title"))
            rows.append(projected)
    return rows


def _fit_sentence(prefix: str, clauses: list[str], limit: int) -> str:
    chosen = prefix
    for clause in clauses:
        candidate = f"{chosen}{clause}" if chosen.endswith(("｜", "：", " ")) else f"{chosen}；{clause}"
        if len(candidate) <= limit:
            chosen = candidate
    return chosen.rstrip("；，、")


def build_market_digest(snapshot: dict[str, Any], slot: str) -> dict[str, Any]:
    """Build the shared dashboard/Telegram market assessment."""
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

    candidates: list[tuple[dict[str, Any], str]] = []
    seen: set[str] = set()
    for event in raw_events:
        # Threshold market signals remain in the instant-alert lane.  Their
        # verbose machine-formatted event text is not a digest fact; the
        # canonical quote theme below presents the same move readably.
        if str(event.get("kind") or "").casefold() == "market_signal":
            continue
        source = str(event.get("source_key") or event.get("source") or event.get("content_origin") or "").casefold()
        if source in {"haojiao", "jenny", "gooaye", "creator"}:
            continue
        if not _within_lookback(event, as_of):
            continue
        fact = _event_fact(event)
        if not fact:
            continue
        key = _event_key(event, fact)
        if key in seen:
            continue
        seen.add(key)
        candidates.append((event, fact))

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

    event_themes = [_theme_for_event(event, fact) for event, fact in candidates]
    all_quotes = [
        item for item in [*(snapshot.get("indices") or []), *(snapshot.get("quotes") or []), *(snapshot.get("macro_quotes") or [])]
        if isinstance(item, dict)
    ]
    quote_priority = ["NASDAQ", "SOX", "DJIA", "TAIEX", "US10Y", "DXY", "GOLD", "WTI"]
    quote_items = sorted(
        [item for item in all_quotes if str(item.get("ticker") or "") in quote_priority],
        key=lambda item: quote_priority.index(str(item.get("ticker") or "")),
    )
    quote_theme = _theme_for_quotes(quote_items)
    primary_theme = event_themes[0] if event_themes else quote_theme
    if primary_theme is None:
        return {
            "status": "suppressed",
            "notification_eligible": False,
            "notification_reason": "insufficient_evidence",
            "assessment_summary": "",
            "overview": "本輪公開市場證據不足，暫不形成判讀。",
            "public_short_message": "",
            "themes": [],
            "primary_theme": None,
            "secondary_signals": [],
            "displayed_event_keys": [],
            "evidence": [],
            "source_evidence": [],
            "quote_evidence": [],
        }
    if event_themes and not primary_theme.get("quote_evidence") and quote_theme:
        # An event may only carry ticker references after the source router
        # has compacted its payload.  Hydrate the primary theme from the same
        # release-bound snapshot, never from a different historical snapshot.
        primary_theme = {
            **primary_theme,
            "quote_evidence": list(quote_theme.get("quote_evidence") or [])[:2],
        }

    themes = [primary_theme]
    secondary_themes = [theme for theme in event_themes[1:] if theme.get("canonical_event_key") != primary_theme.get("canonical_event_key")]
    if quote_theme and quote_theme.get("canonical_event_key") != primary_theme.get("canonical_event_key"):
        secondary_themes.append(quote_theme)
    themes.extend(secondary_themes[:2])

    # Prices are evidence attached to the event, not a second copy of the
    # event's public narrative.  Keep quote-only briefings meaningful, while
    # preventing a refreshed quote from changing the identity of an event
    # briefing or making the Telegram summary oscillate between runs.
    summary_themes = event_themes[:3] if event_themes else [quote_theme]

    secondary_signals: list[dict[str, Any]] = []
    seen_secondary: set[str] = {str(primary_theme.get("canonical_event_key") or "")}
    for theme in secondary_themes:
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
            "source_event_keys": theme.get("source_event_keys") or [],
            "rank_reason": "重要度／核對狀態／發布時間／穩定事件鍵",
        })
        if len(secondary_signals) >= 3:
            break

    facts = [str(theme["what_happened"]).rstrip("。") + "。" for theme in summary_themes if theme]
    if not facts:
        return {
            "status": "suppressed",
            "notification_eligible": False,
            "notification_reason": "insufficient_evidence",
            "assessment_summary": "",
            "overview": "本輪公開市場證據不足，暫不形成判讀。",
            "public_short_message": "",
            "themes": [],
            "primary_theme": None,
            "secondary_signals": [],
            "displayed_event_keys": [],
            "evidence": [],
            "source_evidence": [],
            "quote_evidence": [],
        }

    label = _SLOT_LABELS.get(slot, "市場")
    overview = _fit_sentence("今日判讀：", facts, DASHBOARD_SUMMARY_MAX_CHARS)
    if overview == "今日判讀：":
        overview = ""
    message_clauses = facts[:2]
    public_message = summarize_public_message(
        f"{label}｜" + "｜".join(message_clauses),
        message_kind="scheduled_brief",
        label=label,
        limit=PUBLIC_MESSAGE_MAX_CHARS,
    )
    if public_message and not len(public_message) <= PUBLIC_MESSAGE_MAX_CHARS:
        public_message = ""

    canonical_material = {
        "slot": slot,
        "overview": overview,
        "public_short_message": public_message,
        # Quote hydration is release-bound evidence, not notification
        # identity.  Keep the values in the artifact, but exclude them from
        # the content hash so a refreshed quote cannot resend the same event.
        "themes": [
            {key: value for key, value in theme.items() if key != "quote_evidence"}
            for theme in summary_themes
            if theme
        ],
    }
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
        "canonical_hash_version": 1,
        "assessment_summary": overview,
        "overview": overview,
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
