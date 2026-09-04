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


def _fj_alert(*, event="伊朗通信基礎設施事件。", snapshot_id="s1", observation_id="o1"):
    return {
        "notification_id": "fj-notification-1",
        "source_key": "financialjuice",
        "snapshot_id": snapshot_id,
        "observation_id": observation_id,
        "public_short_message": "🟣 FJ 10/10｜" + event,
        "event": event,
    }


def test_deep_link_resolves_latest_release_for_same_event():
    link = parse_deep_link(
        "https://example.test/app?alert=fj-notification-1&release=old&snapshot=s1&observation=o1"
    )
    historical = _fj_alert()
    latest = {**historical, "release_id": "new"}
    result = resolve_deep_link(
        link,
        manifest={"release_id": "new", "market_snapshot_id": "s1"},
        alerts=[latest],
        latest_alerts=[latest],
        historical_alerts=[historical],
    )
    assert result["status"] == "ok"
    assert result["resolution"] == "latest_same_event"
    assert result["alert"] == latest
    assert result["original_release_id"] == "old"


def test_deep_link_keeps_historical_alert_when_content_changes():
    link = parse_deep_link(
        "https://example.test/app?alert=fj-notification-1&release=old&snapshot=s1&observation=o1"
    )
    historical = _fj_alert()
    latest = {**_fj_alert(event="伊朗新增通信攻擊事件。"), "release_id": "new"}
    result = resolve_deep_link(
        link,
        manifest={"release_id": "new", "market_snapshot_id": "s1"},
        alerts=[latest],
        latest_alerts=[latest],
        historical_alerts=[historical],
    )
    assert result["status"] == "archived"
    assert result["resolution"] == "historical_exact"
    assert result["alert"] == historical


def test_deep_link_does_not_remap_without_verified_original_alert():
    link = parse_deep_link(
        "https://example.test/app?alert=fj-notification-1&release=old&snapshot=s1&observation=o1"
    )
    latest = _fj_alert()
    result = resolve_deep_link(
        link,
        manifest={"release_id": "new", "market_snapshot_id": "s1"},
        alerts=[],
        latest_alerts=[latest],
        historical_alerts=[],
    )
    assert result["status"] == "archived"
    assert "alert" not in result
