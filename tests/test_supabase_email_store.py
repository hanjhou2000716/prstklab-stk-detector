from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.append(str(Path(__file__).parents[1] / "railway-monitor"))

from supabase_email_store import SupabaseEmailStore  # noqa: E402


class _Response:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload


def test_cursor_round_trip_uses_singleton_and_hides_key(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []

    def request(method: str, url: str, **kwargs: Any) -> _Response:
        calls.append({"method": method, "url": url, "kwargs": kwargs})
        if method == "GET":
            return _Response(200, current)
        current[:] = [dict(kwargs["json"])]
        return _Response(201, current)

    monkeypatch.setattr("supabase_email_store.requests.request", request)
    store = SupabaseEmailStore("https://example.supabase.co", "service-role-secret")
    assert store.cursor()["last_history_id"] is None
    saved = store.save_cursor(last_history_id="123", pending_history_id="124")
    assert saved["last_history_id"] == "123"
    assert saved["pending_history_id"] == "124"
    assert calls[0]["url"].endswith("gmail_watch_state?id=eq.primary&select=*&limit=1")
    # The key is necessarily sent in the Authorization header; the adapter's
    # public return values and error classes never include it.
    assert "service-role-secret" not in repr(saved)


def test_public_projection_rejects_private_mail_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("supabase_email_store.requests.request", lambda *_args, **_kwargs: _Response(201, [{"ok": True}]))
    store = SupabaseEmailStore("https://example.supabase.co", "key")
    with pytest.raises(ValueError, match="private"):
        store.save_public_observation({
            "observation_id": "obs-1",
            "source": "creator",
            "public_safe": True,
            "body": "must never persist",
        })


def test_public_projection_keeps_creator_fields_but_strips_transport_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []

    def request(method: str, url: str, **kwargs: Any) -> _Response:
        captured.append(kwargs.get("json") or {})
        return _Response(201, [{"observation_id": "jenny:abc"}])

    monkeypatch.setattr("supabase_email_store.requests.request", request)
    store = SupabaseEmailStore("https://example.supabase.co", "key")
    assert store.save_public_observation({
        "observation_id": "jenny:abc",
        "content_origin": "jenny",
        "episode_key": "jenny:abc",
        "episode_title": "今日市場觀察",
        "public_safe": True,
    }) is True
    payload = captured[0]["payload_json"]
    assert payload["episode_title"] == "今日市場觀察"
    with pytest.raises(ValueError, match="private"):
        store.save_public_observation({
            "observation_id": "jenny:def",
            "content_origin": "jenny",
            "episode_key": "jenny:def",
            "source_message_id": "gmail-private-id",
            "public_safe": True,
        })
    assert "gmail_message_id" not in payload


def test_store_requires_https_and_credentials() -> None:
    with pytest.raises(ValueError, match="not_configured"):
        SupabaseEmailStore("", "")
    with pytest.raises(ValueError, match="https"):
        SupabaseEmailStore("http://example.supabase.co", "key")
