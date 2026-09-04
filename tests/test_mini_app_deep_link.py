from pathlib import Path

APP = Path("site/app.js").read_text(encoding="utf-8")


def test_mini_app_resolves_deep_link_only_with_matching_release():
    assert "new URLSearchParams(window.location.search)" in APP
    assert "requestedRelease !== manifestRelease" in APP
    assert "該訊息版本已歸檔或不可用" in APP
    assert "latest_same_event" in APP or "最新同事件版本" in APP


def test_mini_app_does_not_replace_unknown_alert_with_current_event():
    assert "找不到此 alert 的同一 release 證據" in APP
    assert "renderAlertCard({ items: [event] }" in APP
    assert "applyDeepLink(snapshot)" in APP


def test_mini_app_accepts_canonical_delivery_event_identities():
    assert "item.event_cluster_key" in APP
    assert "item.notification_id" in APP
    assert "item.story_id" in APP


def test_mini_app_verifies_snapshot_and_observation_identity():
    assert 'params.get("snapshot")' in APP
    assert 'params.get("observation")' in APP
    assert "knownSnapshots.includes(requestedSnapshot)" in APP
    assert "event.observation_id" in APP
    assert "canonical_content_hash" in APP
    assert 'requestedAlert,\n            manifestRelease,\n            "",\n            "",' in APP
