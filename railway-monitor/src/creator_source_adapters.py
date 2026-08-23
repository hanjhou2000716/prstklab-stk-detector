# GENERATED FILE: do not edit manually.
# Run scripts/sync_railway_canonical_parser.py to refresh it.
# Canonical source: src/creator_source_adapters.py
# Canonical source SHA256: 2d5d334d4b43610775ed82ba0f588d1e57eb24075c751ff63e6cfa548bc00210

"""Deterministic adapters for known creator newsletter templates.

Provider identity is owned by :mod:`src.creator_provider_registry`.  This
module owns only the shared, public-safe section vocabulary, so adding a
provider to the registry does not require maintaining a second whitelist.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from bs4 import BeautifulSoup

from src.creator_provider_registry import creator_ids, get_creator_provider, is_known_creator
from src.email_intelligence import normalize_creator_insight

_MAX_FIELD_CHARS = 600
_SUPPORTED_PARSER = "creator-template-v2"
_JENNY_PARSER = "jenny-template-v2"
_JENNY_FIELDS = ("CSCO", "NBIS", "COHR", "CBRS")

# These labels describe the shared template contract, not provider identity.
# Keep aliases conservative: unlabelled prose must remain unsupported.
_BASE_LABELS: dict[str, tuple[str, ...]] = {
    "title": ("title", "episode", "主題", "標題", "集數"),
    "fact": ("fact", "facts", "事實", "資料", "發生什麼事"),
    "opinion": ("opinion", "view", "觀點", "看法", "分析"),
    "takeaway": ("takeaway", "key takeaway", "重點", "結論", "摘要"),
    "risk": ("risk", "risk view", "風險", "風險觀察"),
}

_JENNY_STRUCTURED_LABELS: dict[str, tuple[str, ...]] = {
    "topics": ("topics", "topic", "主題", "主題標籤"),
    "markets": ("markets", "market", "市場", "市場範圍"),
    "sectors": ("sectors", "sector", "產業", "產業別"),
    "tickers": ("tickers", "ticker", "標的", "股票代號", "代號"),
    "key_numbers": ("key numbers", "numbers", "關鍵數字", "重要數字"),
    "market_view": ("market view", "市場觀點", "大盤觀點"),
    "strategy_view": ("strategy view", "策略觀點", "策略重點"),
    "risk_view": ("risk view", "風險觀點", "風險提醒"),
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


def _plain_text(value: str) -> str:
    """Convert sanitized Jenny HTML to deterministic text without retaining markup."""
    raw = str(value or "")
    if not re.search(r"<\s*(?:html|body|div|p|section|h[1-6]|br)\b", raw, re.IGNORECASE):
        return raw.replace("\r\n", "\n").replace("\r", "\n")
    soup = BeautifulSoup(raw, "html.parser")
    for node in soup.find_all(("script", "style", "noscript")):
        node.decompose()
    return soup.get_text("\n", strip=True).replace("\r\n", "\n").replace("\r", "\n")


def _jenny_fields(body: str) -> dict[str, str]:
    """Extract the fixed Jenny ticker fields when the email contains them."""
    result: dict[str, str] = {}
    for line in body.splitlines():
        normalized = " ".join(line.split())
        for ticker in _JENNY_FIELDS:
            match = re.match(rf"^{ticker}\s*[:：-]\s*(.+)$", normalized, re.IGNORECASE)
            if match:
                result[ticker] = _clip(match.group(1), 240)
    return result


def _labeled_list(lines: list[str], labels: tuple[str, ...]) -> list[str]:
    """Read explicitly labelled comma/space separated values only.

    We intentionally do not infer a market or ticker from arbitrary prose:
    creator commentary is evidence, not an automated trading signal.
    """
    value = _section(lines, labels, limit_lines=1)
    if not value:
        return []
    parts = re.split(r"[,，、;；|/\s]+", value)
    return list(dict.fromkeys(item.strip() for item in parts if item.strip()))[:20]


def _key_numbers(lines: list[str]) -> list[dict[str, str]]:
    value = _section(lines, _JENNY_STRUCTURED_LABELS["key_numbers"], limit_lines=2)
    if not value:
        return []
    numbers: list[dict[str, str]] = []
    for token in re.split(r"[,，、;；|]+", value):
        token = _clip(token, 120)
        match = re.match(r"(?P<label>[^:=：]+)\s*[:=：]\s*(?P<value>.+)", token)
        if match:
            numbers.append({"label": _clip(match.group("label"), 48), "value": _clip(match.group("value"), 64)})
    return numbers[:20]


def _explicit_tickers(text: str, provider_fields: dict[str, str]) -> list[str]:
    # Only known Jenny fields and conventional uppercase symbols are accepted.
    # This prevents ordinary English words from becoming fake tickers.
    values = list(provider_fields)
    values.extend(re.findall(r"(?<![A-Za-z0-9])\$?([A-Z]{2,5})(?![A-Za-z0-9])", text))
    ignored = {"AI", "HTML", "HTTP", "USD", "EPS", "THE", "AND", "FOR", "WITH"}
    return list(dict.fromkeys(value.upper() for value in values if value.upper() not in ignored))[:20]


def _parse_jenny_template(
    *, sender: str, subject: str, body: str, message_id: str, provider_config: Any,
    media_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Parse Jenny's structured/sanitized template with fail-closed semantics.

    The body may be HTML or plain text, but only labelled sections are accepted.
    The ticker fields are optional because individual editions can omit a name;
    when present they are preserved as evidence fields rather than converted into
    an investment signal.
    """
    text = _plain_text(body)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    labels = _LABELS["jenny"]
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
            "source_adapter": _JENNY_PARSER,
            "template_fingerprint": _fingerprint("jenny", subject, text),
        }
    if not any((facts, opinions, takeaways, risk)):
        return {
            "parse_status": "unsupported_template",
            "failure_reason": "missing_fact_or_opinion_sections",
            "message_id": message_id,
            "source_adapter": _JENNY_PARSER,
            "template_fingerprint": _fingerprint("jenny", subject, text),
        }
    provider_fields = _jenny_fields(text)
    tickers = _explicit_tickers(text, provider_fields)
    media = media_summary if isinstance(media_summary, dict) and media_summary.get("public_safe") else {}
    insight = normalize_creator_insight({
        "creator_id": "jenny",
        "creator_name": provider_config.display_name,
        "episode_key": f"jenny:{message_id or title.casefold()}",
        "episode_id": message_id,
        "episode_title": title,
        "source_message_id": message_id,
        "content_origin": "jenny",
        "topics": _labeled_list(lines, _JENNY_STRUCTURED_LABELS["topics"]),
        "markets": _labeled_list(lines, _JENNY_STRUCTURED_LABELS["markets"]),
        "sectors": _labeled_list(lines, _JENNY_STRUCTURED_LABELS["sectors"]),
        "tickers": tickers,
        "key_takeaways": [value for value in (takeaways, risk) if value],
        "creator_market_view": _section(lines, _JENNY_STRUCTURED_LABELS["market_view"], limit_lines=2),
        "creator_strategy_view": _section(lines, _JENNY_STRUCTURED_LABELS["strategy_view"], limit_lines=2),
        "creator_risk_view": _section(lines, _JENNY_STRUCTURED_LABELS["risk_view"], limit_lines=2) or risk,
        "key_numbers": _key_numbers(lines),
        "claims": [facts] if facts else [],
        "opinions": [value for value in (opinions, risk) if value],
        "verification_state": "unverified",
        "evidence_alignment": "not_verifiable",
        "parse_status": "parsed",
        "parser_version": _JENNY_PARSER,
        "summary_image_available": media.get("availability") == "private_ready",
        "summary_image_hash": media.get("sha256", ""),
    })
    insight.update({
        "parse_status": "parsed",
        "parser_version": _JENNY_PARSER,
        "source_adapter": _JENNY_PARSER,
        "template_fingerprint": _fingerprint("jenny", subject, text),
        "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "provider_fields": provider_fields,
        "provider_fields_missing": [ticker for ticker in _JENNY_FIELDS if ticker not in provider_fields],
        "required_fields_present": True,
        "public_safe": True,
    })
    return insight


def parse_creator_template(
    *,
    source: str,
    sender: str,
    subject: str,
    body: str,
    message_id: str = "",
    media_summary: dict[str, Any] | None = None,
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
    if normalized_source == "jenny":
        return _parse_jenny_template(
            sender=sender,
            subject=subject,
            body=body,
            message_id=message_id,
            provider_config=provider_config,
            media_summary=media_summary,
        )
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
