"""Build and verify an immutable public release manifest.

The manifest is the join point for market, research and event artifacts.  A
Mini App must never combine files from different releases: callers validate
the manifest first and only then load the hash-addressed artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.artifact_contract import validate_release
from src.atomic_file import replace_with_retry
from src.creator_artifact import validate_creator_artifact
from src.creator_release import validate_creator_release
from src.production_acceptance import (
    production_research_contract_errors,
    validate_production_bundle,
)
from src.research_fallback import mark_stale_research_fallback

DEFAULT_ARTIFACTS = {
    "market.json": Path("site/data/market.json"),
    "research-report.json": Path("site/data/research-report.json"),
    "event-ledger.json": Path("site/data/event-ledger.json"),
}

ALERT_INDEX_NAME = "alert-index.json"
ALERT_ARTIFACT_PREFIX = "alerts"
MAX_ALERT_INDEX_ROWS = 1000
ALERT_RETENTION_DAYS = 30
CANONICAL_HASH_VERSION = 2

SOURCE_HEALTH_ARTIFACT = "source-health.json"


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _alert_filename(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-")[:96]
    return safe or hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def canonical_alert_content_hash(
    event: dict[str, Any], *, public_short_message: str = "",
    brief_title: str = "", title: str = "", event_text: str = "",
) -> str:
    """Hash stable public alert content while excluding release metadata.

    Delivery receipts can cause the same market snapshot to be published in a
    later release.  This fingerprint lets the browser prove that the later
    alert is the same public event without treating changing quotes or
    timestamps as a material content change.
    """
    source_key = str(
        event.get("source_key") or event.get("source") or event.get("content_origin") or ""
    ).strip().casefold()
    public_summary = " ".join(str(public_short_message or brief_title or title).split())
    fact = " ".join(str(event_text or event.get("event") or event.get("summary") or title).split())
    payload = {
        "source_key": source_key,
        "public_summary": public_summary,
        "event": fact,
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _alert_projection(event: dict[str, Any], *, release_id: str, market_snapshot_id: str, created_at: str) -> dict[str, Any]:
    """Create the immutable public detail for one notification identity."""
    notification_id = str(
        event.get("notification_id") or event.get("alert_id") or event.get("event_cluster_key")
        or event.get("event_key") or event.get("item_id") or ""
    ).strip()
    if not notification_id:
        notification_id = f"notification-{hashlib.sha256(_canonical_json(event)).hexdigest()[:24]}"
    evidence = event.get("market_evidence")
    if not isinstance(evidence, list):
        evidence = []
    title = str(event.get("title") or event.get("event") or "市場事件").strip() or "市場事件"
    source_key = str(event.get("source_key") or event.get("source") or "").strip().casefold()
    if source_key == "financialjuice":
        from src.financialjuice_notification import financialjuice_public_short_message
        from src.telegram_client import is_valid_public_summary

        generated_public_short_message = financialjuice_public_short_message(event)
        stored_public_short_message = str(event.get("public_short_message") or "").strip()
        public_short_message = (
            generated_public_short_message
            if is_valid_public_summary(generated_public_short_message, source="financialjuice")
            else stored_public_short_message
        )
        if not is_valid_public_summary(public_short_message, source="financialjuice"):
            raise ValueError("financialjuice event has no valid public summary")
        brief_title = public_short_message
        # ``title`` is also consumed by older Mini App bundles.  Bind it to
        # the same canonical public sentence so an archived alert cannot show
        # a different raw headline from the Telegram message.
        title = public_short_message
    else:
        public_short_message = ""
        brief_title = str(event.get("brief_title") or title).strip() or title
    event_text = str(event.get("event") or title).strip() or title
    canonical_content_hash = canonical_alert_content_hash(
        event,
        public_short_message=public_short_message,
        brief_title=brief_title,
        title=title,
        event_text=event_text,
    )
    linked_markets = event.get("linked_markets")
    if not isinstance(linked_markets, list):
        linked_markets = [
            str(item.get("ticker") or "").strip()
            for item in evidence
            if isinstance(item, dict) and str(item.get("ticker") or "").strip()
        ]
    return {
        "schema_version": "1.0",
        "kind": event.get("kind") or "external_event",
        "source": event.get("source") or "公開來源",
        "source_key": event.get("source_key"),
        "notification_id": notification_id,
        "alert_id": str(event.get("alert_id") or notification_id),
        "event_cluster_key": event.get("event_cluster_key"),
        "release_id": release_id,
        "snapshot_id": str(event.get("snapshot_id") or market_snapshot_id),
        "observation_id": event.get("observation_id"),
        "created_at": created_at,
        "canonical_content_hash": canonical_content_hash,
        "canonical_hash_version": CANONICAL_HASH_VERSION,
        # Keep the headline aliases required by the Mini App.  Archived alert
        # artifacts are rendered independently of the live market snapshot.
        "title": title,
        "brief_title": brief_title,
        "public_short_message": public_short_message,
        "short_label": event.get("short_label") or event.get("source") or "公開事件",
        "event": event.get("event") or title,
        "linked_markets": linked_markets,
        "why_important": event.get("why_important") or event.get("importance_detail"),
        "possible_linkage": event.get("possible_linkage") or event.get("possible_impact") or event.get("market_context"),
        "stock_observation": event.get("stock_observation") or event.get("watch") or event.get("follow_up_observation"),
        "market_evidence": [item for item in evidence[:2] if isinstance(item, dict)],
        "source_evidence": event.get("source_evidence") or [],
        "source_trace": event.get("source_trace") or {},
        "vendor_importance": event.get("vendor_importance"),
        "prstk_risk_level": event.get("prstk_risk_level") or event.get("risk_level"),
        "prstk_risk": event.get("prstk_risk") or {},
        "notification_status": event.get("notification_status"),
        "notification_reason": event.get("notification_reason"),
    }


def _briefing_projection(
    briefing: dict[str, Any], *, release_id: str, market_snapshot_id: str, created_at: str,
) -> dict[str, Any]:
    """Create the immutable alert used by a scheduled multi-source briefing."""
    briefing_id = str(briefing.get("briefing_id") or "").strip()
    public_message = str(briefing.get("public_short_message") or "").strip()
    if not briefing_id or not public_message:
        raise ValueError("scheduled briefing has no public identity or message")
    if len(public_message) > 60 or "..." in public_message or "…" in public_message:
        raise ValueError("scheduled briefing public message violates the text contract")
    content_hash = str(briefing.get("canonical_content_hash") or "").strip()
    if not content_hash:
        raise ValueError("scheduled briefing has no canonical content hash")
    return {
        "schema_version": "1.0",
        "kind": "market_briefing",
        "source": "PRStK 多來源市場判讀",
        "source_key": "scheduled_brief",
        "notification_id": briefing_id,
        "alert_id": briefing_id,
        "event_cluster_key": briefing_id,
        "release_id": release_id,
        "snapshot_id": str(market_snapshot_id),
        "observation_id": briefing.get("observation_id"),
        "created_at": created_at,
        "canonical_content_hash": content_hash,
        "canonical_hash_version": briefing.get("canonical_hash_version", 1),
        "title": public_message,
        "brief_title": public_message,
        "public_short_message": public_message,
        "short_label": "市場判讀",
        "event": briefing.get("assessment_summary") or briefing.get("overview") or public_message,
        "why_important": "本次判讀整合最近24小時的公開事件與市場資料。",
        "possible_linkage": "各市場若分歧，保留分歧，不直接推論跨市場因果。",
        "stock_observation": "持續核對台美主要指數、利率與相關產業價格。",
        "market_evidence": [item for item in (briefing.get("evidence") or [])[:6] if isinstance(item, dict)],
        "source_evidence": [item for item in (briefing.get("evidence") or [])[:6] if isinstance(item, dict)],
        "briefing": {
            "slot": briefing.get("slot"),
            "as_of": briefing.get("as_of"),
            "themes": briefing.get("themes") or [],
            "evidence": briefing.get("evidence") or [],
        },
        "notification_status": briefing.get("status"),
        "notification_reason": briefing.get("notification_reason"),
    }


def _publish_alert_artifacts(
    *, root: Path, market: dict[str, Any], release_id: str, created_at: str,
    resolved: dict[str, Path], hashes: dict[str, str],
) -> None:
    """Write release-bound alert details and a bounded historical index.

    Alert files are release-specific and therefore never overwritten when the
    same notification is observed again in a later release.  The index is the
    only lookup table; the browser verifies its hash through the current
    manifest before it follows an archived deep link.
    """
    alert_dir = root / "site" / "data" / ALERT_ARTIFACT_PREFIX
    alert_dir.mkdir(parents=True, exist_ok=True)
    index_path = root / "site" / "data" / ALERT_INDEX_NAME
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    # The retained immutable files are the source of truth.  Reusing a stale
    # index row can keep a deleted/moved artifact addressable and was the
    # reason historical files existed without a matching current index row.
    # Rebuild every row from the files on each release instead.
    for path in sorted(alert_dir.glob("*.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(item, dict) and item.get("notification_id") and item.get("release_id"):
            rows[(str(item["notification_id"]), str(item["release_id"]))] = {
                "notification_id": item["notification_id"],
                "release_id": item["release_id"],
                "snapshot_id": item.get("snapshot_id"),
                "observation_id": item.get("observation_id"),
                "canonical_content_hash": item.get("canonical_content_hash"),
                "canonical_hash_version": item.get("canonical_hash_version"),
                "path": f"{ALERT_ARTIFACT_PREFIX}/{path.name}",
                "sha256": sha256_file(path),
                "created_at": item.get("created_at"),
            }
    event_block = market.get("events") if isinstance(market, dict) else None
    events = event_block.get("items", []) if isinstance(event_block, dict) else []
    for event in events:
        if not isinstance(event, dict):
            continue
        artifact = _alert_projection(
            event, release_id=release_id,
            market_snapshot_id=str(market.get("snapshot_id") or ""),
            created_at=created_at,
        )
        notification_id = str(artifact["notification_id"])
        filename = f"{_alert_filename(notification_id)}-{_alert_filename(release_id)}.json"
        path = alert_dir / filename
        _write_normalized_artifact(path, artifact)
        relative = f"{ALERT_ARTIFACT_PREFIX}/{filename}"
        rows[(notification_id, release_id)] = {
            "notification_id": notification_id,
            "release_id": release_id,
            "snapshot_id": artifact.get("snapshot_id"),
            "observation_id": artifact.get("observation_id"),
            "canonical_content_hash": artifact.get("canonical_content_hash"),
            "canonical_hash_version": artifact.get("canonical_hash_version"),
            "path": relative,
            "sha256": sha256_file(path),
            "created_at": created_at,
        }
        resolved[relative] = path
        hashes[relative] = sha256_file(path)
    briefing = market.get("briefing") if isinstance(market, dict) else None
    if isinstance(briefing, dict) and briefing.get("notification_eligible") is True:
        artifact = _briefing_projection(
            briefing,
            release_id=release_id,
            market_snapshot_id=str(market.get("snapshot_id") or ""),
            created_at=created_at,
        )
        briefing_id = str(artifact["notification_id"])
        filename = f"{_alert_filename(briefing_id)}-{_alert_filename(release_id)}.json"
        path = alert_dir / filename
        _write_normalized_artifact(path, artifact)
        relative = f"{ALERT_ARTIFACT_PREFIX}/{filename}"
        rows[(briefing_id, release_id)] = {
            "notification_id": briefing_id,
            "release_id": release_id,
            "snapshot_id": artifact.get("snapshot_id"),
            "observation_id": artifact.get("observation_id"),
            "canonical_content_hash": artifact.get("canonical_content_hash"),
            "canonical_hash_version": artifact.get("canonical_hash_version"),
            "path": relative,
            "sha256": sha256_file(path),
            "created_at": created_at,
        }
        resolved[relative] = path
        hashes[relative] = sha256_file(path)
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=ALERT_RETENTION_DAYS)

    def is_recent(item: dict[str, Any]) -> bool:
        value = str(item.get("created_at") or "").strip()
        if not value:
            return True
        try:
            created = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return True
        created = created.replace(tzinfo=UTC) if created.tzinfo is None else created.astimezone(UTC)
        return created >= cutoff

    ordered = sorted(rows.values(), key=lambda item: str(item.get("created_at") or ""), reverse=True)
    recent = [item for item in ordered if is_recent(item)]
    older = [item for item in ordered if not is_recent(item)]
    index = {
        "schema_version": "1.0",
        "generated_at": created_at,
        # Every recent immutable alert remains addressable for the policy
        # retention window; the cap applies only to older history.
        "alerts": [*recent, *older[:max(0, MAX_ALERT_INDEX_ROWS - len(recent))]],
    }
    _write_normalized_artifact(index_path, index)
    resolved[ALERT_INDEX_NAME] = index_path
    hashes[ALERT_INDEX_NAME] = sha256_file(index_path)


def _creator_identity_hash(
    creator_artifact: dict[str, Any] | None,
    creator_records: list[dict[str, Any]] | None,
) -> str | None:
    """Hash creator content before derived release lineage is attached."""
    if creator_records is not None:
        material: Any = creator_records
    elif isinstance(creator_artifact, dict):
        material = {
            key: value
            for key, value in creator_artifact.items()
            if key
            not in {
                "release_id",
                "parent_release_id",
                "creator_release_id",
                "generated_at",
                "validation_errors",
                "status",
                "artifact_hash",
            }
        }
    else:
        return None
    return hashlib.sha256(_canonical_json(material)).hexdigest()


def _active_creator_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep retired or unknown Creator mail out of new release identity."""
    from src.creator_provider_registry import creator_ids

    active_ids = set(creator_ids(enabled_only=True))
    return [
        record
        for record in records
        if isinstance(record, dict)
        and str(record.get("creator_id") or record.get("content_origin") or "").strip().casefold() in active_ids
    ]


