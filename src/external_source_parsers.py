"""Deterministic parsers for sanitized external intelligence mail.

Parsers consume body text in memory and return derived fields only.  A missing
marker produces an explicit parse state/DLQ reason rather than a partial event
that could silently enter the alert pipeline.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from src.creator_provider_registry import is_known_creator
from src.creator_source_adapters import parse_creator_template
from src.email_intelligence import normalize_creator_insight, route_email_source
from src.event_classifier import classify_event_fields
from src.financialjuice_contract import FINANCIALJUICE_SOURCE_URL, normalize_financialjuice_item

MAX_FIELD_CHARS = 600
DLQ_STATES = {"parse_failed", "unsupported_template", "invalid_source", "duplicate"}


def _clip(value: str, limit: int = MAX_FIELD_CHARS) -> str:
    return " ".join(value.split())[:limit].strip()


def _plain_text(body: str) -> str:
    """Normalize Gmail HTML relays before applying the text parser.

    FinancialJuice relays are HTML-only in the live Gmail source.  Parsing
    markup directly can make the first ``<!DOCTYPE ...>`` line look like a
    headline and can hide labels whose value is rendered in a sibling tag.
    Keep this conversion in the canonical parser so every ingress (Railway,
    fixture and replay) receives the same deterministic input.  Plain text is
    returned unchanged apart from normalising line endings.
    """
    raw = str(body or "")
    # Some Gmail relays omit ``html``/``body`` and send a table fragment only
    # (for example ``<table><tr><td>...``).  Treat any actual HTML element as
    # markup so labels and values are extracted from rendered text instead of
    # being left interleaved with tags.
    if not re.search(r"<\s*/?\s*[a-z][^>]*>", raw, re.IGNORECASE):
        return raw.replace("\r\n", "\n").replace("\r", "\n")
    soup = BeautifulSoup(raw, "html.parser")
    for node in soup.find_all(("script", "style", "noscript")):
        node.decompose()
    text = soup.get_text("\n", strip=True)
    return text.replace("\r\n", "\n").replace("\r", "\n")


_FJ_SECTION_LABELS = (
    "original headline", "vendor original headline", "headline", "title",
    "original content", "原文內容", "原文",
    "translation", "chinese translation", "繁體中文翻譯", "中文翻譯", "翻譯",
    "ai commentary", "vendor analysis", "analysis", "AI分析", "AI 分析", "ai 評論", "AI 評論", "AI評論", "分析",
    "possible impact", "vendor impact", "impact", "可能影響", "市場影響",
    "source url", "來源連結", "url",
)


def _marker_pattern(labels: tuple[str, ...]) -> re.Pattern[str]:
    choices = sorted({label for label in labels if label}, key=len, reverse=True)
    return re.compile("|".join(re.escape(label) for label in choices), re.IGNORECASE)


def _section(body: str, labels: tuple[str, ...]) -> str:
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    target_pattern = _marker_pattern(labels)
    boundary_pattern = _marker_pattern(_FJ_SECTION_LABELS)
    for index, line in enumerate(lines):
        match = target_pattern.search(line)
        if not match:
            continue
        inline = re.sub(r"^[\s:：\-–—]+", "", line[match.end():])
        # A value can legitimately begin with the same words as its label,
        # e.g. ``可能影響: 可能影響 ...``.  Do not mistake that first token for
        # the next field boundary; only look for a boundary after it.
        next_marker = boundary_pattern.search(inline, 1)
        if next_marker:
            inline = re.sub(
                r"[\s:：\-–—📝💡⚠️📄📌🔎📈📉📊🚨\ufe0f]+$", "", inline[:next_marker.start()]
            )
        if inline:
            return _clip(inline)
        following: list[str] = []
        for candidate in lines[index + 1:index + 4]:
            if boundary_pattern.search(candidate):
                break
            following.append(candidate)
        if following:
            return _clip(" ".join(following))
    return ""


def _first_line(body: str) -> str:
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if re.match(r"^[^\w]{0,8}(?:importance|重要性評分|重要性|重要度)\s*[:：]", line, re.IGNORECASE):
            continue
        if re.match(
            r"^[^\w]{0,8}(?:importance|重要性評分|重要性|重要度|original headline|"
            r"原始標題|headline|translation|繁體中文翻譯|中文翻譯|翻譯|"
            r"ai commentary|ai 評論|分析|possible impact|可能影響|市場影響|impact)"
            r"\s*[:：]?\s*$",
            line,
            re.IGNORECASE,
        ):
            continue
        return _clip(line, 240)
    return ""


def _subject_headline(subject: str) -> str:
    """Use only substantive FJ subjects as a safe headline fallback."""
    candidate = _clip(subject, 240)
    if not candidate:
        return ""
    normalized = re.sub(r"[^a-z0-9]+", " ", candidate.casefold()).strip()
    generic = {
        "financialjuice",
        "financialjuice alert",
        "financialjuice breaking news",
        "financialjuice news",
        "financialjuice notification",
    }
    if normalized in generic or normalized.startswith("financialjuice news "):
        return ""
    return candidate


def _source_domain(source_url: str) -> str:
    return (urlsplit(source_url).hostname or "").lower().removeprefix("www.")


def _importance(body: str) -> int | None:
    match = re.search(
        r"(?:importance|重要性評分|重要性|重要度)\s*[:：]?\s*(?:[^\d\n]{0,8})?"
        r"(10|[0-9])\s*(?:/\s*10)?",
        body,
        re.IGNORECASE,
    )
    return int(match.group(1)) if match else None


_ITEM_MARKER = re.compile(r"(?im)^\s*(?:item|news\s+item|story)\s*#?\s*(\d+)\s*[:.)-]?\s*$")


def _compound_blocks(body: str) -> list[str]:
    """Split only explicit repeated-item sections; never guess from paragraphs."""
    markers = list(_ITEM_MARKER.finditer(body))
    if len(markers) < 2:
        return []
    blocks: list[str] = []
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(body)
        block = body[marker.end():end].strip()
        if block:
            blocks.append(block)
    return blocks


def _item_record(block: str) -> dict[str, Any]:
    def strict(labels: tuple[str, ...]) -> str:
        for raw in block.splitlines():
            line = raw.strip()
            for label in labels:
                match = re.match(rf"{re.escape(label)}\s*:\s*(.+)$", line, re.IGNORECASE)
                if match:
                    return _clip(match.group(1))
        return ""

    headline = strict(("original headline", "vendor original headline", "headline", "title"))
    translation = strict(("translation", "chinese translation"))
    analysis = strict(("ai commentary", "vendor analysis", "analysis"))
    impact = strict(("possible impact", "vendor impact", "impact"))
    published = strict(("published at", "published"))
    source_url = strict(("source url", "url"))
    tags = strict(("vendor tags", "tags"))
    entities = [part.strip() for part in re.split(r"[,，;；]", strict(("entities",))) if part.strip()]
    facts = {
        "headline": headline,
        "translation": translation,
        "analysis": analysis,
        "impact": impact,
        "tags": tags,
        "entities": entities,
    }
    classification = classify_event_fields(facts)
    event_type = str(classification.get("category") or "unknown")
    return {
        "original_headline": headline,
        "chinese_translation": translation,
        "ai_commentary": analysis,
        "possible_impact": impact,
        "importance": _importance(block),
        "published_at": published,
        "source_url": source_url,
        "vendor_tags": [part.strip() for part in re.split(r"[,，;；]", tags) if part.strip()],
        "entities": entities,
        "candidate_event_type": event_type,
        "classification": classification,
    }


def _compound_cluster_key(item: dict[str, Any], normalized: dict[str, Any]) -> str:
    """Keep item clusters independent when a vendor omits structured entities."""
    material = "|".join(
        str(item.get(key) or "") for key in ("candidate_event_type", "original_headline", "chinese_translation")
    ) + "|" + str(normalized.get("content_hash") or "")
    return "fj-cluster-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def parse_financialjuice_compound_email(
    *, sender: str, subject: str, body: str, message_id: str = "",
) -> dict[str, Any]:
    """Parse repeated FinancialJuice items with fail-closed compound semantics."""
    body = _plain_text(body)
    blocks = _compound_blocks(body)
    if not blocks:
        return {"parse_status": "not_compound"}
    records = [_item_record(block) for block in blocks]
    if any(not record["original_headline"] for record in records):
        return {
            "parse_status": "compound_unresolved",
            "failure_reason": "compound_item_missing_headline",
            "parser_version": "financialjuice-compound-v1",
            "message_id": message_id,
            "content_origin": "financialjuice",
            "content_type": "breaking_news",
            "item_count": len(records),
            "items": [],
            "public_safe": True,
        }
    items: list[dict[str, Any]] = []
    seen_clusters: set[str] = set()
    for index, record in enumerate(records):
        normalized = normalize_financialjuice_item(record, message_id=message_id, index=index)
        normalized.update(
            {
                "headline": record["original_headline"],
                "translation": record["chinese_translation"],
                "vendor_tags": record["vendor_tags"],
                "vendor_analysis": record["ai_commentary"],
                "vendor_impact": record["possible_impact"],
                "entities": record["entities"],
                "candidate_event_type": record["candidate_event_type"],
            }
        )
        cluster_key = _compound_cluster_key(record, normalized)
        if cluster_key in seen_clusters:
            cluster_key += "-" + str(index)
        seen_clusters.add(cluster_key)
        normalized["event_cluster_key"] = cluster_key
        items.append(normalized)
    return {
        "parse_status": "parsed",
        "parser_version": "financialjuice-compound-v1",
        "message_id": message_id,
        "content_origin": "financialjuice",
        "content_type": "breaking_news",
        "compound": True,
        "item_count": len(items),
        "items": items,
        "attribution": "FinancialJuice",
        "public_safe": True,
    }


def parse_financialjuice_email(*, sender: str, subject: str, body: str, message_id: str = "") -> dict[str, Any]:
    """Parse a FinancialJuice relay into attributed, non-directional facts."""
    body = _plain_text(body)
    route = route_email_source(sender=sender, subject=subject, body=body)
    if route["source"] != "financialjuice":
        return {"parse_status": "invalid_source", "failure_reason": "source_not_financialjuice", "message_id": message_id}
    compound = parse_financialjuice_compound_email(
        sender=sender, subject=subject, body=body, message_id=message_id,
    )
    if compound.get("parse_status") == "parsed":
        return compound
    if compound.get("parse_status") == "compound_unresolved":
        return compound
    importance = _importance(body)
    headline = _section(
        body,
        ("original headline", "原始標題", "headline", "original content", "原文內容", "原文"),
    )
    translation = _section(body, ("translation", "繁體中文翻譯", "中文翻譯", "翻譯"))
    headline = headline or translation or _subject_headline(subject) or _first_line(body)
    analysis = _section(
        body,
        ("ai commentary", "AI分析", "AI commentary", "AI 評論", "AI評論", "分析"),
    )
    impact = _section(body, ("possible impact", "可能影響", "市場影響", "impact"))
    source_url = _section(body, ("source url", "來源連結", "url")) or FINANCIALJUICE_SOURCE_URL
    if not headline:
        return {"parse_status": "parse_failed", "failure_reason": "missing_headline", "message_id": message_id}
    identity_record = {
        "original_headline": headline,
        "chinese_translation": translation,
        "ai_commentary": analysis,
        "possible_impact": impact,
        "source_url": source_url,
    }
    identity = normalize_financialjuice_item(
        identity_record, message_id=message_id, index=0,
    )
    cluster_key = _compound_cluster_key(
        {
            "candidate_event_type": classify_event_fields(identity_record).get("category") or "unknown",
            "original_headline": headline,
            "chinese_translation": translation,
        },
        identity,
    )
    return {
        "parse_status": "parsed",
        "parser_version": "financialjuice-v1",
        "message_id": message_id,
        "content_origin": "financialjuice",
        "content_type": "breaking_news",
        "vendor_importance": importance,
        "vendor_importance_present": importance is not None,
        "vendor_original_headline": headline,
        "vendor_translation": translation,
        "vendor_analysis": analysis,
        "vendor_possible_impact": impact,
        "source_url": source_url,
        "source_domain": _source_domain(source_url),
        "attribution": "FinancialJuice",
        "item_id": identity["item_id"],
        "content_hash": identity["content_hash"],
        "event_cluster_key": cluster_key,
        "public_safe": True,
    }


def _parse_creator_email_legacy(*, sender: str, subject: str, body: str, source: str, message_id: str = "") -> dict[str, Any]:
    """Compatibility parser for historical sanitized fixtures.

    Real production templates use :func:`parse_creator_template`; this path
    remains only for old records whose labels were normalized before storage.
    """
    route = route_email_source(sender=sender, subject=subject, body=body)
    origin = source or route["source"]
    if not is_known_creator(origin):
        return {"parse_status": "invalid_source", "failure_reason": "source_not_creator", "message_id": message_id}
    title = _section(body, ("title", "標題", "主題")) or _clip(subject, 240)
    if not title:
        return {"parse_status": "parse_failed", "failure_reason": "missing_episode_title", "message_id": message_id}
    takeaways = []
    for labels in (("takeaway", "重點", "摘要"), ("market view", "市場觀點"), ("risk view", "風險觀點")):
        value = _section(body, labels)
        if value:
            takeaways.append(value)
    insight = normalize_creator_insight({
        "creator_id": origin,
        "creator_name": origin,
        # ``normalize_creator_insight`` derives a hashed identity from the
        # transport message ID when no explicit key is supplied.  Never expose
        # the Gmail ID itself in a public-safe fallback record.
        "episode_id": message_id,
        "episode_title": title,
        "source_message_id": message_id,
        "content_origin": origin,
        "key_takeaways": takeaways[:5],
        "claims": [_section(body, ("fact", "事實", "數據"))] if _section(body, ("fact", "事實", "數據")) else [],
        "opinions": [_section(body, ("opinion", "看法", "策略觀點"))] if _section(body, ("opinion", "看法", "策略觀點")) else [],
        "verification_state": "unverified",
        "evidence_alignment": "not_verifiable",
        "parse_status": "parsed",
    })
    insight["parse_status"] = "parsed"
    insight["parser_version"] = f"{origin}-v1"
    insight["source_message_id"] = message_id
    insight["source_adapter"] = "legacy-creator-parser"
    insight["adapter_fallback_reason"] = "historical_template_labels"
    return insight


def parse_creator_email(*, sender: str, subject: str, body: str, source: str | None = None, message_id: str = "") -> dict[str, Any]:
    """Parse a creator template with deterministic adapter and safe fallback."""
    route = route_email_source(sender=sender, subject=subject, body=body)
    origin = source or route["source"]
    if not is_known_creator(origin):
        return {"parse_status": "invalid_source", "failure_reason": "source_not_creator", "message_id": message_id}
    adapted = parse_creator_template(
        source=origin,
        sender=sender,
        subject=subject,
        body=body,
        message_id=message_id,
    )
    if adapted.get("parse_status") == "parsed":
        return adapted
    # Do not guess a new event.  Keep compatibility only for the known legacy
    # sanitized format and expose that fallback in the derived record.
    legacy = _parse_creator_email_legacy(
        sender=sender,
        subject=subject,
        body=body,
        source=origin,
        message_id=message_id,
    )
    if legacy.get("parse_status") == "parsed":
        legacy["adapter_status"] = adapted.get("parse_status")
        legacy["adapter_failure_reason"] = adapted.get("failure_reason")
        return legacy
    return adapted


def parse_external_email(**kwargs: Any) -> dict[str, Any]:
    """Dispatch to a known parser and return explicit DLQ-safe status."""
    route = route_email_source(
        sender=str(kwargs.get("sender") or ""),
        subject=str(kwargs.get("subject") or ""),
        body=str(kwargs.get("body") or ""),
    )
    if route["source"] == "financialjuice":
        return parse_financialjuice_email(**kwargs)
    if is_known_creator(route["source"]):
        return parse_creator_email(**kwargs, source=route["source"])
    return {"parse_status": "invalid_source", "failure_reason": "unknown_template", "message_id": kwargs.get("message_id", "")}


__all__ = [
    "DLQ_STATES",
    "parse_creator_email",
    "parse_external_email",
    "parse_financialjuice_compound_email",
    "parse_financialjuice_email",
]
