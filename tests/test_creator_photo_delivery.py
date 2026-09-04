from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.creator_photo_delivery import (
    build_creator_receipt,
    creator_caption,
    plan_creator_delivery,
)

INSIGHT = {
    "creator_id": "gooaye",
    "creator_name": "股癌",
    "content_origin": "gooaye",
    "episode_key": "gooaye:ep-7",
    "episode_title": "市場與半導體觀察",
    "key_takeaways": ["觀察供應鏈變化", "等待官方數據核對", "不構成投資建議"],
    "tickers": ["NVDA", "2330"],
    "public_safe": True,
}


def test_caption_is_bounded_and_attributed() -> None:
    caption = creator_caption({**INSIGHT, "episode_title": "標題 " * 200})
    assert len(caption) <= 240
    assert caption.startswith("股癌｜")


def test_plan_uses_text_only_when_private_media_is_missing(monkeypatch) -> None:
    monkeypatch.setattr("src.creator_delivery_contract.is_active_creator", lambda _creator: True)
    plan = plan_creator_delivery(
        INSIGHT,
        release_id="release-1",
        creator_snapshot_id="creator-1",
        mini_app_url="https://example.test/app",
        release_ready=True,
        media_available=False,
    )
    assert plan["allowed"] is True
    assert plan["media_mode"] == "text_only"
    assert plan["status"] == "media_degraded"
    assert "view=creator" in plan["mini_app_url"]
    assert "episode=gooaye%3Aep-7" in plan["mini_app_url"]


def test_plan_is_blocked_before_release() -> None:
    plan = plan_creator_delivery(
        INSIGHT,
        release_id="release-1",
        creator_snapshot_id="creator-1",
        mini_app_url="https://example.test/app",
        release_ready=False,
        media_available=True,
    )
    assert plan["allowed"] is False
    assert "release_gate_not_ready" in plan["reasons"]


def test_receipt_hashes_recipient_and_keeps_lineage() -> None:
    receipt = build_creator_receipt(
        INSIGHT,
        release_id="release-1",
        creator_snapshot_id="creator-1",
        chat_id="8869592162",
        status="delivered",
        message_id=12,
        media_hash="a" * 64,
    )
    assert receipt["creator_episode_key"] == "gooaye:ep-7"
    assert receipt["release_id"] == "release-1"
    assert receipt["recipient_hash"] == "7a30574fc065a0a7"
    assert "chat_id" not in receipt


def test_receipt_schema_rejects_raw_recipient(tmp_path: Path) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((Path(__file__).parents[1] / "schemas" / "creator-delivery-receipt.schema.json").read_text(encoding="utf-8"))
    receipt = build_creator_receipt(
        INSIGHT,
        release_id="release-1",
        creator_snapshot_id="creator-1",
        chat_id="8869592162",
        status="media_degraded",
        media_mode="text_only",
    )
    jsonschema.validate(receipt, schema)
    receipt["chat_id"] = "8869592162"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(receipt, schema)
