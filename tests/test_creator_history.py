import pytest

from src.creator_history import CreatorHistoryStore


def _insight(key: str, *, creator: str = "gooaye") -> dict:
    return {"episode_key": key, "creator_id": creator, "content_origin": creator, "public_safe": True, "claims": [], "opinions": []}


def test_history_is_append_only_and_deduplicates_identical_snapshot(tmp_path):
    store = CreatorHistoryStore(tmp_path / "creator.sqlite3")
    first = store.append(_insight("ep-1"), recorded_at="2026-08-01T00:00:00+00:00")
    second = store.append(_insight("ep-1"), recorded_at="2026-08-02T00:00:00+00:00")
    assert first == second
    assert len(store.list_recent()) == 1


def test_history_rejects_private_content(tmp_path):
    store = CreatorHistoryStore(tmp_path / "creator.sqlite3")
    with pytest.raises(ValueError, match="private"):
        store.append({**_insight("ep-1"), "raw_body": "secret"})


def test_history_prune_keeps_latest_episode_snapshot(tmp_path):
    store = CreatorHistoryStore(tmp_path / "creator.sqlite3")
    store.append({**_insight("ep-1"), "opinions": ["old"]}, recorded_at="2026-01-01T00:00:00+00:00")
    store.append({**_insight("ep-1"), "opinions": ["latest"]}, recorded_at="2026-08-01T00:00:00+00:00")
    assert store.prune(now="2026-08-13T00:00:00+00:00", retention_days=30) == 1
    assert store.list_recent()[0]["opinions"] == ["latest"]
