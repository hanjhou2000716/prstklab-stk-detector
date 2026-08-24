from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.append(str(Path(__file__).parents[1] / "railway-monitor"))

from email_store import EmailStore  # noqa: E402
from gmail_watch import GmailWatchConfig  # noqa: E402
from gmail_watch_service import renew_watch_if_due  # noqa: E402


def _config() -> GmailWatchConfig:
    return GmailWatchConfig(
        topic_name="projects/p/topics/t",
        label_ids=("Label_1",),
        oauth_state="configured",
        audience="https://railway.example/gmail/push",
        service_account="push@example.iam.gserviceaccount.com",
        oauth_client_id="client",
        oauth_client_secret="secret",
        refresh_token="refresh",
    )


class _Response:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload


class _Client:
    def __init__(self, responses: list[_Response]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def post(self, url: str, **kwargs: object) -> _Response:
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def _run(coro):
    return asyncio.run(coro)


def test_active_watch_skips_network(tmp_path: Path) -> None:
    store = EmailStore(tmp_path / "mail.sqlite3")
    expiration = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    store.save_cursor(watch_expiration=expiration, last_history_id="history-1")
    called = False

    def factory(**_kwargs: object) -> _Client:
        nonlocal called
        called = True
        return _Client([])

    result = _run(renew_watch_if_due(_config(), store, client_factory=factory))
    assert result["watch_status"] == "active"
    assert result["attempted"] is False
    assert called is False


def test_renews_and_persists_cursor(tmp_path: Path) -> None:
    store = EmailStore(tmp_path / "mail.sqlite3")
    client = _Client([
        _Response(200, {"access_token": "token"}),
        _Response(200, {"expiration": "1780000000000", "historyId": "history-2"}),
    ])
    result = _run(renew_watch_if_due(_config(), store, force=True, client_factory=lambda **_kwargs: client))
    assert result["watch_status"] == "active"
    assert store.cursor()["last_history_id"] == "history-2"
    assert store.cursor()["watch_expiration"]
    assert client.calls[1][1]["headers"] == {"Authorization": "Bearer token"}


def test_http_403_is_reported_without_leaking_response(tmp_path: Path) -> None:
    store = EmailStore(tmp_path / "mail.sqlite3")
    client = _Client([_Response(200, {"access_token": "token"}), _Response(403, {"error": "private"})])
    result = _run(renew_watch_if_due(_config(), store, force=True, client_factory=lambda **_kwargs: client))
    assert result == {"status": "failed", "watch_status": "failed", "attempted": True, "error": "http_403"}
    assert store.cursor()["watch_error"] == "http_403"


def test_recent_failure_suppresses_repeated_watch_call(tmp_path: Path) -> None:
    store = EmailStore(tmp_path / "mail.sqlite3")
    store.save_cursor(watch_error="http_403", watch_error_at=datetime.now(UTC).isoformat())
    called = False

    def factory(**_kwargs: object) -> _Client:
        nonlocal called
        called = True
        return _Client([])

    result = _run(renew_watch_if_due(_config(), store, client_factory=factory))
    assert result["watch_status"] == "failed"
    assert result["attempted"] is False
    assert result["retry_suppressed"] is True
    assert result["retry_after_seconds"] > 0
    assert called is False


def test_success_clears_previous_watch_failure(tmp_path: Path) -> None:
    store = EmailStore(tmp_path / "mail.sqlite3")
    store.save_cursor(watch_error="http_403", watch_error_at=datetime.now(UTC).isoformat())
    client = _Client([
        _Response(200, {"access_token": "token"}),
        _Response(200, {"expiration": "1780000000000", "historyId": "history-3"}),
    ])
    result = _run(renew_watch_if_due(_config(), store, force=True, client_factory=lambda **_kwargs: client))
    assert result["watch_status"] == "active"
    assert store.cursor()["watch_error"] is None
    assert store.cursor()["watch_error_at"] is None


def test_missing_oauth_is_fail_closed(tmp_path: Path) -> None:
    store = EmailStore(tmp_path / "mail.sqlite3")
    result = _run(renew_watch_if_due(GmailWatchConfig.from_env({
        "GMAIL_WATCH_TOPIC": "projects/p/topics/t",
        "GMAIL_WATCH_LABEL_IDS": "Label_1",
        "GMAIL_OAUTH_STATE": "configured",
        "GMAIL_PUBSUB_AUDIENCE": "https://railway.example/gmail/push",
        "GMAIL_PUBSUB_SERVICE_ACCOUNT": "push@example.iam.gserviceaccount.com",
    }), store, force=True, client_factory=lambda **_kwargs: _Client([])))
    assert result["status"] == "configuration_missing"
    assert "GMAIL_REFRESH_TOKEN" in result["missing"]


def test_watch_includes_inbox_by_default_for_history_sync() -> None:
    config = GmailWatchConfig.from_env({
        "GMAIL_WATCH_TOPIC": "projects/p/topics/t",
        "GMAIL_WATCH_LABEL_IDS": "Label_1",
        "GMAIL_OAUTH_STATE": "configured",
        "GMAIL_PUBSUB_AUDIENCE": "https://railway.example/gmail/push",
        "GMAIL_PUBSUB_SERVICE_ACCOUNT": "push@example.iam.gserviceaccount.com",
    })
    assert config.label_ids == ("Label_1", "INBOX")


def test_watch_can_opt_out_of_inbox() -> None:
    config = GmailWatchConfig.from_env({"GMAIL_WATCH_INCLUDE_INBOX": "false"})
    assert config.label_ids == ()
