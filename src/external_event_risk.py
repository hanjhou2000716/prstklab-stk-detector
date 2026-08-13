"""Cross-source event identity and conservative PRStK risk scoring."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any

from src.creator_provider_registry import editorial_creator_ids

SOURCE_TIERS = {
    "gmail": "transport",
    "financialjuice": "discovery",
    "jin10": "discovery",
    "gdelt": "discovery",
    "reuters": "trusted_media",
    "ap": "trusted_media",
    "official": "official",
    "twse": "official",
    "sec": "official",
    "fed": "official",
}
for _creator_id in editorial_creator_ids():
    SOURCE_TIERS[_creator_id] = "editorial"
EDITORIAL_SOURCES = set(editorial_creator_ids())

# Normalize common Traditional/Simplified Chinese and English aliases before
# clustering.  This is deliberately a small deterministic lexicon: it helps
# identify the same event across feeds without pretending semantic certainty.
TERM_ALIASES = {
    "川普": "trump",
    "特朗普": "trump",
    "donald trump": "trump",
    "taco": "taco",
    "伊朗": "iran",
    "波斯": "iran",
    "戰爭": "war",
    "战争": "war",
    "衝突": "conflict",
    "冲突": "conflict",
    "會談": "talk",
    "谈判": "talk",
    "談判": "talk",
    "協商": "talk",
    "协商": "talk",
    "talks": "talk",
    "negotiation": "talk",
    "dialogue": "talk",
}


def source_tier(source: str) -> str:
    return SOURCE_TIERS.get(str(source or "").casefold(), "discovery")


def _norm(value: Any) -> str:
    text = " ".join(str(value or "").casefold().split())
    text = re.sub(r"[^\w\u3400-\u9fff]+", " ", text).strip()
    for alias, canonical in sorted(TERM_ALIASES.items(), key=lambda item: -len(item[0])):
        text = text.replace(alias.casefold(), canonical)
    return " ".join(text.split())


def _bucket(value: Any, minutes: int = 120) -> str:
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        timestamp = timestamp.replace(tzinfo=timestamp.tzinfo or UTC).astimezone(UTC)
        return str(int(timestamp.timestamp()) // (minutes * 60))
    except (TypeError, ValueError):
        return "unknown"


def event_cluster_key(event: dict[str, Any]) -> str:
    """Create a source-independent key from actor/action/location/time facts."""
    fields = (
        _norm(event.get("event_type") or event.get("category")),
        _norm(event.get("actor") or event.get("person") or event.get("entities")),
        _norm(event.get("action") or event.get("event_action")),
        _norm(event.get("location") or event.get("market")),
        _bucket(event.get("occurred_at") or event.get("published_at")),
    )
    material = "|".join(fields)
    return f"evt-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"


def event_fingerprint(event: dict[str, Any]) -> dict[str, str]:
    """Return explainable entity/action/location identity fields."""
    return {
        "entity": _norm(event.get("actor") or event.get("person") or event.get("entities")),
        "action": _norm(event.get("action") or event.get("event_action")),
        "location": _norm(event.get("location") or event.get("market")),
    }


def cluster_external_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge observations while excluding editorial commentary from evidence."""
    clusters: dict[str, dict[str, Any]] = {}
    for event in events:
        source = str(event.get("source") or event.get("content_origin") or "unknown").casefold()
        key = event_cluster_key(event)
        cluster = clusters.setdefault(key, {
            "event_cluster_key": key,
            "event_type": event.get("event_type") or event.get("category") or "unknown",
            "observations": [],
            "source_domains": [],
            "evidence_sources": [],
            "editorial_sources": [],
            "fingerprints": event_fingerprint(event),
        })
        observation = dict(event)
        observation["source_tier"] = source_tier(source)
        cluster["observations"].append(observation)
        if source_tier(source) == "editorial":
            cluster["editorial_sources"].append(source)
        else:
            cluster["evidence_sources"].append(source)
        domain = _norm(event.get("source_domain") or event.get("domain"))
        if domain:
            cluster["source_domains"].append(domain)
    for cluster in clusters.values():
        for field in ("source_domains", "evidence_sources", "editorial_sources"):
            cluster[field] = sorted(set(cluster[field]))
        cluster["cross_source_count"] = len(cluster["evidence_sources"])
    return list(clusters.values())


def score_prstk_risk(
    cluster: dict[str, Any],
    *,
    official_confirmed: bool = False,
    market_sync_confirmed: bool = False,
    vendor_importance: int | None = None,
) -> dict[str, Any]:
    """Score R0-R4 without allowing a single vendor score to become critical."""
    category = str(cluster.get("event_type") or "unknown").casefold()
    evidence_count = int(cluster.get("cross_source_count") or 0)
    editorial_only = evidence_count == 0 and bool(cluster.get("editorial_sources"))
    material = category in {"conflict", "black_swan", "policy", "macro", "energy", "market", "disaster"}
    if not material:
        level, reason = "R0", "non_material_or_unclassified"
    elif official_confirmed and market_sync_confirmed:
        level, reason = "R4", "official_and_market_sync_confirmed"
    elif official_confirmed or evidence_count >= 2:
        level, reason = "R3", "official_or_independent_corroboration"
    elif editorial_only:
        level, reason = "R1", "editorial_content_is_not_event_evidence"
    else:
        level, reason = "R2", "single_source_observation_pending_crosscheck"
    # Vendor importance is metadata, never a risk override.
    return {
        "prstk_risk_level": level,
        "risk_rank": int(level[1]),
        "risk_reason": reason,
        "vendor_importance": vendor_importance,
        "official_confirmed": bool(official_confirmed),
        "market_sync_confirmed": bool(market_sync_confirmed),
        "notification_eligible": level in {"R3", "R4"},
        "high_priority": level == "R4",
    }


def notification_decision(score: dict[str, Any]) -> dict[str, Any]:
    """Return an explicit delivery decision and missing evidence reasons."""
    level = str(score.get("prstk_risk_level") or "R0")
    reasons: list[str] = []
    if level in {"R0", "R1", "R2"}:
        reasons.append("risk_threshold_not_reached")
    if level == "R4" and score.get("official_confirmed") is not True:
        reasons.append("official_confirmation_missing")
    if level == "R4" and score.get("market_sync_confirmed") is not True:
        reasons.append("market_sync_missing")
    return {"allowed": not reasons, "status": "eligible" if not reasons else "pending", "reasons": reasons}


__all__ = ["cluster_external_events", "event_cluster_key", "event_fingerprint", "notification_decision", "score_prstk_risk", "source_tier"]
