"""Schema and cross-field validation for published intelligence artifacts.

The validator is side-effect free and fail-closed: callers can validate a
candidate release before publishing it or sending a notification.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        # Compare timestamps on one timeline.  Public feeds frequently omit
        # an offset while generated artifacts include one; mixing naive and
        # aware values otherwise crashes the audit instead of failing closed.
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except (TypeError, ValueError):
        return None


def _schema_errors(document: dict[str, Any], schema_name: str) -> list[str]:
    schema = json.loads((SCHEMA_DIR / schema_name).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [f"schema: {error.json_path} {error.message}" for error in validator.iter_errors(document)]


def _quote_contract_errors(quote: dict[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    freshness = str(quote.get("freshness") or "")
    if quote.get("stale_used") is True and freshness == "live":
        errors.append(f"{path}: stale_used=true cannot be freshness=live")
    if quote.get("quote_delayed") is True and quote.get("alert_eligible") is True:
        errors.append(f"{path}: delayed quote cannot be alert_eligible=true")

    source_label = str(quote.get("source_label") or "").strip().lower()
    source = str(quote.get("quote_source") or "").strip().lower()
    url = str(quote.get("source_url") or "").strip()
    domain = (urlparse(url).hostname or "").lower().removeprefix("www.") if url else ""
    official_labels = {"twse", "taifex", "tpex"}
    if source_label in official_labels and domain and not any(
        token in domain for token in ("twse.com.tw", "taifex.com.tw", "tpex.org.tw")
    ):
        errors.append(f"{path}: official source_label conflicts with source_domain={domain}")
    if source_label == "yahoo" and domain and "yahoo.com" not in domain:
        errors.append(f"{path}: Yahoo source_label conflicts with source_domain={domain}")
    # TPEx is often rendered as TPEX/TPEx in the provider label.
    normalized_label = "tpex" if source_label == "tpex" else source_label
    if normalized_label and source and normalized_label not in source:
        errors.append(f"{path}: source_label is not represented in quote_source")

    fetched = _parse_time(quote.get("fetched_at"))
    published = _parse_time(quote.get("published_at"))
    if fetched and published and published > fetched:
        errors.append(f"{path}: published_at is later than fetched_at")

    quote_date = _parse_time(quote.get("quote_date"))
    technical = quote.get("technical_context")
    technical_date = _parse_time(technical.get("as_of")) if isinstance(technical, dict) else None
    if quote_date and technical_date and technical_date.date() < quote_date.date() and not quote.get("technical_context_stale"):
        errors.append(f"{path}: technical context predates quote without technical_context_stale=true")
    return errors


def validate_market(document: dict[str, Any]) -> list[str]:
    """Validate market schema and quote-level safety invariants."""
    errors = _schema_errors(document, "market.schema.json")
    for collection in ("indices", "quotes"):
        for index, quote in enumerate(document.get(collection, [])):
            if isinstance(quote, dict):
                errors.extend(_quote_contract_errors(quote, f"{collection}[{index}]"))
    return errors


def validate_research(document: dict[str, Any]) -> list[str]:
    """Validate candidate state semantics and source completeness.

    Machine-readable state is authoritative; localized status text is never
    parsed for safety decisions.
    """
    errors = _schema_errors(document, "research-report.schema.json")
    allowed_states = {None, "available", "no_candidates", "data_gap", "building", "failed"}
    for index, source in enumerate(document.get("sources", [])):
        if not isinstance(source, dict):
            continue
        path = f"sources[{index}]"
        scan_state = source.get("scan_state")
        candidate_state = source.get("candidate_state")
        candidates = source.get("candidates")
        visible = source.get("visible_candidates")
        formal = source.get("formal_candidates")
        unavailable = source.get("data_unavailable") is True or source.get("data_gap") is True
        if scan_state == "complete" and unavailable:
            errors.append(f"{path}: complete scan cannot be marked data_unavailable/data_gap")
        if candidate_state not in allowed_states:
            errors.append(f"{path}: unknown candidate_state={candidate_state!r}")
        if candidate_state == "no_candidates" and unavailable:
            errors.append(f"{path}: no_candidates and data_gap are mutually exclusive")
        if isinstance(candidates, int) and isinstance(visible, int) and candidates != visible:
            errors.append(f"{path}: candidates must equal visible_candidates")
        if candidate_state == "no_candidates" and isinstance(visible, int) and visible != 0:
            errors.append(f"{path}: no_candidates requires visible_candidates=0")
        if candidate_state == "available" and isinstance(visible, int) and visible == 0:
            errors.append(f"{path}: available requires visible_candidates>0")
        if isinstance(candidates, int) and isinstance(formal, int) and formal > candidates:
            errors.append(f"{path}: formal_candidates cannot exceed candidates")
    return errors


def validate_events(document: dict[str, Any]) -> list[str]:
    """Validate the durable event ledger before it joins a release.

    The ledger is an input to notification decisions, so malformed timestamps,
    source provenance, or non-canonical keys must fail closed rather than being
    silently carried into the next snapshot.
    """
    errors = _schema_errors(document, "event-ledger.schema.json")
    events = document.get("events", {})
    if not isinstance(events, dict):
        return errors
    for key, event in events.items():
        if not isinstance(event, dict):
            continue
        path = f"events[{key!r}]"
        if str(event.get("canonical_key") or "") != str(key):
            errors.append(f"{path}: canonical_key must match ledger key")
        source_url = str(event.get("source_url") or "")
        parsed_url = urlparse(source_url)
        if parsed_url.scheme != "https" or not parsed_url.hostname:
            errors.append(f"{path}: source_url must be an absolute HTTPS URL")
        source_domain = str(event.get("source_domain") or "").lower().removeprefix("www.")
        if parsed_url.hostname and source_domain and parsed_url.hostname.lower().removeprefix("www.") != source_domain:
            errors.append(f"{path}: source_domain does not match source_url")
        first_seen = _parse_time(event.get("first_discovered_at"))
        updated = _parse_time(event.get("updated_at"))
        if first_seen and updated and updated < first_seen:
            errors.append(f"{path}: updated_at precedes first_discovered_at")
        verified = event.get("verified_sources")
        if isinstance(verified, list):
            for index, url in enumerate(verified):
                parsed = urlparse(str(url))
                if parsed.scheme != "https" or not parsed.hostname:
                    errors.append(f"{path}.verified_sources[{index}]: must be an absolute HTTPS URL")
    return errors


def validate_manifest(document: dict[str, Any]) -> list[str]:
    """Validate the release manifest envelope."""
    return _schema_errors(document, "release-manifest.schema.json")


def validate_release(
    *,
    market: dict[str, Any],
    research: dict[str, Any],
    manifest: dict[str, Any],
    events: dict[str, Any] | None = None,
) -> list[str]:
    """Validate a release and ensure its artifacts refer to one snapshot."""
    errors = validate_manifest(manifest)
    errors.extend(validate_market(market))
    errors.extend(validate_research(research))
    if events is not None:
        errors.extend(validate_events(events))
    expected_market = str(manifest.get("market_snapshot_id") or "")
    expected_research = str(manifest.get("research_snapshot_id") or "")
    if expected_market and str(market.get("snapshot_id") or "") != expected_market:
        errors.append("release: market snapshot_id does not match manifest")
    if expected_research and str(research.get("snapshot_id") or "") != expected_research:
        errors.append("release: research snapshot_id does not match manifest")
    expected_event = str(manifest.get("event_snapshot_id") or "")
    event_snapshot = str((events or {}).get("snapshot_id") or "")
    if expected_event and event_snapshot and event_snapshot != expected_event:
        errors.append("release: event snapshot_id does not match manifest")
    return errors
