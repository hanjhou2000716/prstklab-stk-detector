from __future__ import annotations

from typing import Any

import pytest

from src.telegram_subscriptions import (
    TelegramSubscriptionError,
    fetch_active_chat_ids,
    migrate_legacy_chat_ids,
)


class _Response:
    def __init__(self, status_code: int = 200, payload: Any = None) -> None:
        self.status_code = status_code
        self.ok = status_code < 400
        self._payload = payload if payload is not None else []

    def json(self) -> Any:
        return self._payload


def test_fetch_active_chat_ids_returns_only_validated_deduplicated_ids() -> None:
    captured: dict[str, Any] = {}

    def get(url: str, **kwargs: Any) -> _Response:
        captured.update(url=url, kwargs=kwargs)
        return _Response(payload=[{"chat_id": "100"}, {"chat_id": "100"}, {"chat_id": "-200"}])

    assert fetch_active_chat_ids("https://example.supabase.co", "key", request_get=get) == ("100", "-200")
    assert captured["kwargs"]["params"]["status"] == "eq.active"
    assert captured["kwargs"]["params"]["chat_type"] == "eq.private"
    assert "key" in captured["kwargs"]["headers"]["Authorization"]


def test_fetch_active_chat_ids_rejects_malformed_chat_id() -> None:
    with pytest.raises(TelegramSubscriptionError, match="invalid_chat_id"):
        fetch_active_chat_ids(
            "https://example.supabase.co", "key",
            request_get=lambda *_args, **_kwargs: _Response(payload=[{"chat_id": "user@example.com"}]),
        )


def test_migration_is_idempotent_and_includes_fixed_editor_without_sending() -> None:
    captured: dict[str, Any] = {}

    def post(url: str, **kwargs: Any) -> _Response:
        captured.update(url=url, kwargs=kwargs)
        return _Response(payload=[{"chat_id": "100"}, {"chat_id": "8869592162"}])

    assert migrate_legacy_chat_ids(
        ("100", "100", "not-an-id"),
        url="https://example.supabase.co",
        key="key",
        request_post=post,
    ) == 2
    assert captured["kwargs"]["headers"]["Prefer"].startswith("resolution=ignore-duplicates")
    rows = captured["kwargs"]["json"]
    assert [row["chat_id"] for row in rows] == ["100", "8869592162"]
    assert rows[-1]["is_editor"] is True


def test_store_requires_https_and_credentials() -> None:
    with pytest.raises(TelegramSubscriptionError, match="not_configured"):
        fetch_active_chat_ids("", "")
