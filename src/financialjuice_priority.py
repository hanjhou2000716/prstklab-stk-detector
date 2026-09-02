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
    event = _first_clean_text(
        views, "translation", "chinese_translation", "vendor_translation",
    ) or _first_clean_text(
        views, "headline", "translated_headline", "original_headline",
        "vendor_original_headline", "headline", "title", "event", "summary",
    )
    why_important = _first_clean_text(
        views, "analysis", "ai_commentary", "vendor_analysis", "why_important", "importance_detail",
    ) or _embedded_clean_text(
        views, _ANALYSIS_LABELS,
        stop=(*_IMPACT_LABELS, *_ORIGINAL_LABELS, "source url", "來源連結"),
    ) or _NEUTRAL_IMPORTANCE
    possible_linkage = _first_clean_text(
        views, "impact", "possible_impact", "vendor_possible_impact", "vendor_impact", "possible_linkage",
        "market_impact", "impact",
    ) or _NEUTRAL_LINKAGE
    stock_observation = _first_text(
        views, "stock_observation", "watch", "stock_watch", "follow_up_observation",
    ) or _NEUTRAL_STOCK_OBSERVATION
    return {
        "event": event or "FinancialJuice 公開快訊",
        "why_important": why_important,
        "possible_linkage": possible_linkage,
        "stock_observation": stock_observation,
    }


def _event_record(result: dict[str, Any], row: dict[str, Any], *, status: str, reasons: list[str]) -> dict[str, Any]:
    risk = _mapping(result.get("risk"))
    cluster = _mapping(result.get("cluster"))
    views = _source_views(result, row)
    semantic = _semantic_projection(result, row)
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
        "brief_title": f"FinancialJuice｜{headline}｜{'重要度 ' + str(importance) + '/10' if importance is not None else '待核對'}",
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
        "parser_version": parser_version,
        "notification_id": result.get("notification_id") or row.get("item_id") or observation_id,
        "lifecycle_state": result.get("lifecycle_state") or "pending_confirmation",
        "risk_level": canonical_risk,
        "prstk_risk_level": canonical_risk,
        "prstk_risk": risk,
        "vendor_importance": importance,
        "vendor_priority_notification": bool(
            isinstance(result.get("vendor_priority"), dict)
            and result["vendor_priority"].get("vendor_priority_notification")
        ),
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
            "market_sync_confirmed": bool(risk.get("market_sync_confirmed")),
            "observation_id": observation_id,
            "observation_id_hash": observation_hash,
            "item_id": item_id,
            "event_cluster_key": cluster_key,
            "received_at": received_at,
            "parser_version": parser_version,
        },
        "source_evidence": result.get("source_evidence") or [],
        "market_evidence": result.get("market_evidence") or [],
        "market_direction": None,
        "market_move": None,
        "alert_eligible": status == "eligible",
        "public_safe": True,
    }


def project_financialjuice_priority(
    observations: list[dict[str, Any]],
    *,
    existing_events: list[dict[str, Any]] | None = None,
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
            if not qualifying:
                status, reasons = "not_eligible", ["vendor_importance_below_8_or_missing"]
            elif cluster_key and cluster_key in existing_keys:
                status, reasons = "already_cluster_notified", ["already_cluster_notified"]
            else:
                status, reasons = "eligible", ["vendor_priority_importance_ge_8"]
            event = _event_record(result, row, status=status, reasons=reasons)
            events.append(event)
            decisions.append({
                "observation_id": event["observation_id"],
                "item_id": row.get("item_id"),
                "event_cluster_key": cluster_key or None,
                "vendor_importance": event.get("vendor_importance"),
                "vendor_priority_notification": qualifying,
                "notification_status": status,
                "notification_reason": event["notification_reason"],
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
        event = None
        for key in ("item_id", "observation_id", "notification_id"):
            value = str(row.get(key) or "").strip()
            if value and value in by_key:
                event = by_key[value]
                break
        view = dict(row)
        if event:
            for key in ("event", "why_important", "possible_linkage", "stock_observation"):
                value = event.get(key)
                if isinstance(value, str) and value.strip():
                    view[key] = value
            event_text = event.get("event")
            if isinstance(event_text, str) and event_text.strip():
                # Keep legacy names usable for older Mini App bundles, but
                # expose only the cleaned semantic section.
                view["title"] = event.get("title") or event_text
                view["headline"] = event_text
                view["chinese_translation"] = event_text
                view["vendor_translation"] = event_text
            why = event.get("why_important")
            linkage = event.get("possible_linkage")
            watch = event.get("stock_observation")
            if isinstance(why, str) and why.strip():
                view["ai_commentary"] = why
                view["vendor_analysis"] = why
            if isinstance(linkage, str) and linkage.strip():
                view["possible_impact"] = linkage
                view["vendor_possible_impact"] = linkage
            if isinstance(watch, str) and watch.strip():
                view["stock_observation"] = watch
                view["watch"] = watch
        bound.append(view)
    return bound


__all__ = ["bind_financialjuice_semantic_views", "project_financialjuice_priority"]
