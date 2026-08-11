from src.deep_link_router import parse_deep_link, resolve_deep_link


def test_deep_link_routes_exact_release_and_alert():
    link = parse_deep_link("https://example.test/app?alert=a1&release=r1&view=event")
    result = resolve_deep_link(link, manifest={"release_id": "r1"}, alerts=[{"alert_id": "a1", "title": "事件"}])
    assert result["status"] == "ok"

def test_deep_link_fails_closed_on_release_mismatch():
    link = parse_deep_link("https://example.test/app?alert=a1&release=old&view=event")
    assert resolve_deep_link(link, manifest={"release_id": "new"}, alerts=[])["status"] == "archived"


def test_deep_link_preserves_snapshot_and_observation_identity():
    link = parse_deep_link(
        "https://example.test/app?alert=a1&release=r1&snapshot=s1&observation=o1&view=event"
    )
    result = resolve_deep_link(
        link,
        manifest={"release_id": "r1", "market_snapshot_id": "s1"},
        alerts=[{"alert_id": "a1", "snapshot_id": "s1"}],
    )
    assert result["status"] == "ok"
    assert result["snapshot_id"] == "s1"
    assert result["observation_id"] == "o1"


def test_deep_link_fails_closed_on_snapshot_mismatch():
    link = parse_deep_link("https://example.test/app?alert=a1&release=r1&snapshot=old")
    result = resolve_deep_link(
        link,
        manifest={"release_id": "r1", "market_snapshot_id": "new"},
        alerts=[{"alert_id": "a1", "snapshot_id": "new"}],
    )
    assert result["status"] == "archived"
