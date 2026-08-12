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
from src.production_acceptance import validate_production_bundle
from src.system_dry_run import run_dry_run


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
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    report = run_offline_e2e()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
