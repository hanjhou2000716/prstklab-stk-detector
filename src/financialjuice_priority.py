"""Project qualifying FinancialJuice observations into the release event lane.

FinancialJuice is a discovery source.  Its vendor importance score can make an
item eligible for a vendor-priority notification, but it never upgrades the
PRStK risk level and never bypasses the release gate.  This projection keeps
the decision visible in the public snapshot so a skipped or deduplicated item
is auditable instead of silently disappearing.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any

from src.external_event_pipeline import build_external_events

_NEUTRAL_STOCK_OBSERVATION = "等待官方後續確認，並觀察相關市場是否同步反應。"
_NEUTRAL_IMPORTANCE = "目前尚無額外重要性說明，等待後續公開資料核對。"
_NEUTRAL_LINKAGE = "尚無足夠公開資料判定連動。"
_INCOMPLETE_EVENT = "資訊待核對"
_MAX_FIELD_CHARS = 600
_GENERIC_EVENT_VALUES = frozenset({
    "financialjuice 公開快訊", "financialjuice|financialjuice 公開快訊",
    "資訊待核對", "information pending", "pending information",
})
_STALE_QUOTE_VALUES = frozenset({"stale", "delayed", "unavailable", "unknown", "failed", "失效", "延遲", "不可用"})
_MARKET_RULES: tuple[tuple[str, tuple[str, ...], frozenset[str], int], ...] = (
    ("WTI", ("wti", "west texas", "西德州", "原油", "oil", "crude", "荷姆茲", "hormuz"), frozenset({"energy", "conflict", "macro"}), 1),
    ("BRENT", ("brent", "布蘭特", "油價", "原油", "oil", "crude", "荷姆茲", "hormuz"), frozenset({"energy", "conflict", "macro"}), 2),
    ("GOLD", ("gold", "黃金", "避險"), frozenset({"conflict", "macro"}), 3),
    ("US10Y", ("us10y", "10-year", "treasury", "殖利率", "利率", "rate", "yield"), frozenset({"fed", "macro", "policy"}), 4),
    ("DXY", ("dxy", "美元", "dollar"), frozenset({"fed", "macro", "policy", "conflict"}), 5),
    ("SOX", ("sox", "費半", "半導體", "semiconductor", "chip", "gpu"), frozenset({"semiconductor", "policy", "market"}), 6),
    ("TSM", ("tsm", "tsmc", "台積", "台積電"), frozenset({"semiconductor", "policy"}), 7),
    ("2330", ("2330", "台積", "台積電", "tsmc"), frozenset({"semiconductor", "policy"}), 8),
    ("NVDA", ("nvda", "nvidia", "gpu"), frozenset({"semiconductor", "policy"}), 9),
    ("NASDAQ", ("nasdaq", "那斯達克", "科技股", "tech stocks"), frozenset({"fed", "macro", "semiconductor", "policy", "market", "conflict"}), 10),
    ("TAIEX", ("taiex", "台股", "台灣加權", "台灣股市"), frozenset({"market", "semiconductor", "policy", "conflict"}), 11),
)
_TRANSLATION_LABELS = (
    "chinese translation", "translation", "繁體中文翻譯", "中文翻譯", "翻譯",
)
_ANALYSIS_LABELS = (
    "ai commentary", "AI 評論", "AI評論", "AI analysis", "AI分析", "AI 分析",
)
_IMPACT_LABELS = (
    "possible impact", "vendor impact", "impact", "可能影響", "市場影響",
)
_ORIGINAL_LABELS = ("original headline", "vendor original headline", "headline", "原始標題", "原文內容", "原文")
_SECTION_STOP_LABELS = (*_ANALYSIS_LABELS, *_IMPACT_LABELS, *_ORIGINAL_LABELS, "source url", "來源連結")
_HEADER_LABELS = (*_TRANSLATION_LABELS, "重要性評分", "importance")
_ORIGINAL_CONTENT_PATTERN = re.compile(
    r"(?:^|[\s📄])(?:原文內容|原文)(?:\s*[:：]|\s+(?=[A-Za-z]))",
    re.IGNORECASE,
)


def _clip(value: str, limit: int = _MAX_FIELD_CHARS) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit - 1].rstrip()}…"


def _is_metadata_only_analysis(value: Any) -> bool:
    """Exclude score/placeholder labels from the public importance field."""
    text = " ".join(str(value or "").split()).strip()
    if not text or text == _NEUTRAL_IMPORTANCE:
        return True
    compact = re.sub(r"[\s📝💡📄⚠️📌🔎📈📉📊🚨]+", "", text).casefold()
    return bool(re.fullmatch(r"(?:重要性評分|importance(?:score)?)[：:]?\d+(?:\.\d+)?(?:/10)?", compact))


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _source(row: dict[str, Any]) -> str:
    return str(row.get("source") or row.get("content_origin") or "").strip().casefold()


def _mapping(value: Any) -> dict[str, Any]:
    """Return a concrete mapping for mypy and defensive producer boundaries."""
    return value if isinstance(value, dict) else {}


def _observation_id_hash(value: Any) -> str | None:
    """Hash the reviewed observation key before it enters delivery evidence."""
    text = str(value or "").strip()
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None


def _nonnegative_number(value: Any) -> int | float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None
    return int(number) if number.is_integer() else number


def _source_views(result: dict[str, Any], row: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the current item's raw and normalized views in priority order.

    Compound events arrive as an envelope row, so their item-level rich fields
    live in ``source_evidence`` after the shared pipeline normalizes the item.
    Prefer evidence matching the current identity to prevent one item's
    commentary or impact from being assigned to another item.
    """
    evidence = [item for item in (result.get("source_evidence") or []) if isinstance(item, dict)]
    identity = {
        str(row.get(key) or result.get(key) or "").strip()
        for key in ("item_id", "observation_id", "event_cluster_key")
        if str(row.get(key) or result.get(key) or "").strip()
    }
    matching = [
        item for item in evidence
        if identity.intersection({
            str(item.get(key) or "").strip()
            for key in ("item_id", "observation_id", "event_cluster_key")
            if str(item.get(key) or "").strip()
        })
    ]
    ordered = [row, *matching, result]
    ordered.extend(item for item in evidence if item not in matching)
    return ordered


