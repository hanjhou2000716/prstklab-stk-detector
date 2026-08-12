from src.creator_media import creator_media_summary, validate_creator_media


def test_valid_png_is_private_and_hash_addressed():
    value = validate_creator_media({"filename": "summary.png", "mime_type": "image/png", "data": b"\x89PNG\r\n\x1a\ncontent"})
    assert value["availability"] == "private_ready"
    assert value["storage_scope"] == "private"
    assert len(value["sha256"]) == 64
    assert "data" not in value


def test_path_traversal_and_magic_mismatch_fail_closed():
    value = validate_creator_media({"filename": "../secret.png", "mime_type": "image/png", "data": b"not-png"})
    assert value["availability"] == "unavailable"
    assert {"unsafe_filename", "magic_mismatch"}.issubset(value["validation_errors"])
    assert value["storage_scope"] == "rejected"


def test_public_summary_never_contains_private_path_or_url():
    value = creator_media_summary({"media_id": "media-1", "mime_type": "image/png", "byte_size": 4, "sha256": "a" * 64, "availability": "private_ready", "local_path": "C:/secret.png", "url": "https://private.invalid/file"})
    assert value["storage_scope"] == "private"
    assert "local_path" not in value
    assert "url" not in value
