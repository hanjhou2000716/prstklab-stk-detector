"""Schema and cross-field validation for published intelligence artifacts.

The validator is side-effect free and fail-closed: callers can validate a
candidate release before publishing it or sending a notification.
"""

from __future__ import annotations

import json
import ntpath
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from jsonschema import Draft202012Validator, FormatChecker

from src.intelligence_contract import validate_intelligence

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


def _instrument_master_contract_errors(document: dict[str, Any]) -> list[str]:
    """Keep quote identity bound to the registry embedded in the snapshot.

    The field is additive for legacy artifacts. Once a producer emits the
    registry artifact, every quote must carry the same content-addressed ID so
    a release cannot combine a quote with a different symbol mapping.
    """
    artifact = document.get("instrument_master")
    if artifact is None:
        return []
    if not isinstance(artifact, dict):
        return ["market.instrument_master must be an object"]
    errors = _schema_errors(artifact, "instrument-master.schema.json")
    registry_id = str(artifact.get("registry_id") or "")
    schema_version = artifact.get("schema_version")
    for collection in ("indices", "quotes"):
        for index, quote in enumerate(document.get(collection, [])):
            if not isinstance(quote, dict):
                continue
            path = f"{collection}[{index}]"
            if quote.get("instrument_master_id") != registry_id:
                errors.append(f"{path}: instrument_master_id does not match market registry")
            if quote.get("instrument_master_version") != schema_version:
                errors.append(f"{path}: instrument_master_version does not match market registry")
    return errors


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

    # Once a producer publishes the source-priority policy, keep the policy
    # bound to the exact ticker and comparison semantics.  Without this
    # invariant a stale/legacy row can advertise (for example) the TAIEX
    # direction-only rule while carrying another instrument's price policy.
    policy = quote.get("crosscheck_policy")
    if isinstance(policy, dict):
        policy_ticker = str(policy.get("ticker") or "").strip().upper()
        ticker = str(quote.get("ticker") or "").strip().upper()
        if policy_ticker and ticker and policy_ticker != ticker:
            errors.append(f"{path}: crosscheck_policy.ticker does not match quote ticker")
        primary = policy.get("primary")
        secondary = policy.get("secondary")
        if isinstance(primary, list) and isinstance(secondary, list):
            expected = [str(item) for item in [*primary, *secondary] if str(item).strip()]
            declared = quote.get("expected_sources")
            if isinstance(declared, list) and declared and [str(item) for item in declared] != expected:
                errors.append(f"{path}: expected_sources does not match crosscheck_policy")
            basis = quote.get("comparison_basis")
            if basis is not None:
                required_basis = "direction_only" if ticker == "TAIEX" else "price_and_time"
                if basis != required_basis:
                    errors.append(f"{path}: comparison_basis conflicts with crosscheck_policy")

    fetched = _parse_time(quote.get("fetched_at"))
    published = _parse_time(quote.get("published_at"))
    if fetched and published and published > fetched:
        errors.append(f"{path}: published_at is later than fetched_at")

    quote_date = _parse_time(quote.get("quote_date"))
    technical = quote.get("technical_context")
    technical_date = _parse_time(technical.get("as_of")) if isinstance(technical, dict) else None
    technical_stale = bool(
        quote.get("technical_context_stale")
        or (technical.get("technical_context_stale") if isinstance(technical, dict) else False)
    )
    if quote_date and technical_date and technical_date.date() < quote_date.date() and not technical_stale:
        errors.append(f"{path}: technical context predates quote without technical_context_stale=true")
    return errors


