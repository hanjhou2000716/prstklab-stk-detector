"""Deterministic Gmail source routing and DLQ-safe parser dispatch."""

from __future__ import annotations

import hashlib
import re
from typing import Any
from src.creator_provider_registry import creator_ids, get_creator_provider

KNOWN_SOURCES = {"financialjuice", *creator_ids()}
DLQ_STATES = {"parse_failed", "unsupported_template", "invalid_source", "duplicate"}
PARSER_VERSION = "railway-email-router-v1"


def _text(value: Any) -> str:
    return str(value or "").strip()


def template_fingerprint(subject: str, body: str, attachments: list[dict[str, Any]] | None = None) -> str:
    """Hash structure only; do not persist the raw body."""
    markers = "|".join(re.findall(r"[A-Za-z][A-Za-z _-]{2,32}", f"{subject}\n{body}")[:32])
    mime = "|".join(_text(item.get("mime_type")) for item in (attachments or []) if isinstance(item, dict))
    return hashlib.sha256(f"{markers}|{mime}".casefold().encode("utf-8")).hexdigest()


def route_source(*, sender: str, subject: str, body: str, attachments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    haystack = " ".join((_text(sender), _text(subject), _text(body))).casefold()
    registry_signals = {
        provider: get_creator_provider(provider).markers
        for provider in creator_ids()
        if get_creator_provider(provider)
    }
    for provider, markers in registry_signals.items():
        if any(marker in haystack for marker in markers):
            return {
                "source": provider,
                "content_type": "creator_analysis",
                "parse_status": "identified" if any(marker in haystack for marker in ("episode", "market view", "takeaway", "creator")) else "unsupported_template",
                "failure_reason": None if any(marker in haystack for marker in ("episode", "market view", "takeaway", "creator")) else "known_source_template_not_matched",
                "template_fingerprint": template_fingerprint(subject, body, attachments),
            }
    signals = {
        "financialjuice": ("financialjuice", "financial juice", "breaking news"),
        "haojiao": ("haojiao", "財經皓角", "皓角"),
        "gooaye": ("gooaye", "股癌", "goo aye"),
    }
    candidates = [source for source, markers in signals.items() if any(marker.casefold() in haystack for marker in markers)]
    source = candidates[0] if candidates else "unknown"
    expected = {
        "financialjuice": ("original headline", "importance", "possible impact", "ai commentary"),
        "haojiao": ("episode", "market view", "takeaway", "creator"),
        "gooaye": ("episode", "market view", "takeaway", "creator"),
    }
    if source == "unknown":
        status, reason = "invalid_source", "source_not_recognized"
    elif not any(marker.casefold() in haystack for marker in expected[source]):
        status, reason = "unsupported_template", "known_source_template_not_matched"
    else:
        status, reason = "identified", None
    return {
        "source": source,
        "content_type": "breaking_news" if source == "financialjuice" else "creator_analysis" if source in KNOWN_SOURCES else "unknown",
        "parse_status": status,
        "failure_reason": reason,
        "template_fingerprint": template_fingerprint(subject, body, attachments),
    }


def parse_email(record: dict[str, Any]) -> dict[str, Any]:
    """Return sanitized parser metadata; raw body is never copied to output."""
    sender, subject, body = _text(record.get("sender")), _text(record.get("subject")), _text(record.get("body"))
    attachments = record.get("attachments") if isinstance(record.get("attachments"), list) else []
    route = route_source(sender=sender, subject=subject, body=body, attachments=attachments)
    message_id = _text(record.get("gmail_message_id") or record.get("message_id"))
    status = route["parse_status"]
    result: dict[str, Any] = {
        "gmail_message_id": message_id,
        "content_origin": route["source"],
        "content_type": route["content_type"],
        "parser_name": "email-router",
        "parser_version": PARSER_VERSION,
        "template_fingerprint": route["template_fingerprint"],
        "parse_status": "parsed" if status == "identified" else status,
        "required_fields_present": bool(message_id and subject and body),
        "failure_reason": route["failure_reason"],
        "public_safe": True,
    }
    if status == "identified" and not result["required_fields_present"]:
        result["parse_status"] = "parse_failed"
        result["failure_reason"] = "required_fields_missing"
    return result


__all__ = ["DLQ_STATES", "parse_email", "route_source", "template_fingerprint"]
