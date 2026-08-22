"""Offline end-to-end acceptance for release, Mini App and Telegram contracts.

The command deliberately stops at a mocked Telegram boundary. It exercises
the same fail-closed release and delivery decisions used by production while
never contacting Telegram, Railway, Pages, or market providers.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from typing import Any

from src.creator_delivery_contract import decide_creator_delivery
from src.creator_intelligence_pipeline import build_creator_intelligence_release
from src.creator_morning_batch import build_creator_morning_batch
from src.creator_notification_e2e import run_creator_notification_e2e
from src.external_source_parsers import parse_financialjuice_email
from src.financialjuice_priority import project_financialjuice_priority
from src.production_acceptance import validate_production_bundle
from src.system_dry_run import run_dry_run

_FINANCIALJUICE_COMPOUND_FIXTURE = (
    "Item 1\nImportance: 9/10\nOriginal headline: Oil supply disruption\n"
    "Translation: Public oil supply update\nEntities: Iran, oil\n"
    "AI commentary: Supply risk remains under observation.\n"
    "Possible impact: Oil volatility.\n"
    "Item 2\nImportance: 7/10\nOriginal headline: Semiconductor export control\n"
    "Translation: Public semiconductor policy update\nEntities: China, semiconductor\n"
    "AI commentary: Chip access changes require confirmation.\n"
    "Possible impact: Technology volatility."
)


def _financialjuice_offline_lane() -> dict[str, Any]:
    """Exercise sanitized FJ ingress through parsing and release projection.

    This is intentionally a SIMULATED lane: it never contacts Gmail, Railway,
    FinancialJuice, Pages, or Telegram. Keeping it in the same offline E2E
    command prevents the parser and vendor-priority policy from becoming a
    unit-tested island while preserving the production release gate.
    """
    parsed = parse_financialjuice_email(
        sender="alerts@financialjuice.com",
        subject="compound alert",
        body=_FINANCIALJUICE_COMPOUND_FIXTURE,
        message_id="production-e2e-fj-message",
    )
    raw_items = parsed.get("items")
    items: list[dict[str, Any]] = (
        [item for item in raw_items if isinstance(item, dict)]
        if isinstance(raw_items, list)
        else []
    )
    projection = project_financialjuice_priority(items)
    decisions = projection.get("decisions") or []
    events = projection.get("events") or []
    cluster_keys = {
        str(item.get("event_cluster_key") or "").strip()
        for item in items
        if isinstance(item, dict)
    }
    statuses = {
        str(item.get("notification_status") or "").strip()
        for item in decisions
        if isinstance(item, dict)
    }
    eligible = [item for item in decisions if isinstance(item, dict) and item.get("notification_status") == "eligible"]
    below_threshold = [item for item in decisions if isinstance(item, dict) and item.get("notification_status") == "not_eligible"]
    separation_ok = all(
        isinstance(event, dict)
        and event.get("source_trace", {}).get("vendor_importance_is_not_risk") is True
        and event.get("market_direction") is None
        for event in events
    )
    return {
        "mode": "SIMULATED",
        "ok": (
            parsed.get("parse_status") == "parsed"
            and parsed.get("compound") is True
            and parsed.get("item_count") == 2
            and len(items) == 2
            and len(cluster_keys) == 2
            and statuses == {"eligible", "not_eligible"}
            and len(eligible) == 1
            and len(below_threshold) == 1
            and separation_ok
        ),
        "parse_status": parsed.get("parse_status"),
        "item_count": len(items),
        "independent_cluster_count": len(cluster_keys),
        "eligible_importances": [item.get("vendor_importance") for item in eligible],
        "below_threshold_importances": [item.get("vendor_importance") for item in below_threshold],
        "vendor_risk_separation": separation_ok,
        "network_used": False,
        "secrets_used": False,
    }


def _creator_morning_offline_lane() -> dict[str, Any]:
    """Exercise the 10:30 Asia/Taipei two-provider batch contract offline."""
    records = [
        {
            "creator_id": "haojiao",
            "episode_key": "e2e-haojiao-20260821",
            "published_at": "2026-08-21T01:55:00+00:00",
            "received_at": "2026-08-21T02:00:00+00:00",
            "public_safe": True,
            "parse_status": "parsed",
        },
        {
            "creator_id": "jenny",
            "episode_key": "e2e-jenny-20260821",
            "published_at": "2026-08-21T02:00:00+00:00",
            "received_at": "2026-08-21T02:05:00+00:00",
            "public_safe": True,
            "parse_status": "parsed",
        },
    ]
    batch = build_creator_morning_batch(
        records,
        as_of="2026-08-21T03:00:00+00:00",
        expected_creators=("haojiao", "jenny"),
    )
    return {
        "mode": "SIMULATED",
        "ok": (
            batch.get("state") == "complete"
            and batch.get("expected_count") == 2
            and batch.get("received_count") == 2
            and batch.get("missing_creators") == []
            and len(batch.get("records") or []) == 2
        ),
        "state": batch.get("state"),
        "expected_count": batch.get("expected_count"),
        "received_count": batch.get("received_count"),
        "batch_key": batch.get("batch_key"),
        "network_used": False,
        "secrets_used": False,
    }


def _ready_bundle() -> dict[str, dict[str, Any]]:
    """Return a minimal internally consistent production release fixture."""
    return {
        "manifest": {
            "status": "ready",
            "release_id": "e2e-release",
            "market_snapshot_id": "e2e-market",
            "research_snapshot_id": "e2e-research",
            "event_snapshot_id": "e2e-events",
        },
        "market": {
            "snapshot_id": "e2e-market",
            "overall_state": "mixed",
            "stale_count": 0,
            "unavailable_count": 0,
        },
        "research": {
            "snapshot_id": "e2e-research",
            "scan_mode": "production",
            "scan_scope": "full",
            "publish_eligible": True,
            "production_eligible": True,
            "universe_expected": 1,
            "universe_scanned": 1,
            "universe_completed": 1,
            "universe_failed": 0,
            "generated_at": "2026-08-12T10:00:00+00:00",
            "run_id": "e2e-research-run",
            "research_run": {
                "run_id": "e2e-research-run",
                "source_commit_sha": "e" * 40,
                "scan_mode": "production",
                "scan_scope": "full",
                "run_finished_at": "2026-08-12T10:00:00+00:00",
            },
            "backtest_release_status": "ready",
            "backtest_release_contract": {
                "backtest_release": "e2e-backtest",
                "publication_state": "ready",
                "publish_eligible": True,
                "strategy_registry": [
                    {"strategy_id": strategy, "strategy_version": "e2e", "data_version": "e2e"}
                    for strategy in ("momentum", "price_action", "resonance", "value")
                ],
            },
            # Keep the offline fixture representative of the strict
            # production contract: every market/strategy row must be present
            # and independently complete.  A single aggregate row would
            # otherwise pass the old gate while the Mini App had empty
            # strategy drawers.
            "sources": [
                {
                    "market": market,
                    "strategy": strategy,
                    "scan_state": "complete",
                    "candidate_state": "no_candidates",
                    "requested": 1,
                    "requested_records": 1,
                    "universe_scanned": 1,
                    "complete_records": 1,
                    "failed_records": 0,
                    "visible_candidates": 0,
                }
                for market, strategy in (
                    ("taiwan", "momentum"),
                    ("taiwan", "price_action"),
                    ("taiwan", "resonance"),
                    ("taiwan", "value"),
                    ("us", "momentum"),
                    ("us", "price_action"),
                    ("us", "resonance"),
                    ("us", "value"),
                )
            ],
        },
        "events": {"snapshot_id": "e2e-events", "events": []},
    }


def _mock_delivery_check(*, send: bool = False) -> dict[str, Any]:
    """Represent the Telegram boundary without reading production settings.

    Offline acceptance must never require a real bot token or recipient list.
    The production sender is still exercised by its own delivery tests; this
    boundary only proves that the release pipeline can reach a mocked receipt.
    """
    return {
        "ok": True,
        "mocked": True,
        "recipient_count": 1,
        "errors": [],
        "sent": bool(send),
    }


def run_offline_e2e(
    *,
    dry_run: Callable[[], dict[str, Any]] = run_dry_run,
    delivery_check: Callable[..., dict[str, Any]] = _mock_delivery_check,
) -> dict[str, Any]:
    """Run deterministic gates and return a non-secret audit report."""
    bundle = _ready_bundle()
    release = validate_production_bundle(**bundle, require_production_research=True)
    telegram = delivery_check(send=False)
    pipeline = dry_run()
    financialjuice_lane = _financialjuice_offline_lane()
    creator_morning_lane = _creator_morning_offline_lane()
    creator_notification_lane = run_creator_notification_e2e()
    creator_delivery = decide_creator_delivery(
        {
            "episode_key": "production-e2e-creator-episode",
            "notification_type": "initial",
            "public_safe": True,
        },
        release_ready=release.allowed,
        media_available=pipeline.get("renderer_available") is True,
    )
    creator_result = build_creator_intelligence_release(
        [{
            "content_origin": "haojiao",
            "episode_key": "production-e2e-creator-release",
            "episode_title": "Public creator observation",
            "claims": ["A public claim"],
            "verification_state": "unverified",
            "public_safe": True,
        }],
        parent_manifest={
            "release_id": bundle["manifest"]["release_id"],
            "market_snapshot_id": bundle["manifest"]["market_snapshot_id"],
            "event_snapshot_id": bundle["manifest"]["event_snapshot_id"],
        },
    )
    creator_release = creator_result["artifact"]
    checks = {
        "release_contract": release.allowed,
        "telegram_configuration": telegram.get("ok") is True,
        "offline_pipeline": pipeline.get("ok") is True
        and pipeline.get("renderer_available") is True
        and pipeline.get("photo_contract", {}).get("delivery_status") != "blocked",
        "photo_contract": pipeline.get("photo_contract", {}).get("dimensions_valid") is True
        and pipeline.get("photo_contract", {}).get("deep_link_valid") is True
        and bool(pipeline.get("photo_contract", {}).get("observation_id")),
        "creator_delivery_contract": creator_delivery["allowed"] is True,
        "creator_release_contract": creator_release["status"] == "ready"
        and creator_release["parent_release_id"] == bundle["manifest"]["release_id"],
        "financialjuice_compound_lane": financialjuice_lane["ok"] is True,
        "creator_morning_batch_lane": creator_morning_lane["ok"] is True,
        "creator_notification_e2e": creator_notification_lane["ok"] is True,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "release_errors": list(release.errors),
        "telegram": {
            "ok": telegram.get("ok") is True,
            "mocked": telegram.get("mocked") is True,
            "recipient_count": telegram.get("recipient_count", 0),
            "errors": telegram.get("errors", []),
        },
        "pipeline": {
            "ok": pipeline.get("ok") is True,
            "renderer_available": pipeline.get("renderer_available", False),
            "card_dimensions": pipeline.get("card_dimensions", {}),
            "delivery_status": pipeline.get("photo_contract", {}).get("delivery_status"),
        },
        "creator_delivery": creator_delivery,
        "creator_release": {
            "status": creator_release["status"],
            "release_id": creator_release["release_id"],
            "parent_release_id": creator_release["parent_release_id"],
            "insight_count": len(creator_release.get("insights") or []),
        },
        "financialjuice_lane": financialjuice_lane,
        "creator_morning_batch": creator_morning_lane,
        "creator_notification_e2e": creator_notification_lane,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    report = run_offline_e2e()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