def validate_market(document: dict[str, Any]) -> list[str]:
    """Validate market schema and quote-level safety invariants."""
    errors = _schema_errors(document, "market.schema.json")
    errors.extend(validate_source_catalog(document.get("source_catalog")))
    errors.extend(_raw_observation_contract_errors(document))
    errors.extend(_instrument_master_contract_errors(document))
    for collection in ("indices", "quotes"):
        for index, quote in enumerate(document.get(collection, [])):
            if isinstance(quote, dict):
                errors.extend(_quote_contract_errors(quote, f"{collection}[{index}]"))
    source_health = document.get("source_health")
    # Older releases only contain a legacy ``data_gaps`` map.  Keep those
    # artifacts readable while enforcing the full contract whenever the
    # canonical source-health envelope is present.
    if isinstance(source_health, dict) and {"status", "sources", "event_scan"}.issubset(source_health):
        errors.extend(validate_source_health(source_health))
    briefing = document.get("briefing")
    if isinstance(briefing, dict) and isinstance(briefing.get("intelligence"), dict):
        errors.extend(validate_intelligence(briefing["intelligence"]))
    news = document.get("news")
    if isinstance(news, dict) and isinstance(news.get("intelligence"), dict):
        intelligence = news["intelligence"]
        if any(key in intelligence for key in ("taiwan", "us")):
            for market, payload in intelligence.items():
                if market not in {"taiwan", "us"} or not isinstance(payload, dict):
                    continue
                candidate = dict(payload)
                if not candidate.get("provider_registry"):
                    candidate["provider_registry"] = news.get("provider_registry", [])
                errors.extend(f"news.intelligence[{market}]: {error}" for error in validate_news_intelligence(candidate))
        else:
            errors.extend(validate_news_intelligence(intelligence))
    return errors


def validate_news_intelligence(document: dict[str, Any]) -> list[str]:
    """Validate the additive NewsStory/relevance contract in market releases."""
    errors = _schema_errors(document, "news-intelligence.schema.json")
    registry = document.get("provider_registry")
    known: dict[str, dict[str, Any]] = {}
    if not isinstance(registry, list):
        return errors + ["news provider_registry must be an array"]
    diversity = document.get("source_diversity")
    if diversity is not None:
        if not isinstance(diversity, dict):
            errors.append("news.source_diversity must be an object")
        else:
            status = str(diversity.get("status") or "")
            if status not in {"no_event", "single_source", "multi_source"}:
                errors.append("news.source_diversity.status is invalid")
            count = diversity.get("independent_source_count")
            if not isinstance(count, int) or count < 0:
                errors.append("news.source_diversity.independent_source_count must be non-negative")
            else:
                expected_cross_checked = count >= 2
                if diversity.get("cross_checked") is not expected_cross_checked:
                    errors.append("news.source_diversity.cross_checked disagrees with source count")
                if document.get("stories") and status == "no_event":
                    errors.append("news.source_diversity.no_event conflicts with stories")
                if not document.get("stories") and status != "no_event":
                    errors.append("news.source_diversity status must be no_event without stories")
                if count >= 2 and status != "multi_source":
                    errors.append("news.source_diversity status must be multi_source for two sources")
                if count < 2 and document.get("stories") and status != "single_source":
                    errors.append("news.source_diversity status must be single_source for one source")
    for index, provider in enumerate(registry):
        if not isinstance(provider, dict):
            errors.append(f"news.provider_registry[{index}] must be an object")
            continue
        provider_id = str(provider.get("provider_id") or "").strip()
        domains = provider.get("domains")
        if not provider_id or not isinstance(domains, list):
            errors.append(f"news.provider_registry[{index}] requires provider_id/domains")
            continue
        if provider_id in known:
            errors.append(f"news.provider_registry duplicates {provider_id}")
        known[provider_id] = provider
        # Feed metadata is optional for compatibility with older artifacts,
        # but when present it is part of the canonical adapter contract.
        feed_kind = provider.get("feed_kind")
        if feed_kind is not None and feed_kind not in {"json", "rss", "atom", "html"}:
            errors.append(f"news.provider_registry[{index}] has unsupported feed_kind={feed_kind!r}")
        if "feed_url" in provider:
            feed_url = str(provider.get("feed_url") or "")
            if feed_url:
                parsed_feed = urlparse(feed_url)
                feed_host = (parsed_feed.hostname or "").lower().removeprefix("www.")
                if parsed_feed.scheme != "https" or not feed_host:
                    errors.append(f"news.provider_registry[{index}] feed_url must be an absolute HTTPS URL")
                elif not any(feed_host == domain or feed_host.endswith("." + domain) for domain in (str(item).lower().removeprefix("www.") for item in domains)):
                    errors.append(f"news.provider_registry[{index}] feed_url is outside provider domains")
            elif provider.get("enabled") is True:
                errors.append(f"news.provider_registry[{index}] enabled feed requires feed_url")
    for index, story in enumerate(document.get("stories", [])):
        if not isinstance(story, dict):
            continue
        path = f"news.stories[{index}]"
        provider = str(story.get("provider") or "")
        if provider not in known:
            errors.append(f"{path}: provider is not in provider_registry")
            continue
        url = str(story.get("canonical_url") or "")
        host = (urlparse(url).hostname or "").lower().removeprefix("www.")
        domains = [str(item).lower().removeprefix("www.") for item in known[provider].get("domains", [])]
        if not url.startswith("https://") or not any(host == domain or host.endswith("." + domain) for domain in domains):
            errors.append(f"{path}: canonical_url is outside provider domains")
        if story.get("public_safe") is not True:
            errors.append(f"{path}: public_safe must be true for published news")
    return errors