def content_snapshot_id(value: dict[str, Any], prefix: str) -> str:
    """Return a deterministic ID for a normalized artifact payload."""
    existing = str(value.get("snapshot_id") or "").strip()
    if len(existing) >= 8:
        return existing
    digest = hashlib.sha256(_canonical_json(value)).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _reconcile_news_health(document: dict[str, Any]) -> dict[str, Any]:
    """Bind provider availability to the final stories at the release boundary."""
    markets = document.get("markets")
    if not isinstance(markets, dict):
        return document
    failure_states = {
        "failed", "rate_limited", "parse_failed", "provider_failed",
        "scan_failed", "configuration_missing", "configuration_required", "critical",
    }
    for market, payload in markets.items():
        if not isinstance(payload, dict):
            continue
        stories = [item for item in (payload.get("stories") or []) if isinstance(item, dict)]
        accepted: dict[str, int] = {}
        for story in stories:
            provider = str(story.get("provider") or "unknown")
            accepted[provider] = accepted.get(provider, 0) + 1
        rows = payload.get("source_health")
        if not isinstance(rows, list):
            continue
        failures = 0
        successes = 0
        for row in rows:
            if not isinstance(row, dict) or str(row.get("key") or "") == f"news_{market}":
                continue
            provider = str(row.get("provider") or "unknown")
            raw = row.get("raw_item_count", row.get("item_count", 0))
            try:
                raw_count = max(0, int(raw or 0))
            except (TypeError, ValueError):
                raw_count = 0
            filtered = accepted.get(provider, 0)
            row["raw_item_count"] = raw_count
            row["filtered_item_count"] = filtered
            row["item_count"] = filtered
            if raw_count > 0 and filtered == 0 and row.get("status") == "healthy":
                row["status"] = "no_event"
                row["data_gap"] = "filtered_no_market_match"
            status = str(row.get("status") or "").casefold()
            if status in failure_states:
                failures += 1
            elif status in {"healthy", "no_event", "stale"}:
                successes += 1
        if stories:
            payload["status"] = "ready"
            payload["collection_state"] = "degraded" if failures else "ready"
        elif failures:
            payload["status"] = "no_event"
            payload["collection_state"] = "degraded" if successes else "source_failed"
        else:
            payload["status"] = "no_event"
            payload["collection_state"] = "no_event"
        payload["source_failure_count"] = failures
        summary = payload.get("scan_summary")
        if isinstance(summary, dict):
            summary["failed_provider_count"] = failures
            summary["successful_provider_count"] = successes
            summary["ranked_story_count"] = len(stories)
    return document


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _external_observation_metadata(market: dict[str, Any]) -> dict[str, Any] | None:
    """Return deterministic lineage for sanitized external observations."""
    rows = market.get("external_observations")
    if not isinstance(rows, list):
        return None
    identities: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        observation_id = str(row.get("observation_id") or "").strip()
        source = str(row.get("source") or row.get("content_origin") or "").strip().casefold()
        if observation_id:
            identities.append({"observation_id": observation_id, "source": source})
    identities.sort(key=lambda item: (item["observation_id"], item["source"]))
    return {
        "count": len(identities),
        "observation_ids_hash": hashlib.sha256(_canonical_json(identities)).hexdigest(),
        "sources": sorted({item["source"] for item in identities if item["source"]}),
        "status": "ready" if identities else "no_event",
    }


