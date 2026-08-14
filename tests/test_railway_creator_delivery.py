from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE = Path(__file__).parents[1] / "railway-monitor" / "creator_delivery.py"
SPEC = importlib.util.spec_from_file_location("railway_creator_delivery_test", MODULE)
assert SPEC and SPEC.loader
creator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(creator)


def test_creator_projection_filters_categories_deduplicates_and_bounds_keys():
    history = [
        {"category": "market_risk", "notification_keys": ["ignore"]},
        {"category": "creator_receipt", "notification_keys": ["alpha", "alpha", "beta"]},
        {"category": "creator_receipt", "notification_keys": ["gamma"]},
    ]
    assert creator.notification_keys(history, limit=2) == ["alpha", "beta"]


def test_creator_projection_does_not_echo_non_string_values():
    assert creator.notification_keys(
        [{"category": "creator_receipt", "notification_keys": [None, 12, "ok"]}]
    ) == ["ok"]
