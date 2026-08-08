from src.deep_link_router import parse_deep_link, resolve_deep_link

def test_deep_link_routes_exact_release_and_alert():
    link = parse_deep_link("https://example.test/app?alert=a1&release=r1&view=event")
    result = resolve_deep_link(link, manifest={"release_id": "r1"}, alerts=[{"alert_id": "a1", "title": "事件"}])
    assert result["status"] == "ok"

def test_deep_link_fails_closed_on_release_mismatch():
    link = parse_deep_link("https://example.test/app?alert=a1&release=old&view=event")
    assert resolve_deep_link(link, manifest={"release_id": "new"}, alerts=[])["status"] == "archived"
