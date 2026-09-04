"""Offline acceptance audit for the canonical intelligence integration.

This is deliberately a small, deterministic gate over the existing producers.
It proves that Creator, FinancialJuice and market-news artifacts are wired to
their public contracts without contacting Gmail, Railway, Pages or Telegram.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# When invoked as ``python scripts/verify_intelligence_contracts.py`` Python's
# import root is ``scripts``.  Add the repository root explicitly so the same
# command works locally and in Actions (pytest already runs from the root).
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.creator_intelligence_pipeline import build_creator_intelligence_release  # noqa: E402
from src.creator_media_provenance import bind_creator_media  # noqa: E402
from src.creator_provider_registry import creator_ids, creator_providers  # noqa: E402
from src.financialjuice_contract import build_financialjuice_envelope, normalize_financialjuice_item  # noqa: E402
from src.financialjuice_priority import project_financialjuice_priority  # noqa: E402
from src.news_intelligence import build_news_intelligence  # noqa: E402

AS_OF = datetime(2026, 8, 24, 3, 0, tzinfo=UTC)  # 11:00 Asia/Taipei
PARENT = {
    "release_id": "release-acceptance-fixture",
    "market_snapshot_id": "market-acceptance-fixture",
    "research_snapshot_id": "research-acceptance-fixture",
    "event_snapshot_id": "event-acceptance-fixture",
}


def _creator_record(creator_id: str, episode_key: str) -> dict[str, Any]:
    return {
        "creator_id": creator_id,
        "content_origin": creator_id,
        "episode_key": episode_key,
        "episode_title": f"{creator_id} morning fixture",
        "published_at": "2026-08-24T02:00:00Z",
        "received_at": "2026-08-24T02:01:00Z",
        "parse_status": "parsed",
        "source_adapter": "acceptance-fixture",
        "required_fields_present": True,
        "public_safe": True,
        "topics": ["semiconductor"],
    }


def run_audit() -> dict[str, Any]:
    checks: dict[str, bool] = {}
    providers = {item.creator_id: item for item in creator_providers(enabled_only=True)}
    inventory = {item.creator_id: item for item in creator_providers()}
    checks["creator_registry_canonical"] = {
        "haojiao", "jenny", "gooaye",
    } == set(inventory) and not providers and creator_ids(enabled_only=True) == ()
    checks["morning_lane_requires_two"] = (
        not providers
        and {item.creator_id for item in inventory.values() if item.morning_required}
        == {"haojiao", "jenny"}
        and inventory["gooaye"].morning_required is False
    )

    creator = build_creator_intelligence_release(
        [_creator_record("haojiao", "h-acceptance"), _creator_record("jenny", "j-acceptance"),
         _creator_record("unknown", "u-dropped")],
        parent_manifest=PARENT,
        market_snapshot={"generated_at": AS_OF.isoformat(), "snapshot_id": PARENT["market_snapshot_id"]},
        research_snapshot={"snapshot_id": PARENT["research_snapshot_id"]},
        event_snapshot={"snapshot_id": PARENT["event_snapshot_id"]},
        batch_as_of=AS_OF,
    )
    artifact = creator["artifact"]
    checks["creator_release_lineage"] = (
        artifact.get("status") == "ready"
        and artifact.get("parent_release_id") == PARENT["release_id"]
        and creator["accepted_count"] == 0
        and creator["dropped_count"] == 3
        and artifact.get("morning_batch", {}).get("state") == "no_new_content"
        and artifact.get("morning_batch", {}).get("expected_count") == 0
    )
    checks["creator_media_fail_closed"] = bind_creator_media(
        observation_id="obs-acceptance", episode_key="h-acceptance", media_record={}
    ).get("media_mode") == "text_only"

    fj_item = normalize_financialjuice_item(
        {
            "original_headline": "Oil supply watch",
            "event_type": "energy",
            "importance": 8,
            "source_url": "https://financialjuice.com/item/acceptance",
            "published_at": "2026-08-24T02:00:00Z",
            "fetched_at": "2026-08-24T02:01:00Z",
            "public_safe": True,
        },
        message_id="fj-message-acceptance",
        index=0,
    )
    envelope = build_financialjuice_envelope([fj_item], message_id="fj-message-acceptance")
    projection = project_financialjuice_priority([dict(fj_item, source="financialjuice")])
    decision = projection["decisions"][0] if projection["decisions"] else {}
    checks["financialjuice_compound_item_and_priority"] = (
        envelope.to_dict().get("item_count") == 1
        and bool(fj_item.get("item_id"))
        and decision.get("notification_status") == "eligible"
        and projection["events"][0].get("source_trace", {}).get("vendor_importance_is_not_risk") is True
        and projection["events"][0].get("market_direction") is None
    )

    taiwan_news = build_news_intelligence(
        [{"title": "Fed policy update", "url": "https://www.federalreserve.gov/feeds/press_all.xml"}],
        market="taiwan",
    )
    us_news = build_news_intelligence(
        [{"title": "NVIDIA outlook", "url": "https://www.sec.gov/Archives/edgar/data/acceptance/8-k"}],
        market="us",
    )
    checks["news_market_separation"] = (
        taiwan_news["status"] == "no_event"
        and taiwan_news["excluded_count"] == 1
        and us_news["status"] == "ready"
        and us_news["stories"][0]["market_compatible"] is True
    )
    checks["news_provider_registry_and_public_url"] = bool(
        us_news.get("provider_registry")
        and us_news["stories"][0].get("public_safe") is True
        and us_news["stories"][0].get("canonical_url", "").startswith("https://")
    )
    return {
        "status": "pass" if all(checks.values()) else "fail",
        "offline": True,
        "as_of": AS_OF.isoformat(),
        "checks": checks,
        "evidence": {
            "creator_release_id": artifact.get("release_id"),
            "creator_parent_release_id": artifact.get("parent_release_id"),
            "financialjuice_item_id": fj_item.get("item_id"),
            "financialjuice_notification_status": decision.get("notification_status"),
            "taiwan_news_status": taiwan_news.get("status"),
            "us_news_status": us_news.get("status"),
        },
        "external_acceptance_required": ["Gmail", "Railway", "Pages", "Telegram"],
    }


def main() -> int:
    result = run_audit()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