def _first_text(views: list[dict[str, Any]], *keys: str) -> str:
    for view in views:
        for key in keys:
            value = view.get(key)
            # Optional parser fields are public text, not arbitrary JSON.
            # Ignore malformed containers instead of leaking ``[]`` or a
            # repr of a private object into the release/UI.
            if not isinstance(value, (str, int, float)) or isinstance(value, bool):
                continue
            text = str(value).strip()
            if text:
                return text
    return ""


def _first_value(views: list[dict[str, Any]], *keys: str) -> Any:
    for view in views:
        for key in keys:
            value = view.get(key)
            if value is not None and str(value).strip():
                return value
    return None


def _label_pattern(labels: tuple[str, ...]) -> re.Pattern[str]:
    choices = sorted({label for label in labels if label}, key=len, reverse=True)
    return re.compile(
        r"(?:^|[\s📝💡📄⚠️📌🔎📈📉📊🚨])(?:"
        + "|".join(re.escape(label) for label in choices)
        + r")\s*[:：]",
        re.IGNORECASE,
    )


def _clean_semantic_text(value: Any, *, kind: str) -> str:
    """Split known FJ labels without inventing or rewriting source text."""
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return ""
    text = " ".join(str(value).split()).strip()
    if not text:
        return ""
    if kind == "translation":
        text = _after_label(text, _TRANSLATION_LABELS)
        text = _before_label(text, _SECTION_STOP_LABELS)
        text = _before_original_content(text)
    elif kind == "analysis":
        if _label_pattern(_ANALYSIS_LABELS).search(text):
            text = _after_label(text, _ANALYSIS_LABELS)
        elif _label_pattern(_HEADER_LABELS).search(text):
            # A header-only legacy value is not commentary.  Do not expose it
            # as the explanation for why an event matters.
            return ""
        text = _before_label(text, (*_IMPACT_LABELS, *_ORIGINAL_LABELS, "source url", "來源連結"))
    elif kind == "impact":
        text = _after_label(text, _IMPACT_LABELS)
        text = _before_label(text, (*_ORIGINAL_LABELS, "source url", "來源連結"))
        text = _before_original_content(text)
    elif kind == "headline":
        text = _after_label(text, _ORIGINAL_LABELS)
        text = _before_label(text, (*_TRANSLATION_LABELS, *_ANALYSIS_LABELS, *_IMPACT_LABELS, "source url", "來源連結"))
    return text.strip(" \t:：-–—📝💡📄⚠️📌🔎📈📉📊🚨")