def _safe_item_count(row: Mapping[str, Any]) -> int:
    """Read provider item counts without letting malformed diagnostics crash audit."""
    # ``item_count`` historically represented the provider's raw response
    # size.  Release-bound news health now also carries
    # ``filtered_item_count`` after market-scope and eligibility routing.  Use
    # that explicit post-filter value when present so a successful provider
    # whose headlines were all rejected does not create the impossible
    # ``stories=0 + available provider items`` release state.  Older releases
    # without the field continue to use the legacy count for compatibility.
    if "filtered_item_count" in row:
        value = row.get("filtered_item_count")
    else:
        funnel = row.get("funnel")
        if isinstance(funnel, Mapping) and "eligible_count" in funnel:
            # Some producers expose the post-routing count only in the
            # observability funnel.  It is the same semantic quantity as the
            # top-level filtered count and is safer than treating raw feed
            # volume as publishable stories.
            value = funnel.get("eligible_count")
        else:
            value = row.get("item_count")
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def validate_news_release(document: dict[str, Any]) -> list[str]:
    """Validate the release-bound multi-market News artifact."""
    if not isinstance(document, dict):
        return ["news release must be an object"]
    markets = document.get("markets")
    if not isinstance(markets, dict):
        return validate_news_intelligence(document)
    errors: list[str] = _schema_errors(document, "news-release.schema.json")
    for field in ("schema_version", "market_snapshot_id", "snapshot_id"):
        if not str(document.get(field) or ""):
            errors.append(f"news release {field} is missing")
    registry = document.get("provider_registry")
    for market, payload in markets.items():
        if market not in {"taiwan", "us"}:
            errors.append(f"news release has unsupported market={market!r}")
        if not isinstance(payload, dict):
            errors.append(f"news release markets[{market}] must be an object")
            continue
        candidate = dict(payload)
        if not candidate.get("provider_registry") and isinstance(registry, list):
            candidate["provider_registry"] = registry
        errors.extend(f"markets[{market}]: {error}" for error in validate_news_intelligence(candidate))
        # A release must not claim a complete source failure when any provider
        # successfully completed (even with no matching headline), nor claim
        # failure while publishing stories.  This catches the production bug
        # where the aggregate market-news health was healthy but the US
        # intelligence panel was incorrectly marked source_failed.
        collection_state = str(candidate.get("collection_state") or "").casefold()
        stories = candidate.get("stories") or []
        provider_rows = [
            row for row in (candidate.get("source_health") or [])
            if isinstance(row, dict) and str(row.get("key") or "") != f"news_{market}"
        ]
        successful_rows = [
            row for row in provider_rows
            if str(row.get("status") or "").casefold() in {"healthy", "no_event", "stale"}
        ]
        available_rows = [
            row for row in provider_rows
            if str(row.get("status") or "").casefold() == "healthy"
            and _safe_item_count(row) > 0
        ]
        if collection_state == "source_failed" and (stories or successful_rows):
            errors.append(f"markets[{market}]: source_failed conflicts with published/provider-success data")
        if stories and collection_state == "no_event":
            errors.append(f"markets[{market}]: no_event conflicts with published stories")
        if not stories and available_rows:
            errors.append(f"markets[{market}]: empty stories conflict with available provider items")
        for index, story in enumerate(candidate.get("stories", [])):
            if isinstance(story, dict) and story.get("market") not in {market, "global", "cross_market"}:
                errors.append(f"markets[{market}].stories[{index}]: market does not match envelope")
    return errors


