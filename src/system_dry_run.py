"""Offline end-to-end contract check for the release-to-delivery pipeline."""
from __future__ import annotations

import struct
import tempfile
from datetime import UTC, datetime
from typing import Any

from src.alert_budget import decide_alert_budget
from src.alert_caption import make_caption
from src.alert_card_renderer import HEIGHT, WIDTH, render_alert_card
from src.alert_contract import AlertEnvelope
from src.alert_lifecycle import transition
from src.deep_link_router import parse_deep_link, resolve_deep_link
from src.intelligence_pipeline import build_intelligence_context


def run_dry_run() -> dict[str, Any]:
    event = {"event_key": "dry-run-event", "event_cluster_key": "dry-run-event", "alert_type": "geopolitical_event", "title": "公開事件測試", "severity": "warning", "source_url": "https://example.test/source"}
    caption = make_caption(subject="市場事件", change="等待核對", state="觀察")
    envelope = AlertEnvelope.from_event(event, release_id="dry-release", snapshot_id="dry-snapshot", short_caption=caption)
    budget = decide_alert_budget(event, [], now=datetime.now(UTC))
    lifecycle = transition("observation", official_confirmed=False, second_source=False, market_sync=False)
    intelligence = build_intelligence_context(event, [])
    link = parse_deep_link("https://example.test/app?alert=dry-run-event&release=dry-release&view=event")
    routed = resolve_deep_link(link, manifest={"release_id": "dry-release"}, alerts=[envelope.to_dict()])
    with tempfile.TemporaryDirectory(prefix="prstk-dry-run-") as temporary:
        card_path = render_alert_card({"title": event["title"], "lifecycle_state": lifecycle, "trigger_reason": caption}, f"{temporary}/alert.png")
        png_header = card_path.read_bytes()[16:24] if card_path.exists() else b""
        card_dimensions = struct.unpack(">II", png_header) if len(png_header) == 8 else (0, 0)
    card_ok = card_dimensions == (WIDTH, HEIGHT)
    return {"ok": all((budget["allowed"], lifecycle == "pending_confirmation", intelligence["advice_gate"] == "observation_only", routed["status"] == "ok", card_ok)), "budget": budget, "lifecycle": lifecycle, "advice_gate": intelligence["advice_gate"], "deep_link": routed["status"], "release_id": envelope.release_id, "card_rendered": card_ok, "card_dimensions": {"width": card_dimensions[0], "height": card_dimensions[1]}}

if __name__ == "__main__":
    import json
    print(json.dumps(run_dry_run(), ensure_ascii=False, sort_keys=True))