def _after_label(text: str, labels: tuple[str, ...]) -> str:
    match = _label_pattern(labels).search(text)
    return text[match.end():].lstrip() if match else text


def _before_label(text: str, labels: tuple[str, ...]) -> str:
    match = _label_pattern(labels).search(text)
    return text[:match.start()] if match else text


def _before_original_content(text: str) -> str:
    match = _ORIGINAL_CONTENT_PATTERN.search(text)
    return text[:match.start()] if match else text


def _first_clean_text(views: list[dict[str, Any]], kind: str, *keys: str) -> str:
    for view in views:
        for key in keys:
            value = _clean_semantic_text(view.get(key), kind=kind)
            if value:
                return value
    return ""


def _is_generic_event(value: Any) -> bool:
    text = " ".join(str(value or "").split()).strip().casefold().rstrip("。.!！")
    return not text or text in _GENERIC_EVENT_VALUES or text.startswith("financialjuice 公開快訊")


def _material_event_text(views: list[dict[str, Any]]) -> str:
    """Return a real FJ event fact, excluding generated placeholder labels."""
    candidates = (
        _first_clean_text(views, "translation", "chinese_translation", "vendor_translation"),
        _first_clean_text(views, "headline", "translated_headline", "original_headline", "vendor_original_headline", "headline", "title", "event"),
    )
    return next((text for text in candidates if not _is_generic_event(text)), "")


def _fallback_why_important(event: str, linkage: str, importance: Any) -> str:
    """Explain a score-only FJ item from its existing public-safe evidence."""
    if _is_generic_event(event):
        return _NEUTRAL_IMPORTANCE
    score = (
        f"來源快訊標示重要度 {str(importance).strip()}/10"
        if importance is not None and str(importance).strip()
        else "來源快訊已提供事件內容"
    )
    basis = linkage if linkage and linkage != _NEUTRAL_LINKAGE else f"事件內容「{event}」"
    return _clip(
        f"{score}；來源影響評估：{basis}；仍待官方或第二來源核對。",
        limit=_MAX_FIELD_CHARS,
    )