def _raw_observation_contract_errors(document: dict[str, Any]) -> list[str]:
    """Validate durable raw-observation state without hiding degradation."""
    envelope = document.get("raw_observation")
    if envelope is None:
        return []
    if not isinstance(envelope, dict):
        return ["market.raw_observation must be an object"]
    errors: list[str] = []
    enabled = envelope.get("enabled") is True
    recorded = envelope.get("recorded") is True
    required = envelope.get("required") is True
    state = envelope.get("state")
    observation_id = str(envelope.get("observation_id") or "").strip()
    if state == "recorded" and not (enabled and recorded and observation_id):
        errors.append("market.raw_observation state=recorded requires enabled, recorded and observation_id")
    if state == "disabled" and (enabled or recorded or required):
        errors.append("market.raw_observation state=disabled conflicts with enabled/recorded/required")
    if state == "unavailable" and recorded:
        errors.append("market.raw_observation state=unavailable cannot be recorded")
    if required and not recorded:
        errors.append("market.raw_observation required=true requires recorded=true")
    if recorded and not observation_id:
        errors.append("market.raw_observation recorded=true requires observation_id")
    return errors


def validate_source_health(document: dict[str, Any]) -> list[str]:
    """Validate source-health semantics without collapsing no-event into failure.

    The field is intentionally additive for older releases.  When present,
    machine states must agree with the display status so a healthy card cannot
    hide a failed scan, and an empty-but-successful scan remains observable.
    """
    errors = _schema_errors(document, "source-health.schema.json")
    # Keep this vocabulary aligned with src.failure_semantics so a producer
    # cannot emit a canonical state that the release validator silently treats
    # as an unknown status or a missing source.
    allowed_status = {
        "healthy", "no_event", "no_new_content", "fallback_active",
        "degraded_with_fallback", "secondary_unavailable", "configuration_missing",
        "configuration_required", "warming", "stale", "partial", "optional_degraded",
        "parse_failed", "provider_failed", "failed", "scan_failed", "critical",
        "pending", "pending_confirmation", "release_blocked",
    }
    gap_states = {
        "fallback_active", "degraded_with_fallback", "secondary_unavailable",
        "configuration_missing", "configuration_required", "stale", "partial",
        "optional_degraded", "parse_failed", "provider_failed", "failed",
        "scan_failed", "critical", "pending_confirmation", "release_blocked",
    }
    declared_missing = document.get("missing_source_count")
    if isinstance(declared_missing, int) and declared_missing >= 0:
        actual_missing = 0
        for source in document.get("sources", []):
            if isinstance(source, dict) and str(source.get("semantic_state") or source.get("status") or "") in gap_states:
                actual_missing += 1
        if declared_missing != actual_missing:
            errors.append(
                "source_health.missing_source_count does not match source semantic states"
            )
    for field in ("runtime_failure_count", "configuration_missing_count"):
        value = document.get(field)
        if isinstance(value, int) and value < 0:
            errors.append(f"source_health.{field} must be non-negative")
    runtime_failure_count = document.get("runtime_failure_count")
    configuration_missing_count = document.get("configuration_missing_count")
    if isinstance(runtime_failure_count, int) and isinstance(configuration_missing_count, int):
        actual_runtime = 0
        actual_configuration = 0
        for source in document.get("sources", []):
            if not isinstance(source, dict):
                continue
            semantic = str(source.get("semantic_state") or source.get("status") or "")
            if semantic == "configuration_missing":
                actual_configuration += 1
            elif semantic in gap_states:
                actual_runtime += 1
        if runtime_failure_count != actual_runtime:
            errors.append("source_health.runtime_failure_count does not match source semantic states")
        if configuration_missing_count != actual_configuration:
            errors.append("source_health.configuration_missing_count does not match source semantic states")
    for index, source in enumerate(document.get("sources", [])):
        if not isinstance(source, dict):
            continue
        path = f"source_health.sources[{index}]"
        status = str(source.get("status") or "")
        semantic = str(source.get("semantic_state") or "")
        if status and status not in allowed_status:
            errors.append(f"{path}: unknown status={status!r}")
        if status in {"healthy", "no_event", "no_new_content"} and semantic in gap_states:
            errors.append(f"{path}: healthy/no_event status conflicts with semantic_state={semantic}")
        if semantic in {"healthy", "no_event", "no_new_content"} and status in gap_states:
            errors.append(f"{path}: failed status conflicts with semantic_state={semantic}")
        if source.get("no_event") is True and status in gap_states:
            errors.append(f"{path}: no_event cannot be a failed source")
    event_scan = document.get("event_scan")
    if isinstance(event_scan, dict) and event_scan.get("status") in {"no_event", "no_events"}:
        failed = [
            source for source in document.get("sources", [])
            if isinstance(source, dict) and (
                source.get("status") in gap_states
                or source.get("semantic_state") in gap_states
            ) and (
                str(source.get("role") or "") == "required_for_core"
                or str(source.get("key") or "") in {"market_quotes", "official_events"}
            )
        ]
        if failed:
            errors.append("source_health: event_scan=no_event cannot coexist with failed core sources")
    if isinstance(event_scan, dict) and event_scan.get("status") == "scan_failed":
        if event_scan.get("has_events") is True:
            errors.append("source_health.event_scan=scan_failed cannot claim has_events=true")
    observability = document.get("observability")
    if isinstance(observability, dict):
        failures = observability.get("failure_count")
        no_events = observability.get("no_event_count")
        if isinstance(failures, int) and isinstance(no_events, int) and failures < 0:
            errors.append("source_health.observability.failure_count must be non-negative")
        history = observability.get("history")
        if isinstance(history, dict):
            samples = history.get("samples")
            sample_count = history.get("sample_count")
            max_samples = history.get("max_samples")
            if isinstance(samples, list) and isinstance(sample_count, int) and sample_count != len(samples):
                errors.append("source_health.observability.history.sample_count does not match samples")
            if isinstance(samples, list) and isinstance(max_samples, int) and len(samples) > max_samples:
                errors.append("source_health.observability.history exceeds max_samples")
            for window_name in ("24h", "7d"):
                metric = history.get("windows", {}).get(window_name) if isinstance(history.get("windows"), dict) else None
                if not isinstance(metric, dict):
                    continue
                window_count = metric.get("sample_count")
                if isinstance(window_count, int) and isinstance(sample_count, int) and window_count > sample_count:
                    errors.append(f"source_health.observability.history.{window_name}.sample_count exceeds history.sample_count")
                if metric.get("state") == "no_observations" and window_count not in (0, None):
                    errors.append(f"source_health.observability.history.{window_name} no_observations has samples")
    return errors


