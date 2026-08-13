"""Deterministic adapters for known creator newsletter templates.

The adapters intentionally parse only labelled fields.  They never infer a
fact, opinion, ticker, or market from free-form prose.  Unsupported templates
are returned as an explicit DLQ-safe state so callers can retain the message
for review without publishing guessed content.
"""

from __future__ import annotations

import hashlib
from typing import Any

from src.email_intelligence import normalize_creator_insight

_MAX_FIELD_CHARS = 600

_LABELS: dict[str, dict[str, tuple[str, ...]]] = {
    "haojiao": {
        "title": ("title", "episode", "節目", "標題", "皓角"),
        "fact": ("fact", "facts", "事實", "事實資料"),
        "opinion": ("opinion", "view", "觀點", "市場觀點", "評論", "看法"),
        "takeaway": ("takeaway", "key takeaway", "重點", "摘要", "結論"),
        "risk": ("risk", "risk view", "風險", "風險觀點"),
    },
    "gooaye": {
        "title": ("title", "episode", "集數", "標題", "股癌"),
        "fact": ("fact", "facts", "事實", "事實資料"),
        "opinion": ("opinion", "view", "觀點", "市場觀點", "評論", "看法"),
        "takeaway": ("takeaway", "key takeaway", "重點", "摘要", "結論"),
        "risk": ("risk", "risk view", "風險", "風險觀點"),
    },
}


def _clip(value: str, limit: int = _MAX_FIELD_CHARS) -> str:
    return " ".join(value.split())[:limit].strip()


def _line_value(line: str, labels: tuple[str, ...]) -> str:
    normalized = line.strip()
    lowered = normalized.casefold()
    for label in labels:
        marker = label.casefold()
        if not lowered.startswith(marker):
            continue
        remainder = normalized[len(label):].lstrip(" :：|-\t")
        return _clip(remainder)
    return ""


def _section(lines: list[str], labels: tuple[str, ...], *, limit_lines: int = 3) -> str:
    for index, line in enumerate(lines):
        inline = _line_value(line, labels)
        if inline:
            return inline
        if any(line.casefold().startswith(label.casefold()) for label in labels):
            return _clip(" ".join(lines[index + 1:index + 1 + limit_lines]))
    return ""


def _fingerprint(source: str, subject: str, body: str) -> str:
    material = "|".join((source.casefold(), _clip(subject, 240).casefold(), body[:2000].casefold()))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]


def parse_creator_template(
    *,
    source: str,
    sender: str,
    subject: str,
    body: str,
    message_id: str = "",
) -> dict[str, Any]:
    """Parse one known template, returning a public-safe derived record.

    A template is accepted only when it has a labelled title and at least one
    labelled fact/opinion/takeaway.  This prevents a sender name alone from
    turning an arbitrary email into creator intelligence.
    """
    if source not in _LABELS:
        return {
            "parse_status": "invalid_source",
            "failure_reason": "source_not_creator",
            "message_id": message_id,
            "source_adapter": "creator-template-v2",
        }
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    labels = _LABELS[source]
    title = _section(lines, labels["title"], limit_lines=1) or _clip(subject, 240)
    facts = _section(lines, labels["fact"])
    opinions = _section(lines, labels["opinion"])
    takeaways = _section(lines, labels["takeaway"])
    risk = _section(lines, labels["risk"])
    if not title:
        return {
            "parse_status": "unsupported_template",
            "failure_reason": "missing_episode_title",
            "message_id": message_id,
            "source_adapter": "creator-template-v2",
            "template_fingerprint": _fingerprint(source, subject, body),
        }
    if not any((facts, opinions, takeaways, risk)):
        return {
            "parse_status": "unsupported_template",
            "failure_reason": "missing_fact_or_opinion_sections",
            "message_id": message_id,
            "source_adapter": "creator-template-v2",
            "template_fingerprint": _fingerprint(source, subject, body),
        }
    insight = normalize_creator_insight({
        "creator_id": source,
        "creator_name": source,
        "episode_key": f"{source}:{message_id or title.casefold()}",
        "episode_id": message_id,
        "episode_title": title,
        "source_message_id": message_id,
        "content_origin": source,
        "key_takeaways": [value for value in (takeaways, risk) if value],
        "claims": [facts] if facts else [],
        "opinions": [value for value in (opinions, risk) if value],
        "verification_state": "unverified",
        "evidence_alignment": "not_verifiable",
        "parse_status": "parsed",
        "parser_version": "creator-template-v2",
    })
    insight.update({
        "parse_status": "parsed",
        "parser_version": "creator-template-v2",
        "source_adapter": "creator-template-v2",
        "template_fingerprint": _fingerprint(source, subject, body),
        "required_fields_present": True,
        "public_safe": True,
    })
    return insight


__all__ = ["parse_creator_template"]