def _read_object(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.is_file():
        return None, f"missing artifact: {path.as_posix()}"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, f"invalid artifact {path.as_posix()}: {type(exc).__name__}"
    if not isinstance(value, dict):
        return None, f"artifact must be an object: {path.as_posix()}"
    return value, None


def _source_label_from_quote(quote: dict[str, Any]) -> str | None:
    """Return a provider label only when the payload gives unambiguous evidence.

    Older snapshots occasionally carried ``source_label=Yahoo`` next to a TPEx
    URL.  This is a representational defect, not a reason to discard the
    quote; canonicalising it here keeps the release contract fail-closed while
    preserving the original source URL and timestamp.
    """
    quote_source = str(quote.get("quote_source") or "").lower()
    parsed_host = (urlparse(str(quote.get("source_url") or "")).hostname or "").lower().removeprefix("www.")
    # The URL is the strongest provenance evidence.  Older snapshots can
    # carry a stale source_domain/label from a previous fallback provider;
    # allowing those fields to override the URL creates invalid releases.
    if parsed_host:
        if "tpex.org.tw" in parsed_host:
            return "TPEx"
        if "twse.com.tw" in parsed_host:
            return "TWSE"
        if "taifex.com.tw" in parsed_host:
            return "TAIFEX"
        if parsed_host == "yahoo.com" or parsed_host.endswith(".yahoo.com"):
            return "Yahoo"
    source_domain = str(quote.get("source_domain") or "").lower().removeprefix("www.")
    if "tpex.org.tw" in source_domain or "tpex" in quote_source:
        return "TPEx"
    if "twse.com.tw" in source_domain or "twse" in quote_source:
        return "TWSE"
    if "taifex.com.tw" in source_domain or "taifex" in quote_source:
        return "TAIFEX"
    if source_domain == "yahoo.com" or source_domain.endswith(".yahoo.com"):
        return "Yahoo"
    if "yahoo" in quote_source:
        return "Yahoo"
    return None


def _date_only(value: Any) -> str:
    try:
        return str(value or "").replace("Z", "+00:00")[:10]
    except Exception:
        return ""


def _normalize_market(value: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    for collection in ("indices", "quotes"):
        rows = value.get(collection)
        if not isinstance(rows, list):
            continue
        for index, quote in enumerate(rows):
            if not isinstance(quote, dict):
                continue
            provider = _source_label_from_quote(quote)
            parsed_host = (urlparse(str(quote.get("source_url") or "")).hostname or "").lower().removeprefix("www.")
            if parsed_host and str(quote.get("source_domain") or "").strip().lower() != parsed_host:
                quote["source_domain"] = parsed_host
                notes.append(f"{collection}[{index}].source_domain={parsed_host}")
            if provider and str(quote.get("source_label") or "").strip().lower() != provider.lower():
                quote["source_label"] = provider
                notes.append(f"{collection}[{index}].source_label={provider}")
            if provider and str(quote.get("quote_source") or "").strip().lower().find(provider.lower()) < 0:
                quote["quote_source"] = f"{provider} public quote"
                notes.append(f"{collection}[{index}].quote_source={provider}")
            # Legacy snapshots can retain a current timestamp from a source
            # replaced by a stale fallback. Keep the card visible, but never
            # publish the contradictory combination as live or alertable.
            if quote.get("stale_used") is True and str(quote.get("freshness") or "").lower() == "live":
                quote["freshness"] = "recent_close"
                quote["alert_eligible"] = False
                notes.append(f"{collection}[{index}].freshness=recent_close_for_stale_used")
            technical = quote.get("technical_context")
            quote_date = _date_only(quote.get("quote_date") or quote.get("published_at") or quote.get("quote_time"))
            technical_date = _date_only(technical.get("as_of")) if isinstance(technical, dict) else ""
            if technical_date and quote_date and technical_date < quote_date and quote.get("technical_context_stale") is not True:
                quote["technical_context_stale"] = True
                notes.append(f"{collection}[{index}].technical_context_stale=true")
    return notes


def _gap_count(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float) and value.is_integer():
        return max(0, int(value))
    if isinstance(value, dict):
        numbers = [int(item) for item in value.values() if isinstance(item, (int, float)) and not isinstance(item, bool)]
        return max(0, sum(numbers)) if numbers else None
    return None


def _normalize_research(value: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    sources = value.get("sources")
    if not isinstance(sources, list):
        return notes
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            continue
        visible = source.get("visible_candidates", source.get("candidates"))
        if "visible_candidates" not in source and "candidates" in source:
            source["visible_candidates"] = visible
            notes.append(f"sources[{index}].visible_candidates=legacy candidates")
        if "candidates" not in source and "visible_candidates" in source:
            source["candidates"] = visible
            notes.append(f"sources[{index}].candidates=visible_candidates")
        gaps = _gap_count(source.get("data_gap_counts"))
        if gaps is not None and source.get("data_gap_counts") != gaps:
            source["data_gap_counts"] = gaps
            notes.append(f"sources[{index}].data_gap_counts=integer")

        # A scan summary and its published rows are produced by separate
        # steps.  If the row file is interrupted or replaced, an old summary
        # can still claim formal candidates that are not present in this
        # release.  Do not let that contradiction block every subsequent
        # release (and leave the Mini App showing an older snapshot).  Keep
        # the release usable, but downgrade the source to an explicit data
        # gap and suppress the unproven counts.
        visible_count = _gap_count(visible)
        count_mismatch = False
        for field in ("formal_candidates", "observation_candidates", "formal_candidate_count", "observation_candidate_count"):
            count = _gap_count(source.get(field))
            if count is not None and visible_count is not None and count > visible_count:
                source[field] = 0
                notes.append(f"sources[{index}].{field}=0 (exceeds visible_candidates)")
                count_mismatch = True
        if count_mismatch:
            # A summary that claims completion while its published rows are
            # empty is not a complete scan.  Normalize the machine-readable
            # state together with the candidate counts so the release can
            # remain usable without violating the complete-scan invariant.
            if source.get("scan_state") == "complete":
                source["scan_state"] = "building"
                notes.append(f"sources[{index}].scan_state=building (count mismatch)")
            source["candidate_state"] = "data_gap"
            source["blocking_reason"] = (
                "published candidate rows do not support the scan summary counts; "
                "awaiting a complete research scan"
            )
            source["data_gap_counts"] = max(gaps or 0, 1)
            notes.append(f"sources[{index}].candidate_state=data_gap (count mismatch)")
        if source.get("candidate_state") is None:
            scan_state = str(source.get("scan_state") or "")
            unavailable = source.get("data_unavailable") is True or source.get("data_gap") is True
            if scan_state == "building":
                state = "building"
            elif scan_state == "failed":
                state = "failed"
            elif unavailable or (gaps is not None and gaps > 0):
                state = "data_gap"
            elif isinstance(visible, int) and visible > 0:
                state = "available"
            else:
                state = "no_candidates"
            source["candidate_state"] = state
            notes.append(f"sources[{index}].candidate_state={state}")
    return notes


def _normalize_artifacts(loaded: dict[str, dict[str, Any]]) -> list[str]:
    """Repair legacy representational fields before hashing and auditing.

    This does not invent quotes, candidates, timestamps, or event confirmations;
    unresolved quality problems remain validation errors.
    """
    notes: list[str] = []
    market = loaded.get("market.json")
    if market:
        notes.extend(f"market: {item}" for item in _normalize_market(market))
    research = loaded.get("research-report.json")
    if research:
        notes.extend(f"research: {item}" for item in _normalize_research(research))
        if not str(research.get("snapshot_id") or "").strip():
            research["snapshot_id"] = content_snapshot_id(research, "research")
            notes.append("research: snapshot_id=deterministic")
    events = loaded.get("event-ledger.json")
    if events and not str(events.get("snapshot_id") or "").strip():
        events["snapshot_id"] = content_snapshot_id(events, "event")
        notes.append("events: snapshot_id=deterministic")
    return notes


def _write_normalized_artifact(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.normalize.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    replace_with_retry(temporary, path)


def build_release_manifest(
    *,
    root: Path | str = Path("."),
    output: Path | str = Path("site/data/release-manifest.json"),
    policy_version: str | None = None,
    artifacts: dict[str, Path] | None = None,
    require_production_research: bool = False,
    allow_stale_research: bool = False,
    research_fallback_reason: str | None = None,
    max_research_age_hours: float = 24.0,
    creator_artifact: dict[str, Any] | None = None,
    creator_public_artifact: dict[str, Any] | None = None,
    creator_records: list[dict[str, Any]] | None = None,
    creator_morning_batch: bool = False,
) -> dict[str, Any]:
    """Build a manifest without fabricating readiness.

    Missing or contract-invalid files produce ``status=invalid``.  This is
    intentional: the public UI can explain an incomplete release instead of
    silently mixing an old file with a new one.
    """
    root = Path(root)
    if creator_records is not None:
        # The canonical registry is the source of truth for new Creator data.
        # Filtering before release hashing prevents retired mail from creating
        # a new public release even when an old ingress file is replayed.
        creator_records = _active_creator_records(creator_records)
    selected = artifacts or DEFAULT_ARTIFACTS
    resolved = {name: (root / path) for name, path in selected.items()}
    loaded: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    hashes: dict[str, str] = {}
    for name, path in resolved.items():
        value, error = _read_object(path)
        if error:
            errors.append(error)
            continue
        assert value is not None
        loaded[name] = value

    # Routine market/event publishers must remain available when the bounded
    # research scan is incomplete.  Convert that artifact into an explicit
    # stale fallback before hashing it, so the release is internally
    # consistent and the UI can hide candidates instead of silently treating
    # partial research as live.  Strict production callers do not opt into
    # this path unless ``allow_stale_research`` is explicitly set.
    research_candidate = loaded.get("research-report.json")
    fallback_applied = False
    fallback_reason = None
    if allow_stale_research and research_candidate:
        research_errors = production_research_contract_errors(research_candidate)
        if research_errors:
            reason = research_fallback_reason or "; ".join(research_errors)
            loaded["research-report.json"] = mark_stale_research_fallback(
                research_candidate,
                reason,
            )
            fallback_applied = True
            fallback_reason = reason

    normalization_notes = _normalize_artifacts(loaded)
    # Publish source health after legacy normalization so its bound market
    # snapshot ID always points at the exact bytes used by the release.
    market = loaded.get("market.json")
    market_document: dict[str, Any] = market if isinstance(market, dict) else {}
    market_health = market_document.get("source_health")
    if (
        isinstance(market_health, dict)
        and {"status", "sources", "event_scan"}.issubset(market_health)
    ):
        source_health_path = root / "site" / "data" / SOURCE_HEALTH_ARTIFACT
        market_id = content_snapshot_id(market_document, "market")
        source_health = {
            "schema_version": "1.0",
            "snapshot_id": f"{market_id}-health",
            "market_snapshot_id": market_id,
            "generated_at": market_document.get("generated_at"),
            "source_health": market_health,
        }
        try:
            _write_normalized_artifact(source_health_path, source_health)
            resolved[SOURCE_HEALTH_ARTIFACT] = source_health_path
            loaded[SOURCE_HEALTH_ARTIFACT] = source_health
        except OSError as exc:
            errors.append(f"cannot persist source health artifact {source_health_path.as_posix()}: {type(exc).__name__}")
    for name, value in loaded.items():
        path = resolved[name]
        try:
            _write_normalized_artifact(path, value)
            hashes[name] = sha256_file(path)
        except OSError as exc:
            errors.append(f"cannot persist/hash artifact {path.as_posix()}: {type(exc).__name__}")

    market = loaded.get("market.json", {})
    research = loaded.get("research-report.json", {})
    events = loaded.get("event-ledger.json", {})
    backtest_contract = research.get("backtest_release_contract") if isinstance(research, dict) else None
    if not isinstance(backtest_contract, dict):
        backtest_contract = {}
    backtest_release = backtest_contract.get("backtest_release")
    backtest_state = backtest_contract.get("publication_state")
    if backtest_state not in {"ready", "blocked"}:
        backtest_state = "unavailable"
    registry = backtest_contract.get("strategy_registry")
    if not isinstance(registry, list):
        registry = []
    market_id = content_snapshot_id(market, "market") if market else ""
    research_id = content_snapshot_id(research, "research") if research else ""
    event_id = content_snapshot_id(events, "event") if events else ""
    external_metadata = _external_observation_metadata(market)
    # News is an additive, fail-soft artifact.  Keep it content-addressed to
    # the same market snapshot so Pages cannot accidentally combine a new
    # headline list with an older quote release.  Legacy market artifacts
    # without the canonical intelligence payload remain valid and simply do
    # not advertise a separate news artifact.
    news_payload = market.get("news") if isinstance(market, dict) else None
    news_artifact = news_payload.get("intelligence") if isinstance(news_payload, dict) else None
    news_snapshot_id: str | None = None
    news_status = "not_available"
    if isinstance(news_artifact, dict) and isinstance(news_artifact.get("stories"), list):
        news_artifact = {
            **news_artifact,
            "market_snapshot_id": market_id,
            "snapshot_id": content_snapshot_id(news_artifact, "news"),
        }
    elif isinstance(news_artifact, dict) and any(isinstance(value, dict) for value in news_artifact.values()):
        registry = news_payload.get("provider_registry", []) if isinstance(news_payload, dict) else []
        news_markets = news_artifact
        news_artifact = {
            "schema_version": "1.0",
            "market_snapshot_id": market_id,
            "snapshot_id": content_snapshot_id({"markets": news_markets}, "news"),
            "provider_registry": registry,
            "markets": news_markets,
            "status": "ready" if any(
                isinstance(value, dict) and value.get("status") == "ready"
                for value in news_markets.values()
            ) else "no_event",
        }
    if isinstance(news_artifact, dict):
        news_artifact = _reconcile_news_health(news_artifact)
        news_snapshot_id = str(news_artifact["snapshot_id"])
        news_status = "ready" if news_artifact.get("status") in {"ready", "no_event"} else "unavailable"
        news_path = root / "site" / "data" / "news.json"
        try:
            from src.artifact_contract import validate_news_release

            errors.extend(validate_news_release(news_artifact))
            _write_normalized_artifact(news_path, news_artifact)
            resolved["news.json"] = news_path
            loaded["news.json"] = news_artifact
            hashes["news.json"] = sha256_file(news_path)
        except OSError as exc:
            errors.append(f"cannot persist/hash news artifact {news_path.as_posix()}: {type(exc).__name__}")
    creator_input_hash = _creator_identity_hash(creator_artifact, creator_records)
    policy = str(policy_version or os.getenv("POLICY_VERSION") or "2026.08")
    created_at = datetime.now(UTC).isoformat()
    release_material = {
        "market_snapshot_id": market_id,
        "research_snapshot_id": research_id,
        "event_snapshot_id": event_id,
        "backtest_release": backtest_release,
        "backtest_publication_state": backtest_state,
        "strategy_registry": registry,
        "artifact_hashes": hashes,
        "policy_version": policy,
    }
    if creator_input_hash:
        release_material["creator_input_hash"] = creator_input_hash
    if external_metadata is not None:
        release_material["external_observation_ids_hash"] = external_metadata["observation_ids_hash"]
    release_id = f"release-{hashlib.sha256(_canonical_json(release_material)).hexdigest()[:16]}"
    # Alert details are immutable per release and indexed separately from the
    # core release identity.  Keeping them out of ``release_material`` avoids
    # a circular hash (the artifact itself carries its release_id), while the
    # resulting paths/hashes are still covered by the manifest gate.
    _publish_alert_artifacts(
        root=root, market=market, release_id=release_id, created_at=created_at,
        resolved=resolved, hashes=hashes,
    )
    if creator_artifact is None and creator_records is not None:
        # Records are expected to be sanitized at ingress. The pipeline still
        # rechecks privacy/source rules before writing a public artifact.
        from src.creator_intelligence_pipeline import build_creator_intelligence_release

        creator_result = build_creator_intelligence_release(
            creator_records,
            parent_manifest={
                "release_id": release_id,
                "market_snapshot_id": market_id,
                "research_snapshot_id": research_id,
                "event_snapshot_id": event_id,
            },
            # Pass the actual release-bound snapshots into the canonical
            # correlation stage.  Passing IDs alone made the public Creator
            # artifact look lineage-bound while every episode correlation
            # reported ``market_snapshot_missing`` and could not compare
            # explicit tickers/sectors.  The source artifacts are already
            # sanitized and are the same objects used by the release gate.
            market_snapshot=market,
            research_snapshot=research,
            event_snapshot=events,
            # The scheduled morning lane must bind its deterministic 10:30
            # cutoff to the exact market snapshot being released.  Other
            # refreshes intentionally omit the batch so historical reviewed
            # records cannot be presented as a current morning digest.
            batch_as_of=market.get("generated_at") if creator_morning_batch and isinstance(market, dict) else None,
        )
        if creator_result.get("accepted_count", 0) > 0:
            creator_artifact = creator_result["artifact"]
            creator_public_artifact = creator_result.get("public_artifact")
    creator_hash = hashlib.sha256(_canonical_json(creator_artifact)).hexdigest() if isinstance(creator_artifact, dict) else None
    creator_errors = (
        validate_creator_release(creator_artifact, parent_manifest={
            "release_id": release_id,
            "market_snapshot_id": market_id,
            "event_snapshot_id": event_id,
            "research_snapshot_id": research_id,
        })
        if isinstance(creator_artifact, dict)
        else []
    )
    creator_status = "ready" if isinstance(creator_artifact, dict) and not creator_errors else ("unavailable" if isinstance(creator_artifact, dict) else "not_available")
    creator_path: Path | None = None
    if isinstance(creator_artifact, dict):
        creator_path = root / "site" / "data" / "creator-release.json"
        try:
            _write_normalized_artifact(creator_path, creator_artifact)
            resolved["creator-release.json"] = creator_path
            loaded["creator-release.json"] = creator_artifact
            hashes["creator-release.json"] = sha256_file(creator_path)
        except OSError as exc:
            errors.append(f"cannot persist/hash artifact {creator_path.as_posix()}: {type(exc).__name__}")
    creator_public_errors: list[str] = []
    creator_public_hash: str | None = None
    creator_public_status = "not_available"
    if isinstance(creator_public_artifact, dict):
        creator_public_errors.extend(validate_creator_artifact(creator_public_artifact))
        expected_parent = {
            "parent_release_id": release_id,
            "market_snapshot_id": market_id,
            "research_snapshot_id": research_id,
            "event_snapshot_id": event_id,
        }
        for field, expected in expected_parent.items():
            if str(creator_public_artifact.get(field) or "") != expected:
                creator_public_errors.append(f"creator public artifact {field} mismatch")
        creator_public_status = "ready" if not creator_public_errors and creator_public_artifact.get("status") == "ready" else "unavailable"
        creator_public_path = root / "site" / "data" / "creator-insights.json"
        try:
            _write_normalized_artifact(creator_public_path, creator_public_artifact)
            resolved["creator-insights.json"] = creator_public_path
            loaded["creator-insights.json"] = creator_public_artifact
            creator_public_hash = sha256_file(creator_public_path)
            hashes["creator-insights.json"] = creator_public_hash
        except OSError as exc:
            # Creator Intelligence is an optional public lane.  A malformed
            # or unavailable creator artifact must be represented in its own
            # status fields and must not invalidate an otherwise complete
            # market/research/event release.
            creator_public_errors.append(
                f"cannot persist/hash public creator artifact {creator_public_path.as_posix()}: {type(exc).__name__}"
            )
    # Do not add optional creator validation errors to the core release
    # errors.  The creator lane is fail-closed independently at delivery time.
    public_paths = {
        name: (path.relative_to(root / "site").as_posix() if path.is_relative_to(root / "site") else path.as_posix())
        for name, path in resolved.items()
    }
    manifest: dict[str, Any] = {
        "release_id": release_id,
        "created_at": created_at,
        "market_snapshot_id": market_id,
        "research_snapshot_id": research_id,
        "event_snapshot_id": event_id,
        "backtest_release": backtest_release,
        "backtest_publication_state": backtest_state,
        "strategy_registry": registry,
        "policy_version": policy,
        "schema_versions": {
            "market": str(market.get("snapshot_schema_version") or "1.0"),
            "research": str(research.get("schema_version") or "1.0"),
            "events": str(events.get("schema_version") or "1.0"),
            "news": "1.0" if "news.json" in loaded else None,
            "creator_insights": "1.0" if isinstance(creator_public_artifact, dict) else None,
        },
        "artifact_hashes": hashes,
        # Paths are relative to the Pages root so the browser never needs to
        # know the repository checkout layout.
        "artifact_paths": public_paths,
        "normalization_notes": normalization_notes,
        "research_freshness": "unknown",
        "research_fallback_used": fallback_applied,
        "research_fallback_reason": fallback_reason,
        "creator_release_id": (creator_artifact or {}).get("release_id") if isinstance(creator_artifact, dict) else None,
        "creator_status": creator_status,
        "creator_validation_errors": creator_errors,
        "creator_artifact_hash": creator_hash,
        "creator_input_hash": creator_input_hash,
        "creator_public_status": creator_public_status,
        "creator_public_validation_errors": sorted(set(creator_public_errors)),
        "creator_snapshot_id": (creator_public_artifact or {}).get("snapshot_id") if isinstance(creator_public_artifact, dict) else None,
        "creator_public_artifact_hash": creator_public_hash,
        "news_snapshot_id": news_snapshot_id,
        "news_status": news_status,
        "external_observation_count": external_metadata["count"] if external_metadata is not None else None,
        "external_observation_ids_hash": external_metadata["observation_ids_hash"] if external_metadata is not None else None,
        "external_observation_sources": external_metadata["sources"] if external_metadata is not None else [],
        "external_observation_status": external_metadata["status"] if external_metadata is not None else "not_available",
        "status": "invalid",
    }
    if fallback_applied:
        # A stale report may be retained as an audit/rollback artifact, but it
        # must never be paired with a new market snapshot in a ready release.
        errors.append("stale research fallback cannot produce a ready manifest")
    if not market_id or not research_id or not event_id:
        errors.append("all three snapshot IDs are required")
    if market and research and "event-ledger.json" in loaded:
        errors.extend(
            validate_release(
                market=market,
                research=research,
                events=events,
                manifest={**manifest, "status": "ready"},
            )
        )
        if require_production_research:
            acceptance = validate_production_bundle(
                manifest={**manifest, "status": "ready"},
                market=market,
                research=research,
                events=events,
                require_production_research=True,
            )
            errors.extend(acceptance.errors)
            market_time = _parse_artifact_time(market.get("generated_at"))
            research_time = _parse_artifact_time(research.get("generated_at"))
            if market_time is None or research_time is None:
                errors.append("production release requires market/research generated_at")
            else:
                age_hours = max(0.0, (market_time - research_time).total_seconds() / 3600.0)
                if age_hours > max(0.0, float(max_research_age_hours)):
                    errors.append("research snapshot is older than production freshness window")
                    manifest["research_freshness"] = "stale_fallback"
                else:
                    manifest["research_freshness"] = "fresh"
        elif research:
            # A routine market/event publisher still needs to describe the
            # freshness of a production research snapshot.  Previously this
            # branch always emitted ``unverified`` even when the research
            # artifact was a complete production/full scan.  The resulting
            # ready manifest then failed the downstream delivery gate and
            # made every scheduled brief look stale.  Keep non-production or
            # fallback reports explicitly unverified, but compute the same
            # market-vs-research age used by the strict path whenever the
            # research contract is complete.
            market_time = _parse_artifact_time(market.get("generated_at"))
            research_time = _parse_artifact_time(research.get("generated_at"))
            is_production = (
                research.get("scan_mode") == "production"
                and research.get("scan_scope") == "full"
                and research.get("publish_eligible") is True
                and research.get("production_eligible") is True
                and not fallback_applied
            )
            if is_production and market_time is not None and research_time is not None:
                age_hours = (market_time - research_time).total_seconds() / 3600.0
                if 0 <= age_hours <= max(0.0, float(max_research_age_hours)):
                    manifest["research_freshness"] = "fresh"
                else:
                    manifest["research_freshness"] = "stale_fallback"
            else:
                manifest["research_freshness"] = "unverified"
    manifest["validation_errors"] = sorted(set(errors))
    if not errors:
        manifest["status"] = "ready"
    return manifest


def _parse_artifact_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except (TypeError, ValueError):
        return None


def write_release_manifest(manifest: dict[str, Any], output: Path | str) -> None:
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    replace_with_retry(temporary, destination)


def verify_release_files(manifest: dict[str, Any], *, root: Path | str = Path(".")) -> list[str]:
    """Verify that every manifest hash still matches the local artifact."""
    root = Path(root)
    errors: list[str] = []
    hashes = manifest.get("artifact_hashes")
    paths = manifest.get("artifact_paths")
    if not isinstance(hashes, dict) or not isinstance(paths, dict):
        return ["manifest artifact hashes/paths are missing"]
    required = ("market.json", "research-report.json", "event-ledger.json")
    for name in required:
        if name not in hashes:
            errors.append(f"manifest hash missing: {name}")
        if name not in paths:
            errors.append(f"manifest path missing: {name}")
    for name, expected in hashes.items():
        raw_path = paths.get(name)
        if not isinstance(raw_path, str):
            errors.append(f"manifest path missing: {name}")
            continue
        if not raw_path.strip():
            errors.append(f"manifest path empty: {name}")
            continue
        path = root / raw_path
        if not path.is_file():
            errors.append(f"artifact missing: {name}")
            continue
        if not isinstance(expected, str) or len(expected) != 64:
            errors.append(f"manifest hash invalid: {name}")
            continue
        try:
            actual = sha256_file(path)
        except OSError as exc:
            errors.append(f"artifact unreadable {name}: {type(exc).__name__}")
            continue
        if actual != str(expected):
            errors.append(f"artifact hash mismatch: {name}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the public release manifest")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=Path("site/data/release-manifest.json"))
    parser.add_argument("--policy-version", default=None)
    parser.add_argument("--require-production-research", action="store_true")
    parser.add_argument("--allow-stale-research", action="store_true")
    parser.add_argument("--research-fallback-reason", default=None)
    parser.add_argument("--max-research-age-hours", type=float, default=24.0)
    parser.add_argument(
        "--creator-records",
        type=Path,
        default=None,
        help="optional JSON array of sanitized public Creator Insight records",
    )
    parser.add_argument(
        "--creator-morning-batch",
        action="store_true",
        help="bind the Creator 10:30 Asia/Taipei batch to the market snapshot timestamp",
    )
    args = parser.parse_args()
    creator_records: list[dict[str, Any]] | None = None
    if args.creator_records is not None:
        creator_path = args.creator_records.resolve()
        public_root = (args.root / "site").resolve()
        if creator_path.is_relative_to(public_root):
            parser.error("creator records must be outside the public site tree")
        try:
            payload = json.loads(creator_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            parser.error(f"creator records are unreadable: {type(exc).__name__}")
        if isinstance(payload, dict):
            payload = payload.get("records")
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            parser.error("creator records must be a JSON array of objects")
        creator_records = payload
    manifest = build_release_manifest(
        root=args.root,
        output=args.output,
        policy_version=args.policy_version,
        require_production_research=args.require_production_research,
        allow_stale_research=args.allow_stale_research,
        research_fallback_reason=args.research_fallback_reason,
        max_research_age_hours=args.max_research_age_hours,
        creator_records=creator_records,
        creator_morning_batch=args.creator_morning_batch,
    )
    write_release_manifest(manifest, args.output)
    print(json.dumps({"status": manifest["status"], "release_id": manifest["release_id"], "validation_errors": manifest["validation_errors"]}, ensure_ascii=False))
    return 0 if manifest["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
