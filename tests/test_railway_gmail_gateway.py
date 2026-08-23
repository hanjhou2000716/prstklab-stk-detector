import base64
import json
import sys
from urllib.parse import parse_qs
from pathlib import Path

import pytest

RAILWAY_MODULES = Path(__file__).parents[1] / "railway-monitor"
sys.path.insert(0, str(RAILWAY_MODULES))

from email_store import EmailStore  # noqa: E402
from gmail_watch import GmailWatchConfig, GmailWatchManager, health, renewal_due  # noqa: E402

from gmail_ingress import GmailIngressError, GmailIngressService  # noqa: E402


def _config() -> GmailWatchConfig:
    return GmailWatchConfig(
        topic_name="projects/p/topics/t",
        label_ids=("Label_1",),
        oauth_state="configured",
        audience="https://railway.example/gmail/push",
        service_account="push@example.iam.gserviceaccount.com",
    )


def _push() -> bytes:
    payload = {"emailAddress": "bot@example.com", "historyId": "123"}
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    return json.dumps({"message": {"data": encoded, "publishTime": "2026-08-13T00:00:00Z"}}).encode()


def _headers() -> dict[str, str]:
    return {
        "authorization": "Bearer verified-jwt",
        "x-goog-authenticated-audience": "https://railway.example/gmail/push",
        "x-goog-authenticated-user-email": "accounts.google.com:push@example.iam.gserviceaccount.com",
    }


def test_watch_configuration_is_fail_closed() -> None:
    config = GmailWatchConfig.from_env({})
    assert config.status == "configuration_missing"
    assert config.watch_request()["status"] == "configuration_missing"


def test_email_router_imports_from_standalone_railway_root() -> None:
    import subprocess

    result = subprocess.run(
        [sys.executable, "-c", "import email_router; print(sorted(email_router.KNOWN_SOURCES))"],
        cwd=RAILWAY_MODULES,
        check=True,
        capture_output=True,
        text=True,
    )


def _oauth_config() -> GmailWatchConfig:
    return GmailWatchConfig(
        topic_name="projects/p/topics/t",
        label_ids=("INBOX",),
        oauth_state="configured",
        audience="https://railway.example/gmail/push",
        service_account="push@example.iam.gserviceaccount.com",
        oauth_client_id="client-id",
        oauth_client_secret="client-secret",
        refresh_token="refresh-token",
    )
    assert "haojiao" in result.stdout
    assert "jenny" in result.stdout


def test_watch_renewal_is_due_without_expiration() -> None:
    assert renewal_due(None)


def test_watch_manager_refreshes_oauth_and_persists_lease(tmp_path: Path) -> None:
    store = EmailStore(tmp_path / "mail.sqlite3")
    calls: list[tuple[str, dict, dict]] = []

    def transport(url: str, body: bytes, headers: dict[str, str], _timeout: float) -> tuple[int, bytes]:
        payload = parse_qs(body.decode()) if url.endswith("/token") else json.loads(body.decode())
        calls.append((url, payload, headers))
        if url.endswith("/token"):
            assert headers["Content-Type"] == "application/x-www-form-urlencoded"
            assert payload["grant_type"] == ["refresh_token"]
            return 200, json.dumps({"access_token": "access-token"}).encode()
        assert headers["Authorization"] == "Bearer access-token"
        assert payload == {
            "topicName": "projects/p/topics/t",
            "labelIds": ["INBOX"],
            "labelFilterAction": "include",
        }
        return 200, json.dumps({"historyId": "history-1", "expiration": "1780000000000"}).encode()

    result = GmailWatchManager(_oauth_config(), store, transport=transport).ensure_watch()
    assert result["status"] == "healthy"
    assert result["renewed"] is True
    cursor = store.cursor()
    assert cursor["last_history_id"] == "history-1"
    assert cursor["watch_expiration"]
    assert cursor["watch_last_renewed_at"]
    assert cursor["watch_error"] is None
    assert len(calls) == 2


def test_watch_manager_does_not_renew_active_lease(tmp_path: Path) -> None:
    store = EmailStore(tmp_path / "mail.sqlite3")
    store.save_cursor(watch_expiration="2099-01-01T00:00:00+00:00")
    calls: list[str] = []
    result = GmailWatchManager(
        _oauth_config(), store,
        transport=lambda url, *_args: (calls.append(url) or (500, b"{}")),
    ).ensure_watch()
    assert result == {"status": "healthy", "renewed": False, "watch_expiration": "2099-01-01T00:00:00+00:00"}
    assert calls == []


def test_watch_manager_failure_is_bounded_and_redacted(tmp_path: Path) -> None:
    store = EmailStore(tmp_path / "mail.sqlite3")

    def transport(_url: str, _body: bytes, _headers: dict[str, str], _timeout: float) -> tuple[int, bytes]:
        return 403, b'{"error":"forbidden"}'

    result = GmailWatchManager(_oauth_config(), store, transport=transport).ensure_watch()
    assert result == {"status": "failed", "renewed": False, "error": "http_403"}
    assert "refresh-token" not in json.dumps(result)
    cursor = store.cursor()
    assert cursor["watch_error"] == "http_403"
    assert cursor["watch_error_at"]


def test_ingress_rejects_invalid_identity(tmp_path: Path) -> None:
    service = GmailIngressService(EmailStore(tmp_path / "mail.sqlite3"), _config())
    with pytest.raises(GmailIngressError, match="unauthenticated"):
        service.decode_push(_push(), {})


