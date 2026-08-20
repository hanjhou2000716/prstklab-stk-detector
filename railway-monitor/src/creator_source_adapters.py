# GENERATED FILE: do not edit manually.
# Run scripts/sync_railway_canonical_parser.py to refresh it.
# Canonical source: src/creator_source_adapters.py
# Canonical source SHA256: d5a4527c79c3af2bd24781d1524d83f76d5b4b91af758094c98e961628d83053

"""Deterministic adapters for known creator newsletter templates.

Provider identity is owned by :mod:`src.creator_provider_registry`.  This
module owns only the shared, public-safe section vocabulary, so adding a
provider to the registry does not require maintaining a second whitelist.
"""

from __future__ import annotations

import hashlib
from typing import Any

from src.creator_provider_registry import creator_ids, get_creator_provider, is_known_creator
from src.email_intelligence import normalize_creator_insight

_MAX_FIELD_CHARS = 600
_SUPPORTED_PARSER = "creator-template-v2"

# These labels describe the shared template contract, not provider identity.
# Keep aliases conservative: unlabelled prose must remain unsupported.
_BASE_LABELS: dict[str, tuple[str, ...]] = {
    "title": ("title", "episode", "主題", "標題", "集數"),
    "fact": ("fact", "facts", "事實", "資料", "發生什麼事"),
    "opinion": ("opinion", "view", "觀點", "看法", "分析"),
    "takeaway": ("takeaway", "key takeaway", "重點", "結論", "摘要"),
    "risk": ("risk", "risk view", "風險", "風險觀察"),
}

# The registry is the only provider allowlist.  A provider with the shared
# parser receives the shared vocabulary automatically.
_LABELS: dict[str, dict[str, tuple[str, ...]]] = {
    provider_id: dict(_BASE_LABELS) for provider_id in creator_ids()
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
        remainder = normalized[len(label):].lstrip(" :：-\t")
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
    """Parse one known template and return a public-safe derived record.

    A template is accepted only when it has a labelled title and at least one
    labelled fact/opinion/takeaway/risk.  This prevents a sender name alone
    from turning arbitrary email into creator intelligence.
    """
    normalized_source = str(source or "").strip().casefold()
    if not is_known_creator(normalized_source):
        return {
            "parse_status": "invalid_source",
            "failure_reason": "source_not_creator",
            "message_id": message_id,
            "source_adapter": "creator-template-v2",
        }
    provider_config = get_creator_provider(normalized_source)
    if provider_config is None or provider_config.parser != _SUPPORTED_PARSER:
        return {
            "parse_status": "unsupported_parser",
            "failure_reason": "creator_parser_not_supported",
            "message_id": message_id,
            "source_adapter": _SUPPORTED_PARSER,
            "parser_version": provider_config.parser if provider_config else None,
        }
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    labels = _LABELS.get(normalized_source, _BASE_LABELS)
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
            "template_fingerprint": _fingerprint(normalized_source, subject, body),
        }
    if not any((facts, opinions, takeaways, risk)):
        return {
            "parse_status": "unsupported_template",
            "failure_reason": "missing_fact_or_opinion_sections",
            "message_id": message_id,
            "source_adapter": "creator-template-v2",
            "template_fingerprint": _fingerprint(normalized_source, subject, body),
        }
    insight = normalize_creator_insight({
        "creator_id": normalized_source,
        "creator_name": provider_config.display_name if provider_config else normalized_source,
        "episode_key": f"{normalized_source}:{message_id or title.casefold()}",
        "episode_id": message_id,
        "episode_title": title,
        "source_message_id": message_id,
        "content_origin": normalized_source,
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
        "template_fingerprint": _fingerprint(normalized_source, subject, body),
        "required_fields_present": True,
        "public_safe": True,
    })
    return insight


__all__ = ["parse_creator_template"]
