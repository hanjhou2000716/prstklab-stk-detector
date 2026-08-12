"""Deterministic parsers for sanitized external intelligence mail.

Parsers consume body text in memory and return derived fields only.  A missing
marker produces an explicit parse state/DLQ reason rather than a partial event
that could silently enter the alert pipeline.
"""

from __future__ import annotations

import re
from typing import Any

from src.creator_source_adapters import parse_creator_template
from src.email_intelligence import normalize_creator_insight, route_email_source

MAX_FIELD_CHARS = 600
DLQ_STATES = {"parse_failed", "unsupported_template", "invalid_source", "duplicate"}


def _clip(value: str, limit: int = MAX_FIELD_CHARS) -> str:
    return " ".join(value.split())[:limit].strip()


def _section(body: str, labels: tuple[str, ...]) -> str:
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if any(label.casefold() in line.casefold() for label in labels):
            if "：" in line:
                inline = line.split("：", 1)[1].strip()
                if inline:
                    return _clip(inline)
            if ":" in line:
                inline = line.split(":", 1)[1].strip()
                if inline:
                    return _clip(inline)
            return _clip(" ".join(lines[index + 1:index + 4]))
    return ""


def _first_line(body: str) -> str:
    return _clip(next((line.strip() for line in body.splitlines() if line.strip()), ""), 240)


def _importance(body: str) -> int | None:
    match = re.search(r"(?:importance|重要性|重要度)\s*[:：]?\s*(10|[0-9])\s*(?:/\s*10)?", body, re.IGNORECASE)
    return int(match.group(1)) if match else None


def parse_financialjuice_email(*, sender: str, subject: str, body: str, message_id: str = "") -> dict[str, Any]:
    """Parse a FinancialJuice relay into attributed, non-directional facts."""
    route = route_email_source(sender=sender, subject=subject, body=body)
    if route["source"] != "financialjuice":
        return {"parse_status": "invalid_source", "failure_reason": "source_not_financialjuice", "message_id": message_id}
    importance = _importance(body)
    headline = _section(body, ("original headline", "原始標題", "headline")) or _first_line(body)
    translation = _section(body, ("translation", "中文翻譯", "翻譯"))
    analysis = _section(body, ("ai commentary", "AI分析", "AI commentary", "分析"))
    impact = _section(body, ("possible impact", "可能影響", "市場影響", "impact"))
    if not headline:
        return {"parse_status": "parse_failed", "failure_reason": "missing_headline", "message_id": message_id}
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
        "attribution": "FinancialJuice",
        "public_safe": True,
    }


def _parse_creator_email_legacy(*, sender: str, subject: str, body: str, source: str, message_id: str = "") -> dict[str, Any]:
    """Compatibility parser for historical sanitized fixtures.

    Real production templates use :func:`parse_creator_template`; this path
    remains only for old records whose labels were normalized before storage.
    """
    route = route_email_source(sender=sender, subject=subject, body=body)
    origin = source or route["source"]
    if origin not in {"haojiao", "gooaye"}:
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
        "episode_key": f"{origin}:{message_id or title.casefold()}",
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
    if origin not in {"haojiao", "gooaye"}:
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
    if route["source"] in {"haojiao", "gooaye"}:
        return parse_creator_email(**kwargs, source=route["source"])
    return {"parse_status": "invalid_source", "failure_reason": "unknown_template", "message_id": kwargs.get("message_id", "")}


__all__ = ["DLQ_STATES", "parse_creator_email", "parse_external_email", "parse_financialjuice_email"]
