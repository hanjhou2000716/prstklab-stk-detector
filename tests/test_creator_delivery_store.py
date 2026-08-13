from __future__ import annotations

import json

from src.creator_delivery_store import append_creator_delivery_receipts, load_creator_delivery_history


def test_receipt_store_is_private_bounded_and_restart_safe(tmp_path):
    path = tmp_path / "private" / "creator-receipts.json"
    rows = [{"notification_key": f"creator:e-{index}:initial", "delivery_status": "delivered"} for index in range(4)]
    assert append_creator_delivery_receipts(path, rows) is True
    assert load_creator_delivery_history(path) == rows
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 1


def test_receipt_store_rejects_public_site_path(tmp_path, monkeypatch):
    site = tmp_path / "site"
    site.mkdir()
    monkeypatch.chdir(tmp_path)
    assert append_creator_delivery_receipts(site / "receipts.json", [{"x": 1}]) is False
