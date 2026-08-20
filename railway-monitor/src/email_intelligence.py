# GENERATED FILE: do not edit manually.
# Run scripts/sync_railway_canonical_parser.py to refresh it.
# Canonical source: src/email_intelligence.py
# Canonical source SHA256: bc74d6b92ed88f414322ea15f701822cc3bafdbcf03a3e6e0a57326f39f9783e

"""Privacy-preserving email and creator-intelligence contracts.

The ingestion boundary keeps raw mail private and exposes only deterministic
metadata plus derived, attributed facts.  It is deliberately pure so Railway
or a Gmail/PubSub adapter can call it without coupling transport to parsing.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from src.creator_provider_registry import creator_ids, get_creator_provider, is_known_creator

SOURCE_NAMES = ("financialjuice", *creator_ids())
CONTENT_TYPES = {"breaking_news", "creator_analysis", "unknown"}
PARSE_STATES = {
    "received", "identified", "parsed", "normalized", "routed",
    "parse_failed", "unsupported_template", "invalid_source", "duplicate",
}
VERIFICATION_STATES = {"verified", "partially_verified", "unverified", "contradicted", "not_applicable"}


def _utc(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC).isoformat()


def _hash(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _text(value: Any) -> str:
    return str(value or "").strip()


def creator_episode_key(record: dict[str, Any]) -> str:
    """Build a stable public-safe creator episode identity for deduplication."""
    source = _text(record.get("content_origin") or record.get("source")) or "unknown"
    explicit = _text(record.get("episode_key"))
    if explicit:
        return explicit
    material = "|".join((
        source.casefold(),
        _text(record.get("episode_id") or record.get("source_message_id") or record.get("message_id")),
        _text(record.get("episode_title") or record.get("subject")),
        (_utc(record.get("published_at") or record.get("source_published_at")) or "")[:10],
    )).casefold()
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]
    return f"{source.casefold()}:{digest}"


def route_email_source(*, sender: str = "", subject: str = "", body: str = "") -> dict[str, str]:
    """Route by deterministic sender/marker signals; unknown mail is DLQ-safe."""
    haystack = " ".join((_text(sender), _text(subject), _text(body))).casefold()
    # Registry-driven providers are checked first so newly configured creators
    # (including Jenny) do not require another hard-coded whitelist.
    for provider in creator_ids():
        metadata = get_creator_provider(provider)
        if metadata and any(marker in haystack for marker in metadata.markers):
            return {"source": provider, "content_type": "creator_analysis", "parse_status": "identified"}
    # Creator identities are defined only by creator_providers.json above.
    # Keep this fallback limited to FinancialJuice so a second Creator
    # whitelist cannot drift from the canonical registry.
    rules = (
        ("financialjuice", ("financial juice", "financialjuice", "financial-juice"), "breaking_news"),
    )
    for source, markers, content_type in rules:
        if any(marker.casefold() in haystack for marker in markers):
            return {"source": source, "content_type": content_type, "parse_status": "identified"}
    return {"source": "unknown", "content_type": "unknown", "parse_status": "invalid_source"}


def normalize_email_observation(record: dict[str, Any]) -> dict[str, Any]:
    """Create a public-safe EmailObservation without retaining raw body text."""
    routed = route_email_source(
        sender=_text(record.get("sender")),
        subject=_text(record.get("subject")),
        body=_text(record.get("body")),
    )
    source = _text(record.get("source")) or routed["source"]
    if source not in SOURCE_NAMES:
        source = routed["source"]
    status = _text(record.get("parse_status")) or routed["parse_status"]
    if status not in PARSE_STATES:
        status = "parse_failed"
    attachments = record.get("attachments") or []
    attachment_hashes = [value for value in (_hash(item) for item in attachments) if value]
    identity_hash = _hash(record.get("message_id")) or _hash(_text(record.get("subject"))) or hashlib.sha256(b"empty-email").hexdigest()
    observation = {
        "observation_id": _text(record.get("observation_id")) or f"email-{identity_hash[:16]}",
        "gmail_message_id": _text(record.get("message_id")),
        "gmail_thread_id": _text(record.get("thread_id")),
        "gmail_history_id": _text(record.get("history_id")),
        "transport_source": "gmail",
        "content_origin": source,
        "content_type": routed["content_type"] if source == routed["source"] else "unknown",
        "sender": _text(record.get("sender")),
        "subject": _text(record.get("subject")),
        "received_at": _utc(record.get("received_at")),
        "source_published_at": _utc(record.get("source_published_at")),
        "body_hash": _hash(record.get("body")),
        "mime_type": _text(record.get("mime_type")) or "text/plain",
        "attachment_count": len(attachments),
        "attachment_hashes": attachment_hashes,
        "parser_version": _text(record.get("parser_version")) or "email-router-v1",
        "parse_status": status,
        "created_at": _utc(record.get("created_at")) or datetime.now(UTC).isoformat(),
        "updated_at": _utc(record.get("updated_at")) or datetime.now(UTC).isoformat(),
    }
    observation["is_public_safe"] = True
    return observation


def normalize_creator_insight(record: dict[str, Any]) -> dict[str, Any]:
    """Normalize attributed creator analysis while separating facts and opinions."""
    def strings(key: str) -> list[str]:
        value = record.get(key) or []
        return list(dict.fromkeys(_text(item) for item in value if _text(item)))

    source = _text(record.get("content_origin"))
    if not is_known_creator(source):
        source = "unknown"
    verification = _text(record.get("verification_state")) or "unverified"
    if verification not in VERIFICATION_STATES:
        verification = "unverified"
    return {
        "creator_id": _text(record.get("creator_id")),
        "creator_name": _text(record.get("creator_name")),
        "episode_key": creator_episode_key(record),
        "episode_id": _text(record.get("episode_id")),
        "episode_title": _text(record.get("episode_title")),
        "published_at": _utc(record.get("published_at")),
        "source_message_id": _text(record.get("source_message_id")),
        "source_url": _text(record.get("source_url")),
        "content_origin": source,
        "topics": strings("topics"),
        "markets": strings("markets"),
        "sectors": strings("sectors"),
        "tickers": strings("tickers"),
        "key_takeaways": strings("key_takeaways"),
        "creator_market_view": _text(record.get("creator_market_view")),
        "creator_strategy_view": _text(record.get("creator_strategy_view")),
        "creator_risk_view": _text(record.get("creator_risk_view")),
        "consensus_stance": _text(record.get("consensus_stance")) if _text(record.get("consensus_stance")).casefold() in {"risk_on", "risk_off", "neutral"} else "",
        "key_numbers": record.get("key_numbers") if isinstance(record.get("key_numbers"), list) else [],
        "claims": strings("claims"),
        "opinions": strings("opinions"),
        "verification_state": verification,
        "evidence_alignment": _text(record.get("evidence_alignment")) or "not_verifiable",
        "prstk_correlation": record.get("prstk_correlation") if isinstance(record.get("prstk_correlation"), dict) and record.get("prstk_correlation") else {
            "correlation_state": "not_comparable",
            "reason": "market_and_research_snapshots_missing",
            "matched_tickers": [],
            "matched_sectors": [],
            "creator_topics": [],
            "market_snapshot_id": "",
            "research_snapshot_id": "",
            "as_of": _utc(record.get("updated_at")) or datetime.now(UTC).isoformat(),
            "evidence": [],
            "is_investment_signal": False,
        },
        "summary_image_available": bool(record.get("summary_image_available")),
        "summary_image_hash": _text(record.get("summary_image_hash")),
        "parse_status": _text(record.get("parse_status")) or "normalized",
        "parser_version": _text(record.get("parser_version")) or "creator-normalizer-v1",
        "created_at": _utc(record.get("created_at")) or datetime.now(UTC).isoformat(),
        "updated_at": _utc(record.get("updated_at")) or datetime.now(UTC).isoformat(),
        "public_safe": True,
    }


__all__ = ["creator_episode_key", "normalize_creator_insight", "normalize_email_observation", "route_email_source"]