def validate_source_catalog(catalog: Any) -> list[str]:
    """Validate the declarative adapter catalog embedded in a market release.

    The catalog is evidence about the adapters used by the producer, not just
    display metadata.  Reject duplicate providers and incomplete contracts so
    a release cannot claim a cross-check policy that its source registry does
    not describe.
    """
    if catalog is None:
        return []
    if not isinstance(catalog, list):
        return ["market.source_catalog must be an array"]
    errors: list[str] = []
    providers: set[str] = set()
    for index, item in enumerate(catalog):
        path = f"source_catalog[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{path} must be an object")
            continue
        provider = str(item.get("provider") or "").strip()
        if not provider:
            errors.append(f"{path}.provider is required")
        elif provider.casefold() in providers:
            errors.append(f"{path}.provider is duplicated")
        else:
            providers.add(provider.casefold())
        contract = item.get("adapter_contract_version")
        if not isinstance(contract, int) or contract < 1:
            errors.append(f"{path}.adapter_contract_version must be a positive integer")
        for field in ("provenance_fields", "health_fields"):
            values = item.get(field)
            if not isinstance(values, list) or not all(isinstance(value, str) and value.strip() for value in values):
                errors.append(f"{path}.{field} must be a non-empty string array")
        policy = str(item.get("alert_policy") or "")
        if policy not in {"crosscheck_required", "display_only"}:
            errors.append(f"{path}.alert_policy is invalid")
        if item.get("can_trigger_alert") is True and policy != "crosscheck_required":
            errors.append(f"{path}.can_trigger_alert requires crosscheck_required")
        if item.get("can_trigger_alert") is False and policy == "crosscheck_required":
            errors.append(f"{path}.can_trigger_alert=false conflicts with crosscheck_required")
    return errors


