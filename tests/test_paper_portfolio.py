import pytest

from src.paper_portfolio import record_paper_entry, update_paper_entry


def test_paper_entry_preserves_public_snapshot_and_missing_price():
    entry = record_paper_entry(
        {"ticker": "2330", "name": "TSMC", "strategy": "momentum", "advice_gate": "observation_only"},
        release_id="release-1",
        snapshot_id="snapshot-1",
        price=None,
    )
    assert entry["paper_only"] is True
    assert entry["observed_price"] is None
    assert entry["simulated_returns"] == {"5": None, "20": None, "60": None}
    assert entry["status"] == "open"


def test_paper_update_never_fabricates_return_without_fill_price():
    entry = record_paper_entry({"ticker": "AAPL"}, release_id="r", snapshot_id="s", price=None, horizons=(5,))
    updated = update_paper_entry(entry, price=100, horizon_days=5, final=True)
    assert updated["simulated_returns"]["5"] is None
    assert updated["status"] == "closed"


def test_paper_update_records_return_and_invalidation():
    entry = record_paper_entry({"ticker": "2330"}, release_id="r", snapshot_id="s", price=100, horizons=(5,))
    updated = update_paper_entry(entry, price=105, horizon_days=5, invalidated=True)
    assert updated["simulated_returns"]["5"] == 0.05
    assert updated["status"] == "invalidated"


def test_paper_entry_rejects_missing_identity():
    with pytest.raises(ValueError):
        record_paper_entry({}, release_id="r", snapshot_id="s")
