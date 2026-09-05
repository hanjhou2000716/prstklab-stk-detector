"""Deterministic multi-source market briefings.

The digest is deliberately rule based.  It combines already reviewed market
observations and public events into one release-bound object; it never invents
facts, infers causality, or calls an external model.
"""

from __future__ import annotations

import hashlib
import json
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
    "intraday": "盤中",
    "midday": "午報",
    "afternoon": "午盤",
    "post_close": "盤後",
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
    source = str(event.get("source_key") or event.get("source") or "").casefold()
    return hashlib.sha256(f"{source}|{_normalise(fact).casefold()}".encode()).hexdigest()[:20]


def _importance_score(event: dict[str, Any]) -> float:
    value = event.get("vendor_importance")
    if value is None:
        value = event.get("importance")
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return {"high-risk": 3.0, "warning": 2.0, "normal": 1.0}.get(str(value).casefold(), 0.0)


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
    return bool(item.get("change_percent") is not None and item.get("price") is not None)


def _theme_for_event(event: dict[str, Any], fact: str) -> dict[str, Any]:
    source = _event_source(event)
    why = _clean_text(event.get("why_important") or event.get("importance_detail") or event.get("trigger"))
    impact = _clean_text(event.get("possible_linkage") or event.get("possible_impact") or event.get("market_context"))
    watch = _clean_text(event.get("stock_observation") or event.get("watch") or event.get("follow_up_observation"))
    return {
        "title": source,
        "what_happened": fact,
        "why_important": why or "事件事實已完成公開來源核對。",
        "market_implication": impact or "等待相關市場價格與後續公開資料核對，不直接推定因果。",
        "stock_observation": watch or "持續觀察台美主要指數、利率與相關產業價格。",
        "evidence": [{
            "source": source,
            "source_key": event.get("source_key") or event.get("source"),
            "observation_id": event.get("observation_id"),
            "notification_id": event.get("notification_id"),
            "published_at": event.get("published_at") or event.get("created_at"),
        }],
        "event_key": _event_key(event, fact),
    }


def _theme_for_quotes(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    clauses = [_quote_clause(item) for item in items if _usable_quote(item)]
    clauses = [value for value in clauses if value]
    if not clauses:
        return None
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
        "event_key": hashlib.sha256("|".join(clauses[:3]).encode("utf-8")).hexdigest()[:20],
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

    def candidate_sort_key(pair: tuple[dict[str, Any], str]) -> tuple[int, float, float, str]:
        timestamp = _event_timestamp(pair[0])
        return (
            0 if pair[0].get("notification_status") == "eligible" else 1,
            -_importance_score(pair[0]),
            -(timestamp.timestamp() if timestamp else 0),
            _event_key(pair[0], pair[1]),
        )

    candidates.sort(key=candidate_sort_key)

    event_themes = [_theme_for_event(event, fact) for event, fact in candidates[:2]]
    themes = event_themes[:1]
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
    if quote_theme and len(themes) < 3:
        themes.append(quote_theme)
    if len(themes) < 3:
        themes.extend(event_themes[1:2])

    facts = [str(theme["what_happened"]).rstrip("。") + "。" for theme in themes]
    if not facts:
        return {
            "status": "suppressed",
            "notification_eligible": False,
            "notification_reason": "insufficient_evidence",
            "assessment_summary": "",
            "overview": "本輪公開市場證據不足，暫不形成判讀。",
            "public_short_message": "",
            "themes": [],
            "evidence": [],
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
        "themes": themes,
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
        "evidence": [evidence for theme in themes for evidence in theme.get("evidence", [])],
        "lookback_hours": 24,
        "as_of": generated or as_of.isoformat(),
        "slot": slot,
    }
