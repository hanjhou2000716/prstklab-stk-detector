import hashlib

from src.financialjuice_priority import project_financialjuice_priority


def _row(importance=8):
    return {
        "observation_id": "fj-observation-1",
        "item_id": "fj-item-1",
        "source": "financialjuice",
        "original_headline": "Oil supply risk",
        "event_type": "energy",
        "importance": importance,
        "source_url": "https://financialjuice.com/item/1",
        "published_at": "2026-08-21T01:00:00Z",
        "received_at": "2026-08-21T01:01:00Z",
        "parser_version": "financialjuice-compound-v1",
        "public_safe": True,
    }


def test_qualifying_fj_item_becomes_release_bound_vendor_priority_event():
    projection = project_financialjuice_priority([_row(8)])
    assert projection["decisions"][0]["notification_status"] == "eligible"
    event = projection["events"][0]
    assert event["vendor_priority_notification"] is True
    assert event["risk_level"] == "R2"
    assert event["prstk_risk_level"] == "R2"
    assert event["market_direction"] is None
    assert event["source_trace"]["vendor_importance_is_not_risk"] is True
    assert event["received_at"] == "2026-08-21T01:01:00Z"
    assert event["parser_version"] == "financialjuice-compound-v1"
    assert event["observation_id_hash"] == hashlib.sha256(b"fj-observation-1").hexdigest()
    assert event["source_trace"]["observation_id_hash"] == event["observation_id_hash"]
    assert "fj-observation-1" not in event["source_trace"]["observation_id_hash"]


def test_fj_below_threshold_is_visible_but_not_eligible():
    projection = project_financialjuice_priority([_row(7)])
    assert projection["decisions"][0]["notification_status"] == "not_eligible"
    assert projection["events"][0]["alert_eligible"] is False


def test_fj_same_cluster_is_not_sent_twice():
    projection = project_financialjuice_priority([_row(8)], existing_events=[{"event_cluster_key": ""}])
    # Without a cluster key, this is a new auditable item; the absence of a
    # key must not silently suppress a qualifying notification.
    assert projection["decisions"][0]["notification_status"] == "eligible"

    row = _row(8)
    row["event_cluster_key"] = "cluster-1"
    projection = project_financialjuice_priority([row], existing_events=[{"event_cluster_key": "cluster-1"}])
    assert projection["decisions"][0]["notification_status"] == "already_cluster_notified"
    assert "already_cluster_notified" in projection["decisions"][0]["notification_reason"]
