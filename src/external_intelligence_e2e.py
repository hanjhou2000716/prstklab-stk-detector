"""Offline smoke path for the external intelligence boundary.

This deliberately uses no network, Gmail credentials or Telegram recipients.
It proves that a sanitized mail observation can be parsed, risk-scored and
attached to a creator-safe release without bypassing evidence gates.
"""

from __future__ import annotations

from typing import Any

from src.creator_delivery_contract import decide_creator_delivery
from src.creator_intelligence_pipeline import build_creator_intelligence_release
from src.email_intelligence import normalize_email_observation
from src.external_event_risk import cluster_external_events, notification_decision, score_prstk_risk
from src.external_source_parsers import parse_external_email


def run_external_intelligence_dry_run() -> dict[str, Any]:
    observation = normalize_email_observation({
        "message_id": "dry-run-1",
        "sender": "alerts@financialjuice.com",
        "subject": "Iran oil supply risk",
        "body": "Event: Iran conflict may affect oil supply. Importance: monitor.",
        "received_at": "2026-08-12T00:00:00Z",
    })
    parsed = parse_external_email(
        sender=observation["sender"],
        subject=observation["subject"],
        body="Event: Iran conflict may affect oil supply. Importance: monitor.",
        message_id=observation["gmail_message_id"],
    )
    external = {
        "event_type": "energy",
        "title": observation["subject"],
        "summary": parsed.get("summary") or observation["subject"],
        "source": observation["content_origin"],
        "source_domain": "financialjuice.com",
        "source_tier": "discovery",
        "source_url": "https://financialjuice.com/",
    }
    clusters = cluster_external_events([external])
    score = score_prstk_risk(clusters[0]) if clusters else {"prstk_risk_level": "R0", "notification_eligible": False}
    parent = {"release_id": "release-dry-run", "market_snapshot_id": "market-dry-run", "event_snapshot_id": "event-dry-run"}
    creator_insight = {
        "content_origin": "haojiao",
        "episode_key": "dry-run-creator-episode",
        "notification_type": "initial",
        "public_safe": True,
        "verification_state": "partially_verified",
        "title": "Offline creator intelligence observation",
    }
    creator_result = build_creator_intelligence_release([creator_insight], parent_manifest=parent)
    creator = creator_result["artifact"]
    creator_delivery = decide_creator_delivery(
        creator_insight,
        release_ready=creator["status"] == "ready",
        media_available=False,
    )
    return {
        "email_observation": {"parse_status": observation["parse_status"], "content_origin": observation["content_origin"]},
        "parser": {"parse_status": parsed.get("parse_status"), "failure_reason": parsed.get("failure_reason")},
        "external_risk": {"level": score.get("prstk_risk_level"), "notification": notification_decision(score)},
        "creator_release": {"status": creator["status"], "parent_release_id": creator["parent_release_id"]},
        "creator_pipeline": {"accepted_count": creator_result["accepted_count"], "dropped_count": creator_result["dropped_count"]},
        "creator_delivery": creator_delivery,
        "network_used": False,
        "secrets_used": False,
        "formal_delivery": False,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(run_external_intelligence_dry_run(), ensure_ascii=False, indent=2))
