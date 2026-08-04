from datetime import UTC, datetime

import pytest

from src.point_in_time import audit_fundamental_snapshots, latest_fundamental_snapshot, normalize_corporate_action, snapshot_is_usable


DECISION = datetime(2021, 6, 30, tzinfo=UTC)


def base(**overrides):
    value = {"market": "us", "ticker": "AAA", "as_of": "2020-12-31", "published_at": "2021-02-01T00:00:00Z", "point_in_time": True}
    value.update(overrides)
    return value


def test_future_published_snapshot_is_rejected():
    ok, reason = snapshot_is_usable(base(published_at="2021-07-01T00:00:00Z"), DECISION)
    assert ok is False
    assert "published" in reason


def test_latest_snapshot_uses_prior_public_snapshot():
    snapshots = [base(as_of="2019-12-31", published_at="2020-02-01T00:00:00Z"), base(as_of="2020-12-31", published_at="2021-02-01T00:00:00Z")]
    assert latest_fundamental_snapshot(snapshots, market="us", ticker="AAA", decision_time=DECISION)["as_of"] == "2020-12-31"


def test_audit_separates_future_data_gap():
    audit = audit_fundamental_snapshots([base(), base(ticker="BBB", published_at="2022-01-01T00:00:00Z")], market="us", decision_time=DECISION)
    assert audit["usable"] == 1
    assert audit["blocked"] == 1
    assert audit["status"] == "partial"


def test_corporate_action_normalization_preserves_provenance():
    action = normalize_corporate_action({"ticker": "AAA", "action_type": "stock_split", "action_date": "2021-05-01", "source_url": "https://example.test/action"})
    assert action["point_in_time"] is True
    assert action["action_type"] == "stock_split"
    assert action["source_url"]


def test_unknown_corporate_action_fails_closed():
    with pytest.raises(ValueError):
        normalize_corporate_action({"action_type": "rumor", "action_date": "2021-05-01"})