def test_ingress_rejects_when_gateway_configuration_is_missing(tmp_path: Path) -> None:
    service = GmailIngressService(EmailStore(tmp_path / "mail.sqlite3"), GmailWatchConfig.from_env({}))
    with pytest.raises(GmailIngressError, match="configuration_missing"):
        service.decode_push(_push(), _headers())


def test_ingress_strict_mode_requires_verified_jwt(tmp_path: Path) -> None:
    strict = GmailWatchConfig(
        topic_name="projects/p/topics/t",
        label_ids=("Label_1",),
        oauth_state="configured",
        audience="https://railway.example/gmail/push",
        service_account="push@example.iam.gserviceaccount.com",
        require_jwt_verification=True,
    )
    service = GmailIngressService(EmailStore(tmp_path / "mail.sqlite3"), strict)
    with pytest.raises(GmailIngressError, match="jwt_verification"):
        service.decode_push(_push(), _headers())


def test_ingress_strict_mode_uses_injected_jwt_verifier(tmp_path: Path) -> None:
    strict = GmailWatchConfig(
        topic_name="projects/p/topics/t",
        label_ids=("Label_1",),
        oauth_state="configured",
        audience="https://railway.example/gmail/push",
        service_account="push@example.iam.gserviceaccount.com",
        require_jwt_verification=True,
    )
    service = GmailIngressService(
        EmailStore(tmp_path / "mail.sqlite3"),
        strict,
        token_verifier=lambda token, audience: token == "verified-jwt" and audience == strict.audience,
    )
    assert service.decode_push(_push(), _headers())["history_id"] == "123"


def test_ingress_accepts_replay_safe_observation_and_dedupes(tmp_path: Path) -> None:
    store = EmailStore(tmp_path / "mail.sqlite3")
    service = GmailIngressService(store, _config())
    assert service.decode_push(_push(), _headers())["history_id"] == "123"
    record = {
        "gmail_message_id": "m-1",
        "sender": "alerts@financialjuice.com",
        "subject": "FinancialJuice breaking news",
        "body": "Original headline: Oil supply update\nImportance: 10/10",
    }
    first = service.accept_email(record)
    second = service.accept_email(record)
    assert first["accepted"] is True
    assert second["status"] == "duplicate"
    assert store.health()["raw_content_stored"] is False


def test_push_advances_durable_cursor_without_storing_message_body(tmp_path: Path) -> None:
    store = EmailStore(tmp_path / "mail.sqlite3")
    service = GmailIngressService(store, _config())
    result = service.accept_push(_push(), _headers())
    assert result["accepted"] is True
    assert result["history_id"] == "123"
    cursor = store.cursor()
    assert cursor["last_history_id"] == "123"
    assert cursor["last_notification_at"]
    assert store.health()["raw_content_stored"] is False


def test_known_source_template_failure_enters_dlq(tmp_path: Path) -> None:
    store = EmailStore(tmp_path / "mail.sqlite3")
    service = GmailIngressService(store, _config())
    result = service.accept_email({"gmail_message_id": "m-2", "sender": "alerts@financialjuice.com", "subject": "hello", "body": "unknown"})
    assert result["status"] == "unsupported_template"
    assert store.health()["dlq_count"] == 1


def test_health_reports_stale_watch(tmp_path: Path) -> None:
    store = EmailStore(tmp_path / "mail.sqlite3")
    store.save_cursor(watch_expiration="2020-01-01T00:00:00+00:00")
    result = health(_config(), store.cursor())
    assert result["status"] == "stale"
    assert result["watch_active"] is False
    assert result["observability"]["state"] == "stale"


def test_health_exposes_privacy_safe_observability(tmp_path: Path) -> None:
    result = health(
        _config(),
        {
            "watch_expiration": "2099-01-01T00:00:00Z",
            "last_history_id": "private-history-id",
            "last_message_id": "private-message-id",
            "last_notification_at": "2026-08-13T00:00:00Z",
            "last_sync_at": "2026-08-13T00:01:00Z",
            "dlq_count": 2,
            "last_receipt_at": "2026-08-13T00:02:00Z",
        },
    )
    assert result["status"] == "healthy"
    observability = result["observability"]
    assert observability["observations"] == 0
    assert observability["last_received_at"] == "2026-08-13T00:00:00+00:00"
    assert observability["last_parsed_at"] == "2026-08-13T00:01:00+00:00"
    assert observability["parser_error_count"] == 2
    assert observability["last_delivery_at"] == "2026-08-13T00:02:00+00:00"
    assert observability["state"] == "healthy"
    assert observability["history_cursor_present"] is True
    assert len(observability["history_cursor_hash"]) == 16
    assert observability["queue_pending_count"] == 0
    assert observability["dead_letter_count"] == 2
    assert "last_history_id" not in result
    assert "last_message_id" not in result


def test_gmail_watch_health_exposes_cursor_fingerprint_only(tmp_path: Path) -> None:
    result = health(
        _config(),
        {"watch_expiration": "2099-01-01T00:00:00+00:00", "last_history_id": "123"},
    )
    fingerprint = result["observability"]["history_cursor_hash"]
    assert len(fingerprint) == 16
    assert all(char in "0123456789abcdef" for char in fingerprint)
    assert "123" not in str(result)


def test_health_invalid_timestamps_fail_closed_without_leaking_cursor(tmp_path: Path) -> None:
    result = health(
        GmailWatchConfig.from_env({}),
        {"last_history_id": "private", "last_notification_at": "not-a-timestamp", "dlq_count": "bad"},
    )
    assert result["status"] == "configuration_missing"
    assert result["observability"]["last_received_at"] is None
    assert result["observability"]["parser_error_count"] == 0
    assert "last_history_id" not in json.dumps(result)