def _market_rows(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Flatten the canonical market snapshot without fabricating instruments."""
    if not isinstance(snapshot, dict):
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in ("indices", "macro_quotes", "quotes", "markets"):
        value = snapshot.get(key)
        values = value if isinstance(value, list) else list(value.values()) if isinstance(value, dict) else []
        for row in values:
            if not isinstance(row, dict):
                continue
            ticker = str(row.get("ticker") or row.get("symbol") or "").strip().upper()
            if not ticker or ticker in seen:
                continue
            seen.add(ticker)
            rows.append(row)
    return rows


def _registry_aliases(snapshot: dict[str, Any] | None, ticker: str) -> tuple[str, ...]:
    registry = snapshot.get("instrument_master") if isinstance(snapshot, dict) else None
    instruments = registry.get("instruments") if isinstance(registry, dict) else None
    for instrument in instruments if isinstance(instruments, list) else []:
        if not isinstance(instrument, dict) or str(instrument.get("ticker") or "").strip().upper() != ticker:
            continue
        values = [instrument.get("ticker"), instrument.get("name"), *(instrument.get("symbols") or ()), *(instrument.get("aliases") or ())]
        return tuple(str(value).strip().casefold() for value in values if str(value or "").strip())
    return ()


def _market_fresh(row: dict[str, Any]) -> bool:
    freshness = str(row.get("quality_freshness") or row.get("freshness") or row.get("data_status") or "").strip().casefold()
    return (
        bool(freshness) and freshness not in _STALE_QUOTE_VALUES
        and row.get("stale_used") is not True
        and row.get("quote_delayed") is not True
        and row.get("data_status") not in {"stale", "延遲", "不可用", "失敗"}
    )


def _annotated_market_row(row: dict[str, Any]) -> dict[str, Any]:
    """Recover freshness labels when a producer supplied only date and price."""
    if row.get("freshness"):
        item = dict(row)
        item.setdefault("data_status", {
            "live": "盤中",
            "recent_close": "最近收盤",
            "stale": "資料過期",
            "unavailable": "暫無資料",
        }.get(str(item["freshness"]), "時間待核對"))
        return item
    # Import lazily to keep the parser usable without importing the collection
    # layer during module initialization.
    from src.market_data import annotate_quote_freshness
    item = annotate_quote_freshness([row])[0]
    # A compact FJ market-evidence row may carry only a completed quote date
    # and price.  That is not proof of staleness; preserve it as a dated close
    # while keeping explicit stale/delayed/unavailable markers fail-closed.
    if (
        item.get("freshness") == "stale"
        and item.get("quote_time") in (None, "")
        and item.get("quote_date")
        and item.get("price") is not None
    ):
        item["freshness"] = "recent_close"
        item["data_status"] = "最近收盤"
    return item


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _market_intelligence(result: dict[str, Any], row: dict[str, Any], snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """Link one FJ event to at most two scored, registry-backed market rows."""
    views = _source_views(result, row)
    semantic = _semantic_projection(result, row)
    if snapshot is None:
        # Unit callers and offline parser previews may not have a market
        # snapshot.  Preserve the parsed vendor linkage verbatim in that mode.
        return {
            "linked_markets": [], "market_evidence": [],
            "market_sync_confirmed": False, "linkage_state": "not_evaluated",
            "possible_linkage": semantic["possible_linkage"],
            "stock_observation": semantic["stock_observation"],
        }
    text = " ".join([
        semantic["event"], semantic["why_important"], semantic["possible_linkage"],
        _first_text(views, "entities", "topics", "tickers", "event_type", "category"),
    ]).casefold()
    classification = _mapping(result.get("classification"))
    category = str(classification.get("category") or row.get("event_type") or row.get("category") or "").casefold()
    candidates: list[tuple[int, str, dict[str, Any]]] = []
    available = {
        str(market.get("ticker") or market.get("symbol") or "").strip().upper(): _annotated_market_row(market)
        for market in _market_rows(snapshot)
    }
    for ticker, aliases, categories, tie_break in _MARKET_RULES:
        market = available.get(ticker)
        if not market:
            continue
        registry_aliases = _registry_aliases(snapshot, ticker)
        direct_hits = sum(1 for alias in {ticker.casefold(), *aliases, *registry_aliases} if alias and alias in text)
        category_hit = category in categories
        if not direct_hits and not category_hit:
            continue
        score = float(direct_hits * 100 + (40 if category_hit else 0))
        if ticker in {"TAIEX", "TSM", "2330"}:
            score += 12
        if _market_fresh(market):
            score += 8
        score -= tie_break / 100
        candidates.append((int(score * 100), ticker, market))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    selected = candidates[:2]
    evidence: list[dict[str, Any]] = []
    for _, ticker, market in selected:
        evidence.append({
            "ticker": ticker,
            "name": market.get("name"),
            "market": market.get("market"),
            "instrument_id": market.get("instrument_id"),
            "instrument_master_id": market.get("instrument_master_id"),
            "price": market.get("price"),
            "change": market.get("change"),
            "change_percent": market.get("change_percent"),
            "direction_sign": market.get("direction_sign"),
            "market_direction": market.get("market_direction"),
            "quote_date": market.get("quote_date"),
            "fetched_at": market.get("fetched_at"),
            "freshness": market.get("freshness") or market.get("quality_freshness"),
            "data_status": market.get("data_status"),
            "stale_used": market.get("stale_used", False),
            "quote_delayed": market.get("quote_delayed", False),
            "source_url": market.get("source_url"),
            "observation_id": market.get("observation_id"),
        })
    fresh_moves: list[float] = []
    for item in evidence:
        if not _market_fresh(item):
            continue
        move = _number(item.get("change_percent"))
        if move is not None:
            fresh_moves.append(move)
    synchronized = bool(
        len(fresh_moves) >= 2
        and all(abs(move) >= 0.5 for move in fresh_moves)
        and (all(move > 0 for move in fresh_moves) or all(move < 0 for move in fresh_moves))
    )
    if not evidence:
        linkage_state = "insufficient_evidence"
        stock = "目前沒有足夠可驗證的市場資料建立連動，不做方向判定。"
        linkage = f"{semantic['possible_linkage']} 尚無足夠市場證據建立連動。"
    elif any(not _market_fresh(item) for item in evidence):
        linkage_state = "linked_data_stale"
        labels = "、".join(str(item.get("ticker")) for item in evidence)
        stock = f"{labels} 為主要關聯市場，目前價格訊號待更新，不做方向判定。"
        linkage = f"{semantic['possible_linkage']} 關聯市場：{labels}（資料待更新）。"
    elif synchronized:
        linkage_state = "synchronized_evidence"
        labels = "、".join(
            f"{item['ticker']} {float(item['change_percent']):+.2f}%"
            for item in evidence if _number(item.get("change_percent")) is not None
        )
        stock = f"關聯市場同步反應：{labels}。"
        linkage = f"{semantic['possible_linkage']} 關聯市場：{labels}。"
    else:
        linkage_state = "linked_no_obvious_sync"
        labels = "、".join(str(item.get("ticker")) for item in evidence)
        stock = f"關聯市場為{labels}，目前尚未出現明顯同步異動，持續觀察。"
        linkage = f"{semantic['possible_linkage']} 關聯市場：{labels}，目前尚無明顯同步證據。"
    return {
        "linked_markets": [item["ticker"] for item in evidence],
        "market_evidence": evidence,
        "market_sync_confirmed": synchronized,
        "linkage_state": linkage_state,
        "possible_linkage": linkage,
        "stock_observation": stock,
    }


def _embedded_clean_text(views: list[dict[str, Any]], labels: tuple[str, ...], *, stop: tuple[str, ...]) -> str:
    """Recover one labelled section embedded in another legacy field."""
    for view in views:
        for value in view.values():
            if not isinstance(value, (str, int, float)) or isinstance(value, bool):
                continue
            text = " ".join(str(value).split()).strip()
            if not _label_pattern(labels).search(text):
                continue
            extracted = _after_label(text, labels)
            extracted = _before_label(extracted, stop)
            extracted = _before_original_content(extracted)
            extracted = extracted.strip(" \t:：-–—📝💡📄⚠️📌🔎📈📉📊🚨")
            if extracted:
                return extracted
    return ""


def _semantic_projection(result: dict[str, Any], row: dict[str, Any]) -> dict[str, str]:
    """Project existing FJ facts into the canonical public semantic view.

    This function only selects already-parsed source text.  It never rewrites
    uncertainty, infers entities, or turns vendor commentary into a claim.
    Neutral text is used only for missing optional sections so the Mini App has
    a stable, non-hallucinatory fallback.
    """
    views = _source_views(result, row)
    event = _material_event_text(views)
    possible_linkage = _first_clean_text(
        views, "impact", "possible_impact", "vendor_possible_impact", "vendor_impact", "possible_linkage",
        "market_impact", "impact",
    ) or _NEUTRAL_LINKAGE
    why_important = _first_clean_text(
        views, "analysis", "ai_commentary", "vendor_analysis", "why_important", "importance_detail",
    )
    if _is_metadata_only_analysis(why_important):
        why_important = ""
    why_important = why_important or _embedded_clean_text(
        views, _ANALYSIS_LABELS,
        stop=(*_IMPACT_LABELS, *_ORIGINAL_LABELS, "source url", "來源連結"),
    ) or _fallback_why_important(
        event,
        possible_linkage,
        _first_value(views, "vendor_importance", "importance"),
    )
    stock_observation = _first_text(
        views, "stock_observation", "watch", "stock_watch", "follow_up_observation",
    ) or _NEUTRAL_STOCK_OBSERVATION
    return {
        "event": event or _INCOMPLETE_EVENT,
        "why_important": why_important,
        "possible_linkage": possible_linkage,
        "stock_observation": stock_observation,
    }


def _event_record(
    result: dict[str, Any], row: dict[str, Any], *, status: str, reasons: list[str],
    vendor_priority_notification: bool, market_snapshot: dict[str, Any] | None,
    material_event_present: bool, public_signal_eligible: bool,
) -> dict[str, Any]:
    risk = _mapping(result.get("risk"))
    cluster = _mapping(result.get("cluster"))
    views = _source_views(result, row)
    semantic = _semantic_projection(result, row)
    market = _market_intelligence(result, row, market_snapshot)
    semantic.update({
        "possible_linkage": market["possible_linkage"],
        "stock_observation": market["stock_observation"],
    })
    headline = _first_clean_text(
        views, "headline", "original_headline", "vendor_original_headline", "headline", "title",
    ) or semantic["event"]
    importance = _first_value(views, "vendor_importance", "importance")
    source_url = _first_text(views, "source_url", "url")
    observation_id = str(result.get("observation_id") or row.get("observation_id") or "").strip() or None
    item_id = str(
        row.get("item_id") or result.get("compound_item_id") or result.get("notification_id") or ""
    ).strip() or None
    cluster_key = str(result.get("event_cluster_key") or row.get("event_cluster_key") or "").strip() or None
    observation_hash = _observation_id_hash(observation_id or item_id)
    parser_version = str(
        row.get("parser_version") or result.get("parser_version") or result.get("pipeline_version") or ""
    ).strip() or None
    received_at = row.get("received_at") or row.get("fetched_at") or row.get("published_at") or _now()
    latency = {
        "ingested_at": row.get("ingested_at") or received_at,
        "candidate_at": row.get("candidate_at") or _now(),
        "writer_wait_ms": _nonnegative_number(row.get("writer_wait_ms")),
        "release_ready_at": row.get("release_ready_at"),
        "telegram_attempted_at": row.get("telegram_attempted_at"),
        "delivery_result": row.get("delivery_result"),
        "delay_reason": str(row.get("delay_reason") or "none"),
    }
    pending = list(dict.fromkeys(str(item) for item in (result.get("pending_reasons") or []) if str(item).strip()))
    canonical_risk = str(risk.get("prstk_risk_level") or "R2").upper()
    if canonical_risk not in {"R0", "R1", "R2", "R3", "R4"}:
        canonical_risk = "R2"
    return {
        "kind": "external_event",
        "source": "FinancialJuice",
        "source_key": "financialjuice",
        "source_tier": "discovery",
        "title": headline,
        "brief_title": f"FJ 快訊｜重要度 {importance}/10｜{semantic['event']}" if importance is not None else f"FJ 快訊｜待核對｜{semantic['event']}",
        # Canonical semantic fields are the stable consumer contract.  The
        # legacy summary fields remain populated for older renderers.
        **semantic,
        "brief_summary": semantic["event"],
        "summary": semantic["possible_linkage"],
        "event_type": str(row.get("event_type") or row.get("category") or "unknown"),
        "classification": str(cluster.get("event_type") or row.get("event_type") or "unknown"),
        "event_cluster_key": cluster_key,
        "observation_id": observation_id,
        "observation_id_hash": observation_hash,
        "item_id": item_id,
        "received_at": received_at,
        **latency,
        "latency": latency,
        "parser_version": parser_version,
        "notification_id": result.get("notification_id") or row.get("item_id") or observation_id,
        "lifecycle_state": result.get("lifecycle_state") or "pending_confirmation",
        "risk_level": canonical_risk,
        "prstk_risk_level": canonical_risk,
        "prstk_risk": risk,
        "vendor_importance": importance,
        "vendor_priority_notification": vendor_priority_notification,
        "notification_status": status,
        "notification_reasons": list(dict.fromkeys([*reasons, *pending])),
        "notification_reason": "、".join(dict.fromkeys([*reasons, *pending])),
        "source_url": source_url,
        "published_at": _first_value(views, "published_at", "source_published_at"),
        "fetched_at": _first_value(views, "fetched_at") or _now(),
        "source_trace": {
            "source_label": "FinancialJuice",
            "source_url": source_url,
            "source_domain": str(row.get("source_domain") or "financialjuice.com"),
            "vendor_importance": importance,
            "vendor_importance_is_not_risk": True,
            "official_confirmed": bool(risk.get("official_confirmed")),
            "market_sync_confirmed": market["market_sync_confirmed"],
            "observation_id": observation_id,
            "observation_id_hash": observation_hash,
            "item_id": item_id,
            "event_cluster_key": cluster_key,
            "received_at": received_at,
            "parser_version": parser_version,
        },
        "source_evidence": result.get("source_evidence") or [],
        "market_evidence": market["market_evidence"],
        "linked_markets": market["linked_markets"],
        "linkage_state": market["linkage_state"],
        "market_sync_confirmed": market["market_sync_confirmed"],
        "market_direction": None,
        "market_move": None,
        "alert_eligible": status == "eligible" and vendor_priority_notification,
        "public_signal_eligible": public_signal_eligible,
        "content_gate": {
            "material_event_present": material_event_present,
            "blocked_reason": next(
                (reason for reason in reasons if reason in {"content_incomplete", "missing_material_event", "source_identity_unverified"}),
                None,
            ),
        },
        "public_safe": True,
    }


def project_financialjuice_priority(
    observations: list[dict[str, Any]],
    *,
    existing_events: list[dict[str, Any]] | None = None,
    market_snapshot: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Return public event rows and auditable vendor-priority decisions.

    Items below 8/10 remain visible as ``not_eligible``.  Qualifying items
    sharing a cluster with an already delivered event become
    ``already_cluster_notified`` rather than creating a duplicate alert.
    """
    existing_keys = {
        str(item.get("event_cluster_key") or "").strip()
        for item in (existing_events or [])
        if isinstance(item, dict) and item.get("event_cluster_key")
    }
    events: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    for row in observations:
        if not isinstance(row, dict) or _source(row) != "financialjuice":
            continue
        for result in build_external_events(row):
            vendor = _mapping(result.get("vendor_priority"))
            qualifying = bool(vendor.get("vendor_priority_notification"))
            # A reviewed provider item may carry a canonical cluster assigned
            # by the upstream ledger.  Preserve it over the locally derived
            # fallback so cross-provider deduplication remains stable.
            cluster_key = str(row.get("event_cluster_key") or result.get("event_cluster_key") or "").strip()
            if cluster_key:
                result["event_cluster_key"] = cluster_key
            material_event = bool(_material_event_text(_source_views(result, row)))
            identity_verified = row.get("source_identity_verified") is not False
            if not qualifying:
                status, reasons = "not_eligible", ["vendor_importance_below_8_or_missing"]
                vendor_notification = False
            elif not identity_verified:
                status, reasons = "content_incomplete", ["content_incomplete", "source_identity_unverified"]
                vendor_notification = False
            elif not material_event:
                # Importance alone is not a public event.  Keep a complete
                # decision/event row for audit and lineage, but block both
                # release publication and Telegram eligibility.
                status, reasons = "content_incomplete", ["content_incomplete", "missing_material_event"]
                vendor_notification = False
            elif cluster_key and cluster_key in existing_keys:
                status, reasons = "already_cluster_notified", ["already_cluster_notified"]
                vendor_notification = True
            else:
                status, reasons = "eligible", ["vendor_priority_importance_ge_8"]
                vendor_notification = True
            event = _event_record(
                result, row, status=status, reasons=reasons,
                vendor_priority_notification=vendor_notification,
                market_snapshot=market_snapshot,
                material_event_present=material_event,
                public_signal_eligible=identity_verified and material_event,
            )
            events.append(event)
            decisions.append({
                "observation_id": event["observation_id"],
                "item_id": row.get("item_id"),
                "event_cluster_key": cluster_key or None,
                "vendor_importance": event.get("vendor_importance"),
                "vendor_priority_notification": vendor_notification,
                "notification_status": status,
                "notification_reason": event["notification_reason"],
                "content_gate": event["content_gate"],
                "public_signal_eligible": event["public_signal_eligible"],
                "linked_markets": event["linked_markets"],
                "market_sync_confirmed": event["market_sync_confirmed"],
                "prstk_risk": event.get("prstk_risk"),
                "release_trace_required": True,
            })
    return {"events": events, "decisions": decisions}


def bind_financialjuice_semantic_views(
    observations: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach canonical semantics to public observation rows.

    The reviewed row remains the lineage record, while public consumers
    receive the same semantic fields used by Telegram.  This prevents legacy
    vendor fields containing section labels from leaking into the Mini App
    without creating a second event or delivery path.
    """
    by_key: dict[str, dict[str, Any]] = {}
    for event in events:
        if not isinstance(event, dict):
            continue
        for key in ("item_id", "observation_id", "notification_id"):
            value = str(event.get(key) or "").strip()
            if value:
                by_key[value] = event
    bound: list[dict[str, Any]] = []
    for row in observations:
        if not isinstance(row, dict) or _source(row) != "financialjuice":
            bound.append(dict(row) if isinstance(row, dict) else row)
            continue
        matched_event: dict[str, Any] | None = None
        for key in ("item_id", "observation_id", "notification_id"):
            value = str(row.get(key) or "").strip()
            if value and value in by_key:
                matched_event = by_key[value]
                break
        view = dict(row)
        if matched_event:
            for key in ("event", "why_important", "possible_linkage", "stock_observation"):
                semantic_value = matched_event.get(key)
                if isinstance(semantic_value, str) and semantic_value.strip():
                    view[key] = semantic_value
            event_text = matched_event.get("event")
            if isinstance(event_text, str) and event_text.strip():
                # Keep legacy names usable for older Mini App bundles, but
                # expose only the cleaned semantic section.
                view["title"] = matched_event.get("brief_title") or matched_event.get("title") or event_text
                view["headline"] = event_text
                view["chinese_translation"] = event_text
                view["vendor_translation"] = event_text
            why = matched_event.get("why_important")
            linkage = matched_event.get("possible_linkage")
            watch = matched_event.get("stock_observation")
            if isinstance(why, str) and why.strip():
                view["ai_commentary"] = why
                view["vendor_analysis"] = why
            if isinstance(linkage, str) and linkage.strip():
                view["possible_impact"] = linkage
                view["vendor_possible_impact"] = linkage
            if isinstance(watch, str) and watch.strip():
                view["stock_observation"] = watch
                view["watch"] = watch
            view["public_signal_eligible"] = matched_event.get("public_signal_eligible") is True
            view["content_gate"] = matched_event.get("content_gate") or {}
            view["linked_markets"] = matched_event.get("linked_markets") or []
            view["market_evidence"] = matched_event.get("market_evidence") or []
            view["market_sync_confirmed"] = matched_event.get("market_sync_confirmed") is True
        bound.append(view)
    return bound


def public_financialjuice_observations(
    observations: list[dict[str, Any]], events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return public observation rows while retaining blocked rows in audit data."""
    bound = bind_financialjuice_semantic_views(observations, events)
    return [
        row for row in bound
        if _source(row) != "financialjuice" or row.get("public_signal_eligible") is True
    ]


def replace_financialjuice_event_lane(
    existing_events: list[dict[str, Any]], projected_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Replace stale FJ event rows with the current public projection.

    build_market_snapshot may carry event rows from a prior release. FJ rows
    are re-derived from the reviewed observation ingress on every
    monitor/scheduled pass, so retaining old rows would let blocked or
    source-unverified events leak back into the public events.items lane.
    Non-FJ event producers remain untouched; only projected rows explicitly
    marked public-eligible are appended.
    """
    retained: list[dict[str, Any]] = []
    for item in existing_events:
        if not isinstance(item, dict):
            continue
        source_values = (
            item.get("source"), item.get("source_key"), item.get("content_origin"),
        )
        if any(str(value or "").strip().casefold() == "financialjuice" for value in source_values):
            continue
        retained.append(item)
    existing_ids = {
        str(item.get("observation_id") or item.get("item_id") or "")
        for item in retained
        if isinstance(item, dict)
    }
    for item in projected_events:
        if not isinstance(item, dict) or item.get("public_signal_eligible") is not True:
            continue
        key = str(item.get("observation_id") or item.get("item_id") or "")
        if key and key in existing_ids:
            continue
        retained.append(item)
        if key:
            existing_ids.add(key)
    return retained


__all__ = [
    "bind_financialjuice_semantic_views", "project_financialjuice_priority",
    "public_financialjuice_observations", "replace_financialjuice_event_lane",
]