def validate_source_health_artifact(document: dict[str, Any]) -> list[str]:
    """Validate the release-bound source-health envelope and its binding."""
    errors = _schema_errors(document, "source-health-artifact.schema.json")
    market_snapshot_id = str(document.get("market_snapshot_id") or "").strip()
    snapshot_id = str(document.get("snapshot_id") or "").strip()
    if market_snapshot_id and snapshot_id and snapshot_id != f"{market_snapshot_id}-health":
        errors.append("source_health_artifact.snapshot_id does not match market_snapshot_id")
    health = document.get("source_health")
    if isinstance(health, dict):
        errors.extend(validate_source_health(health))
    return errors


def validate_research(document: dict[str, Any]) -> list[str]:
    """Validate candidate state semantics and source completeness.

    Machine-readable state is authoritative; localized status text is never
    parsed for safety decisions.
    """
    errors = _schema_errors(document, "research-report.schema.json")
    allowed_states = {
        None,
        "available",
        "available_from_completed_records",
        "no_candidates",
        "building",
        "data_gap",
        "data_unavailable",
        "failed",
    }
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
        failed_records = source.get("failed_records", source.get("failed"))
        try:
            failed_count = max(0, int(failed_records or 0))
        except (TypeError, ValueError):
            failed_count = 0
        gap_value = source.get("data_gap_counts")
        def _safe_count(value: Any) -> int:
            try:
                return max(0, int(value or 0))
            except (TypeError, ValueError):
                return 0

        if isinstance(gap_value, dict):
            gap_count = sum(_safe_count(value) for value in gap_value.values())
        else:
            gap_count = _safe_count(gap_value)
        requested = source.get("requested_records", source.get("requested"))
        completed = source.get("complete_records", source.get("data_complete"))
        requested_count = _safe_count(requested)
        completed_count = _safe_count(completed)
        if scan_state == "complete" and unavailable:
            errors.append(f"{path}: complete scan cannot be marked data_unavailable/data_gap")
        if scan_state == "complete" and failed_count:
            errors.append(f"{path}: complete scan cannot contain failed records")
        if scan_state == "complete" and gap_count:
            errors.append(f"{path}: complete scan cannot contain data gaps")
        if scan_state == "complete" and requested_count and completed_count < requested_count:
            errors.append(f"{path}: complete scan universe is incomplete")
        if scan_state == "complete" and candidate_state in {"building", "data_gap", "data_unavailable", "failed"}:
            errors.append(f"{path}: complete scan cannot use incomplete candidate_state={candidate_state}")
        if candidate_state not in allowed_states:
            errors.append(f"{path}: unknown candidate_state={candidate_state!r}")
        if candidate_state == "no_candidates" and unavailable:
            errors.append(f"{path}: no_candidates and data_gap are mutually exclusive")
        if isinstance(candidates, int) and isinstance(visible, int) and candidates != visible:
            errors.append(f"{path}: candidates must equal visible_candidates")
        if candidate_state == "no_candidates" and isinstance(visible, int) and visible != 0:
            errors.append(f"{path}: no_candidates requires visible_candidates=0")
        if candidate_state in {"available", "available_from_completed_records"} and isinstance(visible, int) and visible == 0:
            errors.append(f"{path}: available requires visible_candidates>0")
        if isinstance(candidates, int) and isinstance(formal, int) and formal > candidates:
            errors.append(f"{path}: formal_candidates cannot exceed candidates")
    scan_mode = str(document.get("scan_mode") or "")
    if document.get("publish_eligible") is True and scan_mode != "production":
        errors.append("research publish_eligible=true requires scan_mode=production")
    if document.get("publish_eligible") is True and document.get("scan_scope") != "full":
        errors.append("research publish_eligible=true requires scan_scope=full")
    if document.get("production_eligible") is True and scan_mode != "production":
        errors.append("research production_eligible=true requires scan_mode=production")
    if document.get("production_eligible") is True and document.get("scan_scope") != "full":
        errors.append("research production_eligible=true requires scan_scope=full")
    if document.get("production_eligible") is True and document.get("publish_eligible") is not True:
        errors.append("research production_eligible=true requires publish_eligible=true")
    if document.get("research_fallback_used") is True and document.get("production_eligible") is True:
        errors.append("research fallback cannot be production_eligible=true")
    errors.extend(_backtest_release_contract_errors(document))
    errors.extend(_candidate_explainability_errors(document))
    return errors


