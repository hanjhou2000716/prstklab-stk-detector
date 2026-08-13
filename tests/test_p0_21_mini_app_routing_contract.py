"""P0-21 Mini App release and deep-link safety contract tests."""

from src.deep_link_router import parse_deep_link, resolve_deep_link


def test_p0_21_release_mismatch_is_archived_without_cross_release_data() -> None:
    link = parse_deep_link("https://example.test/app?alert=old&release=old-release&view=event")
    result = resolve_deep_link(link, manifest={"release_id": "current-release"}, alerts=[{"alert_id": "old"}])
    assert result["status"] == "archived"
    assert "alert" not in result


def test_p0_21_unknown_alert_does_not_fall_through_to_latest_event() -> None:
    link = parse_deep_link("https://example.test/app?alert=missing&release=r1&view=market")
    result = resolve_deep_link(link, manifest={"release_id": "r1"}, alerts=[{"alert_id": "other"}])
    assert result["status"] == "missing"
    assert result["view"] == "market"
    assert "alert" not in result


def test_p0_21_snapshot_and_observation_lineage_must_remain_exact() -> None:
    link = parse_deep_link("https://example.test/app?alert=a1&release=r1&snapshot=s1&observation=o1")
    result = resolve_deep_link(
        link,
        manifest={"release_id": "r1", "market_snapshot_id": "s1"},
        alerts=[{"alert_id": "a1", "snapshot_id": "s1"}],
    )
    assert result["status"] == "ok"
    assert result["snapshot_id"] == "s1"
    assert result["observation_id"] == "o1"
