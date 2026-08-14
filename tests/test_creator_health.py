from src.creator_health import build_creator_health


def test_creator_health_distinguishes_no_content_from_failure():
    result = build_creator_health(
        config={"status": "healthy"}, watch={"status": "no_new_content"},
        parser={"status": "no_new_content"}, release={"status": "no_new_content"},
        media={"status": "no_new_content"}, delivery={"status": "no_new_content"},
    )
    assert result["creator_health"] == "no_new_content"
    assert result["secret_values_exposed"] is False


def test_creator_health_surfaces_parse_and_media_failures():
    parse = build_creator_health(config={"status": "healthy"}, parser={"status": "parse_failed"})
    media = build_creator_health(config={"status": "healthy"}, parser={"status": "healthy"}, media={"status": "media_degraded"})
    assert parse["creator_health"] == "parse_failed"
    assert media["creator_health"] == "media_degraded"


def test_creator_health_maps_legacy_no_event_to_no_new_content():
    result = build_creator_health(
        config={"status": "healthy"}, watch={"status": "no_event"},
        parser={"status": "no_event"}, release={"status": "no_event"},
        media={"status": "no_event"}, delivery={"status": "no_event"},
    )
    assert result["creator_health"] == "no_new_content"


def test_creator_health_filters_private_fields():
    result = build_creator_health(config={"status": "healthy", "token": "secret"}, watch={"status": "healthy", "last_history_id": "h1"})
    assert result["timeline"] == {"last_history_id": "h1"}
