from src.creator_media import validate_creator_media
from src.creator_media_provenance import bind_creator_media


def _png():
    return b"\x89PNG\r\n\x1a\n" + b"payload"


def test_valid_media_binding_is_deterministic_and_private_safe():
    media = validate_creator_media({"filename": "summary.png", "mime_type": "image/png", "data": _png()})
    first = bind_creator_media(observation_id="obs-1", episode_key="jenny:2026-08-24", media_record=media)
    second = bind_creator_media(observation_id="obs-1", episode_key="jenny:2026-08-24", media_record=media)
    assert first == second
    assert first["media_mode"] == "photo"
    assert first["binding_status"] == "bound"
    assert "data" not in str(first)
    assert "filename" not in first["media"]


def test_invalid_media_degrades_to_text_only():
    media = validate_creator_media({"filename": "summary.png", "mime_type": "image/png", "data": b"not-image"})
    result = bind_creator_media(observation_id="obs-1", episode_key="jenny:episode", media_record=media)
    assert result["media_mode"] == "text_only"
    assert result["binding_status"] == "degraded"
    assert result["media"]["availability"] == "unavailable"
