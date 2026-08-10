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

from src.delivery_smoke_test import run_smoke_test
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
            "sources": [
                {
                    "scan_state": "complete",
                    "requested_records": 1,
                    "complete_records": 1,
                    "failed_records": 0,
                }
            ],
        },
        "events": {"snapshot_id": "e2e-events", "events": []},
    }


def run_offline_e2e(
    *,
    dry_run: Callable[[], dict[str, Any]] = run_dry_run,
    delivery_check: Callable[..., dict[str, Any]] = run_smoke_test,
) -> dict[str, Any]:
    """Run deterministic gates and return a non-secret audit report."""
    bundle = _ready_bundle()
    release = validate_production_bundle(**bundle, require_production_research=True)
    telegram = delivery_check(send=False)
    pipeline = dry_run()
    checks = {
        "release_contract": release.allowed,
        "telegram_configuration": telegram.get("ok") is True,
        "offline_pipeline": pipeline.get("ok") is True
        and pipeline.get("renderer_available") is True
        and pipeline.get("photo_contract", {}).get("delivery_status") != "blocked",
        "photo_contract": pipeline.get("photo_contract", {}).get("dimensions_valid") is True
        and pipeline.get("photo_contract", {}).get("deep_link_valid") is True,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "release_errors": list(release.errors),
        "telegram": {
            "ok": telegram.get("ok") is True,
            "recipient_count": telegram.get("recipient_count", 0),
            "errors": telegram.get("errors", []),
        },
        "pipeline": {
            "ok": pipeline.get("ok") is True,
            "renderer_available": pipeline.get("renderer_available", False),
            "card_dimensions": pipeline.get("card_dimensions", {}),
            "delivery_status": pipeline.get("photo_contract", {}).get("delivery_status"),
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