def _candidate_explainability_errors(document: dict[str, Any]) -> list[str]:
    """Validate the optional machine-readable candidate explanation contract.

    The nested object is additive for legacy reports.  Once a producer emits
    it, all decision-relevant fields must be present and type-safe so the UI
    cannot present an unexplained score as a formal candidate.
    """
    errors: list[str] = []
    rows = document.get("candidates")
    if not isinstance(rows, list):
        return errors
    list_fields = ("passed_conditions", "failed_conditions", "risk_factors", "evidence")
    required = set(list_fields) | {"data_completeness", "signal_date", "invalidation"}
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or "explainability" not in row:
            continue
        path = f"candidates[{index}].explainability"
        explanation = row.get("explainability")
        if not isinstance(explanation, dict):
            errors.append(f"{path} must be an object")
            continue
        missing = sorted(required - explanation.keys())
        if missing:
            errors.append(f"{path} missing required fields: {', '.join(missing)}")
        for field in list_fields:
            value = explanation.get(field)
            if value is not None and not isinstance(value, list):
                errors.append(f"{path}.{field} must be an array")
        if explanation.get("signal_date") is not None and not isinstance(explanation.get("signal_date"), str):
            errors.append(f"{path}.signal_date must be a string or null")
    return errors


def _backtest_release_contract_errors(document: dict[str, Any]) -> list[str]:
    """Keep research and candidate backtest identity consistent.

    The contract is additive so older observation-only reports remain readable.
    Once a report advertises a backtest status or candidate binding, every
    identity and publication flag is checked fail-closed.
    """
    errors: list[str] = []
    status = document.get("backtest_release_status")
    contract = document.get("backtest_release_contract")
    rows = document.get("candidates")
    candidates = rows if isinstance(rows, list) else []
    candidate_bound = any(
        isinstance(row, dict)
        and ("backtest_release" in row or "backtest_release_contract" in row)
        for row in candidates
    )
    if status is None and contract is None and not candidate_bound:
        return errors
    if status is not None and status not in {"ready", "blocked", "unavailable"}:
        errors.append(f"backtest_release_status has unknown value={status!r}")
    if contract is not None and not isinstance(contract, dict):
        errors.append("backtest_release_contract must be an object")
        contract = None
    # Legacy blocked contracts from before the formal backtest schema may only
    # contain the publication flags and a partial registry. Keep those
    # observation-only documents readable; once a producer emits any of the
    # formal contract fields, the complete schema gate applies.
    formal_contract = isinstance(contract, dict) and any(
        field in contract for field in (
            "market", "research_only", "strategy_registry_validation",
            "performance_summary", "survivorship_audit",
        )
    )
    if formal_contract and isinstance(contract, dict):
        # The release boundary must enforce the same formal contract used by
        # the producer.  Manual checks below remain for stable, actionable
        # compatibility errors, while the schema rejects unknown fields and
        # malformed nested rows before publication.
        try:
            errors.extend(_schema_errors(contract, "backtest-release.schema.json"))
        except (OSError, ValueError, TypeError) as exc:
            errors.append(f"backtest_release_contract schema unavailable: {type(exc).__name__}")
    contract_state = contract.get("publication_state") if contract else None
    release_id = str(contract.get("backtest_release") or "").strip() if contract else ""
    publish_eligible = contract.get("publish_eligible") if contract else None
    if status in {"ready", "blocked"} and contract is None:
        errors.append(f"backtest_release_status={status} requires backtest_release_contract")
    if contract is not None:
        if contract_state not in {"ready", "blocked", "unavailable"}:
            errors.append(f"backtest_release_contract has unknown publication_state={contract_state!r}")
        if status is not None and contract_state != status:
            errors.append("backtest_release_status must match contract.publication_state")
        if contract_state == "ready" and publish_eligible is not True:
            errors.append("ready backtest contract requires publish_eligible=true")
        if contract_state in {"blocked", "unavailable"} and publish_eligible is True:
            errors.append("blocked/unavailable backtest contract cannot be publish_eligible=true")
        if contract_state == "ready" and not release_id:
            errors.append("ready backtest contract requires backtest_release")
        registry_ids = {
            str(item.get("strategy_id"))
            for item in (contract.get("strategy_registry") or [])
            if isinstance(item, dict) and item.get("strategy_id")
        }
        if contract_state == "ready" and not registry_ids:
            errors.append("ready backtest contract requires strategy_registry")
        if contract_state == "ready":
            for item in (contract.get("strategy_registry") or []):
                if not isinstance(item, dict):
                    errors.append("ready backtest strategy_registry rows must be objects")
                    continue
                for field in ("strategy_id", "strategy_version", "parameter_hash", "universe_version", "data_version", "code_commit", "backtest_release"):
                    if item.get(field) in (None, ""):
                        errors.append(f"ready backtest strategy_registry.{field} is missing")
                if item.get("backtest_release") not in (None, release_id):
                    errors.append("ready backtest strategy_registry.backtest_release does not match contract")
    for index, row in enumerate(candidates):
        if not isinstance(row, dict):
            continue
        candidate_release = str(row.get("backtest_release") or "").strip()
        candidate_contract = row.get("backtest_release_contract")
        path = f"candidates[{index}]"
        if candidate_release and not release_id:
            errors.append(f"{path}: backtest_release has no matching research contract")
        if candidate_release and release_id and candidate_release != release_id:
            errors.append(f"{path}: backtest_release does not match research contract")
        strategy_id = str(row.get("strategy") or row.get("strategy_id") or "").strip()
        if contract_state == "ready" and strategy_id and strategy_id not in registry_ids:
            errors.append(f"{path}: strategy is absent from ready backtest registry")
        if candidate_contract is not None:
            if not isinstance(candidate_contract, dict):
                errors.append(f"{path}: backtest_release_contract must be an object")
                continue
            candidate_release_id = str(candidate_contract.get("backtest_release") or "").strip()
            if release_id and candidate_release_id != release_id:
                errors.append(f"{path}: candidate contract release does not match research contract")
            if contract_state and candidate_contract.get("publication_state") != contract_state:
                errors.append(f"{path}: candidate contract state does not match research contract")
            if candidate_contract.get("publish_eligible") is True and contract_state != "ready":
                errors.append(f"{path}: candidate cannot be publish_eligible unless research contract is ready")
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
    errors = _schema_errors(document, "release-manifest.schema.json")
    paths = document.get("artifact_paths")
    hashes = document.get("artifact_hashes")
    if isinstance(paths, dict) and isinstance(hashes, dict):
        required = ("market.json", "research-report.json", "event-ledger.json")
        for name in required:
            path = str(paths.get(name) or "").strip()
            digest = str(hashes.get(name) or "").strip()
            # Release artifact paths are portable logical paths.  ``Path``
            # follows the runner OS, so a Windows drive path would otherwise
            # pass validation on Linux (and vice versa).  Validate both
            # separators and drive/UNC prefixes explicitly.
            portable_path = path.replace("\\", "/")
            drive, _ = ntpath.splitdrive(path)
            is_absolute = bool(
                portable_path.startswith("/")
                or portable_path.startswith("//")
                or drive
            )
            path_parts = tuple(part for part in portable_path.split("/") if part)
            if path and is_absolute:
                errors.append(f"manifest artifact path must be relative: {name}")
            if path and ".." in path_parts:
                errors.append(f"manifest artifact path escapes release root: {name}")
            if path and digest and len(digest) == 64:
                continue
    if document.get("status") == "rolled_back" and not str(document.get("rollback_release_id") or "").strip():
        errors.append("rolled_back manifest requires rollback_release_id")
    if document.get("status") == "ready" and document.get("rollback_release_id"):
        errors.append("ready manifest cannot declare rollback_release_id")
    return sorted(set(errors))


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
