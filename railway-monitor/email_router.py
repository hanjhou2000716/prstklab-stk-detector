"""Deterministic Gmail source routing and DLQ-safe parser dispatch."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

try:
    from src.creator_provider_registry import creator_ids, get_creator_provider
except ModuleNotFoundError as error:  # pragma: no cover - exercised in the Railway root image
    if error.name not in {"src", "src.creator_provider_registry"}:
        raise
    # Railway's current root directory is ``railway-monitor`` and therefore
    # does not contain the repository-level ``src`` package.  Load the
    # build-time public registry bundle instead of crashing the Gmail ingress.
    # This bundle contains provider metadata only; parsing and policy remain
    # owned by the canonical repository modules when the full checkout exists.
    _bundle_path = Path(__file__).with_name("creator_providers.json")
    try:
        _bundle = json.loads(_bundle_path.read_text(encoding="utf-8"))
        _entries = _bundle.get("providers") if isinstance(_bundle, dict) else None
        if not isinstance(_entries, list) or not _entries:
            raise ValueError("creator provider bundle is empty")
        _providers: dict[str, tuple[str, ...]] = {}
        for _entry in _entries:
            if not isinstance(_entry, dict):
                raise ValueError("creator provider bundle entry is invalid")
            _creator_id = str(_entry.get("creator_id") or "").strip().casefold()
            _rules = _entry.get("email_identity_rules")
            _markers = _rules.get("markers") if isinstance(_rules, dict) else None
            if not _creator_id or not isinstance(_markers, list) or not _markers:
                raise ValueError("creator provider bundle entry is incomplete")
            _providers[_creator_id] = tuple(str(item).strip().casefold() for item in _markers if str(item).strip())
        if len(_providers) != len(_entries):
            raise ValueError("creator provider bundle contains duplicate ids")
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise RuntimeError("creator provider bundle unavailable") from exc

    class _BundledProvider:
        def __init__(self, markers: tuple[str, ...]) -> None:
            self.markers = markers

    def creator_ids(*, enabled_only: bool = False) -> tuple[str, ...]:
        del enabled_only
        return tuple(_providers)

    def get_creator_provider(creator_id: str) -> _BundledProvider | None:
        return _BundledProvider(_providers[creator_id]) if creator_id in _providers else None

try:
    # The Railway service normally runs from the repository root.  Keep the
    # import optional so the standalone monitor image still starts safely when
    # only the railway-monitor package is copied into the image.
    from src.external_source_parsers import parse_external_email
except ModuleNotFoundError:  # pragma: no cover - exercised by standalone image
    parse_external_email = None  # type: ignore[assignment]

KNOWN_SOURCES = {"financialjuice", *creator_ids()}
# A standalone Railway image must never acknowledge a known message after
# silently skipping the canonical parser.  Keep this explicit state in the
# same DLQ contract as template/parse failures so the cursor is not advanced
# and the health projection can report the missing parser dependency.
DLQ_STATES = {
    "parse_failed", "unsupported_template", "invalid_source", "duplicate",
    "parser_unavailable",
}
PARSER_VERSION = "railway-email-router-v1"

_PUBLIC_FIELDS = {
    "content_origin", "content_type", "event_type", "category", "title",
    "headline", "original_headline", "summary", "chinese_translation",
    "vendor_translation", "ai_commentary", "possible_impact",
    "vendor_analysis", "vendor_possible_impact", "vendor_importance",
    "vendor_importance_present", "published_at", "source_published_at",
    "source_url", "source_domain", "source_tier", "official_confirmed",
    "market_sync_confirmed", "cross_source_count", "market_evidence",
    "entities", "topics", "tickers", "candidate_event_type", "item_id",
    "content_hash", "parser_version", "parse_status", "public_safe",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _display_name(value: str) -> str:
    """Return the human sender label without treating a domain as identity."""
    candidate = _text(value).split("<", 1)[0].strip()
    # Gmail may omit the display name and return only ``local@domain``.
    # Treat that as an address, not as a trusted provider label.
    return "" if "@" in candidate else candidate


def _trusted_identity(*, markers: tuple[str, ...], sender: str, subject: str) -> bool:
    """Require a source marker in a human label/subject before fallback parsing.

    A provider domain alone is not enough to bypass the template gate: generic
    mail from ``alerts@financialjuice.com`` with an unrelated subject must
    remain in the DLQ.  Gmail display names and RFC-2047-decoded subjects are
    safe identity signals, while the body is deliberately excluded so an
    article mentioning a provider cannot steal the route.
    """
    identity_text = " ".join((_display_name(sender), _text(subject))).casefold()
    return any(marker.casefold() in identity_text for marker in markers)


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
            trusted_identity = _trusted_identity(
                markers=markers,
                sender=sender,
                subject=subject,
            )
            complete_message = bool(_text(subject) and _text(body))
            return {
                "source": provider,
                "content_type": "creator_analysis",
                "parse_status": "identified" if (
                    complete_message and (
                        trusted_identity
                        or any(marker in haystack for marker in ("episode", "market view", "takeaway", "creator"))
                    )
                ) else "unsupported_template",
                "failure_reason": None if (
                    complete_message and (
                        trusted_identity
                        or any(marker in haystack for marker in ("episode", "market view", "takeaway", "creator"))
                    )
                ) else "known_source_template_not_matched",
                "template_fingerprint": template_fingerprint(subject, body, attachments),
            }
    # Creator identities are owned by the canonical registry above.  The
    # standalone fallback only needs the non-Creator FinancialJuice aliases;
    # retaining another Creator marker table here would drift from config/.
    signals = {"financialjuice": ("financialjuice", "financial juice", "breaking news")}
    candidates = [source for source, markers in signals.items() if any(marker.casefold() in haystack for marker in markers)]
    source = candidates[0] if candidates else "unknown"
    expected = {
        "financialjuice": ("original headline", "importance", "possible impact", "ai commentary"),
    }
    if source == "unknown":
        status, reason = "invalid_source", "source_not_recognized"
    elif not (
        any(marker.casefold() in haystack for marker in expected[source])
        or _trusted_identity(markers=signals[source], sender=sender, subject=subject)
    ):
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
    if result["parse_status"] == "parsed" and parse_external_email is None:
        # The Railway root image intentionally does not contain the repository
        # ``src`` package.  It may still route by the public provider bundle,
        # but it cannot derive Creator/FinancialJuice facts.  Previously this
        # path returned an apparently parsed message with zero observations,
        # advanced the Gmail cursor, and lost the content.  Fail closed and
        # leave a redacted DLQ record until the canonical parser is packaged.
        result["parse_status"] = "parser_unavailable"
        result["failure_reason"] = "canonical_external_parser_unavailable"
    # The router previously stopped at source identification, so Railway
    # retained only a cursor/hash and the scheduled publisher never received
    # the reviewed FinancialJuice or Creator facts.  Parse into a bounded,
    # public-safe projection now.  Raw body, sender and transport identifiers
    # remain confined to this request and are never copied to the projection.
    public_rows: list[dict[str, Any]] = []
    if parse_external_email is not None and result["parse_status"] == "parsed":
        try:
            derived = parse_external_email(
                sender=sender,
                subject=subject,
                body=body,
                message_id=message_id,
            )
        except Exception:  # pragma: no cover - parser failures are DLQ-safe
            derived = {"parse_status": "parse_failed", "failure_reason": "derived_parser_error"}
        derived_status = str(derived.get("parse_status") or "parse_failed") if isinstance(derived, dict) else "parse_failed"
        items = derived.get("items") if isinstance(derived, dict) else None
        candidates = items if isinstance(items, list) else [derived]
        for index, candidate in enumerate(candidates):
            if not isinstance(candidate, dict) or candidate.get("parse_status") not in {"parsed", "normalized"}:
                continue
            row = {key: candidate[key] for key in _PUBLIC_FIELDS if key in candidate}
            item_id = str(candidate.get("item_id") or "").strip()
            row["observation_id"] = item_id or f"email-{result['template_fingerprint'][:20]}-{index}"
            row["source"] = str(candidate.get("content_origin") or route["source"])
            row["content_origin"] = row["source"]
            row["public_safe"] = True
            row["parse_status"] = "normalized"
            public_rows.append(row)
        if derived_status not in {"parsed", "normalized"}:
            result["parse_status"] = derived_status if derived_status in DLQ_STATES else "parse_failed"
            result["failure_reason"] = str(
                derived.get("failure_reason") if isinstance(derived, dict) else "derived_parser_error"
            )[:120] or "derived_parser_error"
        elif not public_rows:
            # A parser must produce at least one public-safe observation; do
            # not acknowledge a message that would otherwise disappear after
            # the source route succeeded.
            result["parse_status"] = "parse_failed"
            result["failure_reason"] = "derived_parser_no_public_observation"
    result["public_observations"] = public_rows
    return result


__all__ = ["DLQ_STATES", "parse_email", "route_source", "template_fingerprint"]
