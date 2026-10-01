"""Release-bound, deterministic market-session news selection for briefing cards."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, UTC
from typing import Any
from zoneinfo import ZoneInfo

_SLOT_TARGETS = {
    "morning": ("us", "close", "最近完成的美股收盤重點"),
    "pre_open": ("taiwan", "open", "台股開盤／盤前焦點"),
    "post_close": ("taiwan", "close", "台股收盤重點"),
    "us_premarket": ("us", "open", "美股盤前／開盤焦點"),
}
_MARKETS = {
    "taiwan": ("XTAI", "Asia/Taipei", "台股"),
    "us": ("NYSE", "America/New_York", "美股"),
}
_INDEX_NAMES = {
    "TAIEX": "加權指數", "TWII": "加權指數", "S&P 500": "標普500",
    "SPX": "標普500", "NASDAQ": "那斯達克綜合", "IXIC": "那斯達克綜合",
    "DJIA": "道瓊", "SOX": "費半",
}
_CJK = re.compile(r"[\u3400-\u9fff]")
_SENTENCE_END = re.compile(r"(?<=[。！？.!?])")


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _session_dates(market: str, as_of: datetime, mode: str) -> tuple[date | None, date | None]:
    calendar_name, market_timezone, _label = _MARKETS[market]
    local_day = as_of.astimezone(ZoneInfo(market_timezone)).date()
    try:
        import pandas_market_calendars as mcal

        calendar = mcal.get_calendar(calendar_name)
        schedule = calendar.schedule(
            start_date=local_day - timedelta(days=21),
            end_date=local_day + timedelta(days=1),
        )
    except Exception:
        return None, None
    sessions: list[tuple[date, datetime, datetime]] = []
    for session_day, row in schedule.iterrows():
        opened = row.get("market_open")
        closed = row.get("market_close")
        if opened is None or closed is None:
            continue
        opened_at = opened.to_pydatetime() if hasattr(opened, "to_pydatetime") else opened
        closed_at = closed.to_pydatetime() if hasattr(closed, "to_pydatetime") else closed
        sessions.append((session_day.date(), opened_at.astimezone(timezone.utc), closed_at.astimezone(timezone.utc)))
    if not sessions:
        return None, None
    if mode == "close":
        eligible = [item for item in sessions if item[2] <= as_of]
        if not eligible:
            return None, None
        target = eligible[-1][0]
    else:
        today = next((item[0] for item in sessions if item[0] == local_day), None)
        eligible = [item[0] for item in sessions if item[0] <= local_day]
        target = today or (eligible[-1] if eligible else None)
    if target is None:
        return None, None
    prior = [item[0] for item in sessions if item[0] < target]
    return target, prior[-1] if prior else None


def _news_candidates(snapshot: dict[str, Any], market: str) -> list[dict[str, Any]]:
    news = snapshot.get("news") if isinstance(snapshot.get("news"), dict) else {}
    intelligence = news.get("intelligence") if isinstance(news.get("intelligence"), dict) else {}
    market_news = intelligence.get(market) if isinstance(intelligence.get(market), dict) else {}
    candidates = market_news.get("editorial_candidates")
    if not isinstance(candidates, list):
        candidates = market_news.get("stories")
    return [item for item in candidates if isinstance(item, dict)] if isinstance(candidates, list) else []


def _story_key(story: dict[str, Any]) -> str:
    return str(story.get("event_cluster_key") or story.get("dedupe_key") or story.get("canonical_url") or story.get("url") or story.get("title") or "").strip()


def _story_matches(story: dict[str, Any], market: str, target_day: date, previous_day: date | None, cutoff: datetime) -> tuple[bool, date | None, datetime | None]:
    if story.get("public_news_eligible") is not True:
        return False, None, None
    if str(story.get("market") or "").strip().casefold() != market:
        return False, None, None
    title = str(story.get("title") or "").strip()
    url = str(story.get("canonical_url") or story.get("url") or "").strip()
    published = _parse_time(story.get("published_at"))
    if not title or not url.startswith("https://") or published is None or published > cutoff:
        return False, None, None
    local_day = published.astimezone(ZoneInfo(_MARKETS[market][1])).date()
    if local_day != target_day and local_day != previous_day:
        return False, None, None
    return True, local_day, published


def _slot_terms(slot: str) -> tuple[str, ...]:
    if slot in {"morning", "post_close"}:
        return ("收盤", "close", "closing", "market wrap", "收市")
    return ("盤前", "開盤", "premarket", "pre-market", "opening", "開市")


def _candidate_rank(story: dict[str, Any], local_day: date, target_day: date, slot: str, market: str, published: datetime) -> tuple[Any, ...]:
    text = " ".join(str(story.get(key) or "") for key in ("title", "summary", "description", "topics", "sectors")).casefold()
    slot_match = int(any(term.casefold() in text for term in _slot_terms(slot)))
    index_terms = ("指數", "加權", "標普", "那斯達克", "道瓊", "費半", "index", "s&p", "nasdaq", "dow", "stocks", "market", "equity")
    index_match = int(any(term.casefold() in text for term in index_terms))
    authority = str(story.get("source_tier") or story.get("authority_tier") or "").casefold()
    source_rank = {"official": 3, "primary": 3, "market": 2, "reputable": 1}.get(authority, 0)
    chinese = int(bool(_CJK.search(str(story.get("title") or "") + " " + str(story.get("summary") or ""))))
    return (int(local_day == target_day), slot_match, index_match, source_rank, chinese, published.timestamp(), _story_key(story))


def _quote_observation(quote_items: list[dict[str, Any]], market: str) -> str | None:
    preferred = ("TAIEX", "TWII") if market == "taiwan" else ("S&P 500", "NASDAQ", "DJIA", "SOX")
    by_ticker = {str(item.get("ticker") or "").strip().upper(): item for item in quote_items if isinstance(item, dict)}
    for ticker in preferred:
        quote = by_ticker.get(ticker.upper())
        if not quote or quote.get("stale_used") is True:
            continue
        freshness = str(quote.get("freshness") or quote.get("data_status") or "").casefold()
        if freshness in {"stale", "delayed", "unavailable", "unknown", "failed"}:
            continue
        if not any(quote.get(key) for key in ("quote_time", "quote_date", "date", "observed_at")):
            continue
        try:
            price = float(quote.get("price"))
        except (TypeError, ValueError):
            continue
        if not (price > 0 and price == price and abs(price) != float("inf")):
            continue
        value = quote.get("change_percent")
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if not (number == number and abs(number) != float("inf")):
            continue
        name = _INDEX_NAMES.get(ticker, "市場指數")
        direction = "上漲" if number > 0 else "下跌" if number < 0 else "持平"
        percent = f"{number:+.2f}%" if number else "0.00%"
        observed_date = str(quote.get("quote_date") or quote.get("date") or "")[:10]
        try:
            date.fromisoformat(observed_date)
        except ValueError:
            observed_date = ""
        date_note = f"（資料日 {observed_date}）" if observed_date else ""
        return f"行情觀察：{name}最近收盤{direction}{percent}{date_note}，僅作價格參考，不推論新聞因果。"
    return None


def _complete_summary_sentence(summary: str) -> str | None:
    clean = " ".join(summary.split())
    if not clean or not _CJK.search(clean):
        return None
    pieces = [piece.strip() for piece in _SENTENCE_END.split(clean) if piece.strip()]
    candidate = pieces[0] if pieces else clean
    if candidate[-1] not in "。！？.!?":
        candidate += "。"
    if len(candidate) > 82:
        return None
    return candidate


def build_session_news_summary(
    snapshot: dict[str, Any],
    slot: str,
    as_of: datetime,
    quote_items: list[dict[str, Any]],
    *,
    market_scope_key: str | None = None,
) -> dict[str, Any]:
    """Select one public-gate-passed story and bind its summary to this release snapshot."""
    market, mode, session_kind = _SLOT_TARGETS.get(
        slot, (market_scope_key or "", "open", "當前市場時段焦點"),
    )
    if market not in _MARKETS:
        return {
            "status": "unavailable", "selection_reason": "unsupported_slot", "slot": slot,
            "market_scope_key": market_scope_key or "global", "session_kind": session_kind,
            "headline": "", "summary_sentences": ["時段無法核實，暫不選取新聞。", "資料不足，暫無可核實總結。"],
            "summary": "時段無法核實，暫不選取新聞。資料不足，暫無可核實總結。", "source": "", "source_url": "",
            "published_at": None, "story_id": "", "target_session_date": None,
            "reference_label": "資料不足", "quote_evidence": [],
        }
    target_day, previous_day = _session_dates(market, as_of, mode)
    candidates: list[tuple[tuple[Any, ...], dict[str, Any], date, datetime]] = []
    if target_day:
        seen: set[str] = set()
        for story in _news_candidates(snapshot, market):
            matched, local_day, published = _story_matches(story, market, target_day, previous_day, as_of)
            key = _story_key(story)
            if not matched or local_day is None or published is None or not key or key in seen:
                continue
            seen.add(key)
            candidates.append((_candidate_rank(story, local_day, target_day, slot, market, published), story, local_day, published))
    selected = max(candidates, key=lambda item: item[0]) if candidates else None
    label = _MARKETS[market][2]
    current_market_day = as_of.astimezone(ZoneInfo(_MARKETS[market][1])).date()
    quote_sentence = _quote_observation(quote_items, market)
    if selected:
        _rank, story, story_day, published = selected
        headline = str(story.get("title") or "").strip()
        source = str(story.get("provider_name") or story.get("provider_display_name") or story.get("provider") or story.get("source") or "公開來源").strip()
        source_url = str(story.get("canonical_url") or story.get("url") or "").strip()
        if not source_url.startswith("https://"):
            source_url = ""
        source_sentence = _complete_summary_sentence(str(story.get("summary") or ""))
        news_sentence = source_sentence or "來源未提供可核實中文摘要，請參閱原文。"
        market_sentence = quote_sentence or "行情資料不足，暫不合併判讀。"
        sentences = [news_sentence, market_sentence]
        is_target_session = story_day == target_day and (mode == "close" or target_day == current_market_day)
        status = "selected" if is_target_session else "recent_session_reference"
        reference_label = f"{label}目標時段｜資料日 {story_day.isoformat()}"
        if not is_target_session:
            reference_label = f"最近交易日參考｜{story_day.isoformat()}（非本日）"
        return {
            "status": status, "selection_reason": "session_relevance_rank", "slot": slot,
            "market_scope_key": market, "session_kind": session_kind,
            "target_session_date": target_day.isoformat(), "reference_label": reference_label,
            "headline": headline, "summary_sentences": sentences,
            "summary": " ".join(sentences), "source": source, "source_url": source_url,
            "published_at": published.isoformat(), "story_id": _story_key(story),
            "quote_evidence": [dict(item) for item in quote_items[:4] if isinstance(item, dict)],
        }
    sentences = [
        "本時段未取得符合資格的市場新聞。",
        quote_sentence or "資料不足，暫無可核實總結。",
    ]
    status = "market_data_fallback" if quote_sentence else "unavailable"
    return {
        "status": status, "selection_reason": "no_eligible_session_news", "slot": slot,
        "market_scope_key": market, "session_kind": session_kind,
        "target_session_date": target_day.isoformat() if target_day else None,
        "reference_label": f"{label}目標時段｜資料日 {target_day.isoformat()}" if target_day else "時段日期未核實",
        "headline": "市場開收盤焦點｜新聞未取得" if quote_sentence else "資料不足，暫無可核實總結",
        "summary_sentences": sentences, "summary": " ".join(sentences),
        "source": "", "source_url": "", "published_at": None, "story_id": "",
        "quote_evidence": [dict(item) for item in quote_items[:4] if isinstance(item, dict)],
    }


def bind_session_news_identity(summary: dict[str, Any], release_id: Any, snapshot_id: Any) -> dict[str, Any]:
    """Return a copy carrying the exact public release and snapshot identity."""
    market = str(summary.get("market_scope_key") or "")
    timezone_name = _MARKETS.get(market, ("", "UTC", ""))[1]
    return {
        **summary,
        "schema_version": "session-news-summary-v1",
        "timezone": timezone_name,
        "release_id": str(release_id or ""),
        "snapshot_id": str(snapshot_id or ""),
    }
