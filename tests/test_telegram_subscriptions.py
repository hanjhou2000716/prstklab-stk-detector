from __future__ import annotations

from typing import Any

import pytest

from src.telegram_subscriptions import (
    TelegramSubscriptionError,
    check_subscription_store,
    fetch_active_chat_ids,
    migrate_legacy_chat_ids,
    migrate_legacy_chat_ids_result,
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
        request_get=lambda *_args, **_kwargs: _Response(payload=[]),
        request_post=post,
    ) == 2
    assert captured["kwargs"]["headers"]["Prefer"].startswith("resolution=ignore-duplicates")
    rows = captured["kwargs"]["json"]
    assert [row["chat_id"] for row in rows] == ["100", "8869592162"]
    assert rows[-1]["is_editor"] is True


def test_missing_subscription_table_is_safe_prerequisite_block_without_post() -> None:
    post_calls: list[object] = []

    def post(*args: Any, **kwargs: Any) -> _Response:
        post_calls.append((args, kwargs))
        return _Response(payload=[])

    result = migrate_legacy_chat_ids_result(
        ("100",),
        url="https://example.supabase.co",
        key="key",
        request_get=lambda *_args, **_kwargs: _Response(status_code=404),
        request_post=post,
    )

    assert result.migration_status == "blocked_prerequisite"
    assert result.prerequisite_status == "missing"
    assert result.reason == "telegram_subscription_table_missing"
    assert post_calls == []


def test_preflight_validates_required_columns_and_chat_id_conflict_target() -> None:
    calls: list[dict[str, Any]] = []

    def get(url: str, **kwargs: Any) -> _Response:
        calls.append({"method": "get", "url": url, "kwargs": kwargs})
        return _Response(payload=[])

    def post(url: str, **kwargs: Any) -> _Response:
        calls.append({"method": "post", "url": url, "kwargs": kwargs})
        return _Response(payload=[])

    result = check_subscription_store(
        "https://example.supabase.co",
        "key",
        request_get=get,
        request_post=post,
    )

    assert result.status == "ready"
    assert calls[0]["kwargs"]["params"]["select"] == "chat_id,chat_type,status,is_editor,source"
    assert calls[1]["kwargs"]["json"] == []
    assert "on_conflict=chat_id" in calls[1]["url"]


def test_schema_error_remains_a_hard_failure() -> None:
    with pytest.raises(TelegramSubscriptionError, match="schema_incompatible"):
        check_subscription_store(
            "https://example.supabase.co",
            "key",
            request_get=lambda *_args, **_kwargs: _Response(payload=[]),
            request_post=lambda *_args, **_kwargs: _Response(status_code=400),
        )


def test_rerun_with_no_inserted_rows_is_already_applied() -> None:
    result = migrate_legacy_chat_ids_result(
        ("100",),
        url="https://example.supabase.co",
        key="key",
        request_get=lambda *_args, **_kwargs: _Response(payload=[]),
        request_post=lambda *_args, **_kwargs: _Response(payload=[]),
    )

    assert result.migration_status == "already_applied"
    assert result.prerequisite_status == "ready"
    assert result.migrated_count == 0
    assert result.reason == "all_recipients_already_present"


def test_store_requires_https_and_credentials() -> None:
    with pytest.raises(TelegramSubscriptionError, match="not_configured"):
        fetch_active_chat_ids("", "")
