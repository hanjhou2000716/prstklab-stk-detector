import base64
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs

import pytest

RAILWAY_MODULES = Path(__file__).parents[1] / "railway-monitor"
sys.path.insert(0, str(RAILWAY_MODULES))

from email_router import route_source  # noqa: E402
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
    assert "haojiao" in result.stdout
    assert "jenny" in result.stdout


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


def test_watch_manager_suppresses_recent_failure_until_cooldown(tmp_path: Path) -> None:
    store = EmailStore(tmp_path / "mail.sqlite3")
    store.save_cursor(
        watch_error="http_403",
        watch_error_at="2026-08-25T08:00:00+00:00",
    )
    calls: list[str] = []
    manager = GmailWatchManager(
        _oauth_config(),
        store,
        transport=lambda url, *_args: (calls.append(url) or (500, b"{}")),
        now=lambda: datetime.fromisoformat("2026-08-25T08:30:00+00:00"),
    )
    result = manager.ensure_watch()
    assert result["status"] == "failed"
    assert result["retry_suppressed"] is True
    assert result["retry_after_seconds"] > 0
    assert calls == []


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


def test_ingress_strict_mode_uses_verified_jwt_email_when_proxy_header_is_absent(tmp_path: Path) -> None:
    strict = GmailWatchConfig(
        topic_name="projects/p/topics/t",
        label_ids=("Label_1",),
        oauth_state="configured",
        audience="https://railway.example/gmail/push",
        service_account="push@example.iam.gserviceaccount.com",
        require_jwt_verification=True,
    )
    headers = _headers()
    headers.pop("x-goog-authenticated-user-email")
    service = GmailIngressService(
        EmailStore(tmp_path / "mail.sqlite3"),
        strict,
        token_verifier=lambda _token, _audience: {"email": strict.service_account, "email_verified": True},
    )
    assert service.decode_push(_push(), headers)["history_id"] == "123"


def test_ingress_accepts_pubsub_oidc_without_nonstandard_audience_header(tmp_path: Path) -> None:
    headers = _headers()
    headers.pop("x-goog-authenticated-audience")
    service = GmailIngressService(EmailStore(tmp_path / "mail.sqlite3"), _config())
    assert service.decode_push(_push(), headers)["history_id"] == "123"


@pytest.mark.parametrize(
    "identity",
    [
        "accounts.google.com:serviceAccount:push@example.iam.gserviceaccount.com",
        "serviceAccount:push@example.iam.gserviceaccount.com",
        "https://accounts.google.com:push@example.iam.gserviceaccount.com",
    ],
)
def test_ingress_normalizes_pubsub_service_account_identity_prefixes(
    tmp_path: Path,
    identity: str,
) -> None:
    headers = _headers()
    headers["x-goog-authenticated-user-email"] = identity
    service = GmailIngressService(EmailStore(tmp_path / "mail.sqlite3"), _config())
    assert service.decode_push(_push(), headers)["history_id"] == "123"


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


def test_duplicate_replay_enriches_public_projection_without_second_event(tmp_path: Path) -> None:
    store = EmailStore(tmp_path / "mail.sqlite3")
    service = GmailIngressService(store, _config())
    base = {
        "gmail_message_id": "m-enrich-1",
        "sender": "alerts@financialjuice.com",
        "subject": "FinancialJuice breaking news",
    }
    first = service.accept_email({
        **base,
        "body": (
            "Importance: 8/10\n"
            "Original headline: FinancialJuice 公開快訊\n"
            "Translation: 資訊待核對。\n"
            "AI commentary: 資訊待核對。\n"
            "Possible impact: 資訊待核對。"
        ),
    })
    second = service.accept_email({
        **base,
        "body": (
            "Importance: 8/10\n"
            "Original headline: FinancialJuice 公開快訊\n"
            "Translation: 某公司據報正在評估合作。\n"
            "AI commentary: 目前仍未正式確認。\n"
            "Possible impact: 可能影響伺服器供應鏈。"
        ),
    })
    assert first["accepted"] is True
    assert second["status"] == "duplicate"
    assert second["public_observation_count"] == 1
    rows = store.public_observations()
    assert len(rows) == 1
    assert rows[0]["vendor_translation"].startswith("某公司據報")
    assert "目前仍未正式確認" in rows[0]["vendor_analysis"]
    assert "可能影響伺服器供應鏈" in rows[0]["vendor_possible_impact"]


def test_different_messages_with_the_same_provider_template_are_not_collapsed(
    tmp_path: Path,
) -> None:
    store = EmailStore(tmp_path / "mail.sqlite3")
    service = GmailIngressService(store, _config())
    base = {
        "sender": "alerts@financialjuice.com",
        "subject": "FinancialJuice breaking news",
    }
    first = service.accept_email({
        **base,
        "gmail_message_id": "m-template-1",
        "body": "Original headline: Oil supply update\nImportance: 10/10",
    })
    second = service.accept_email({
        **base,
        "gmail_message_id": "m-template-2",
        "body": "Original headline: Oil supply update\nImportance: 9/10",
    })
    assert first["accepted"] is True
    assert second["accepted"] is True
    rows = service.store.public_observations()
    assert len(rows) == 2
    assert len({row["observation_id"] for row in rows}) == 2


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


def test_creator_marker_in_body_cannot_hijack_source_route() -> None:
    result = route_source(
        sender="newsletter@unknown.example",
        subject="市場摘要",
        body="引用財經皓角的看法；Episode: unrelated commentary",
    )
    assert result["source"] == "unknown"
    assert result["parse_status"] == "invalid_source"


def test_retired_creator_identity_is_routed_to_suppression() -> None:
    result = route_source(
        sender="財經皓角 <creator@example.com>",
        subject="財經皓角市場觀察",
        body="Title: legacy\nFact: historical fixture",
    )
    assert result["source"] == "haojiao"
    assert result["parse_status"] == "retired_source_suppressed"
    assert result["failure_reason"] == "creator_source_retired"


def test_financialjuice_marker_in_github_mail_cannot_hijack_source_route() -> None:
    result = route_source(
        sender="github-actions[bot] <noreply@github.com>",
        subject="PR run failed: FinancialJuice semantics",
        body="Quality check failed while mentioning FinancialJuice.",
    )
    assert result["source"] == "unknown"
    assert result["parse_status"] == "invalid_source"
    assert result["failure_reason"] == "source_identity_not_trusted"


def test_configured_gmail_financialjuice_relay_is_trusted() -> None:
    result = route_source(
        sender="FinancialJuice <james19951209@gmail.com>",
        subject="FinancialJuice alert",
        body="Importance: 10/10\nOriginal headline: Oil supply update",
    )
    assert result["source"] == "financialjuice"
    assert result["parse_status"] == "identified"
    assert result["source_identity_verified"] is True


def test_financialjuice_subject_identity_allows_canonical_fallback_parser(tmp_path: Path) -> None:
    """A real source-labelled alert need not contain every legacy field label."""
    store = EmailStore(tmp_path / "mail.sqlite3")
    service = GmailIngressService(store, _config())
    result = service.accept_email({
        "gmail_message_id": "fj-natural-1",
        "sender": "alerts@financialjuice.com",
        "subject": "FinancialJuice alert",
        "body": "Oil supply update",
    })
    assert result["accepted"] is True
    assert result["status"] == "parsed"
    assert result["public_observation_count"] == 1
    assert store.health()["source_health"]["financialjuice"]["failed_count"] == 0


def test_legitimate_financialjuice_projection_carries_verified_identity(tmp_path: Path) -> None:
    store = EmailStore(tmp_path / "mail.sqlite3")
    service = GmailIngressService(store, _config())
    result = service.accept_email({
        "gmail_message_id": "fj-identity-1",
        "sender": "alerts@financialjuice.com",
        "subject": "FinancialJuice alert",
        "body": "Importance: 8/10\nOriginal headline: Oil supply update",
    })
    assert result["accepted"] is True
    assert store.public_observations(limit=1)[0]["source_identity_verified"] is True


def test_retired_creator_display_name_is_suppressed_without_public_observation(tmp_path: Path) -> None:
    """Retired Creator mail advances only through the redacted DLQ path."""
    store = EmailStore(tmp_path / "mail.sqlite3")
    service = GmailIngressService(store, _config())
    result = service.accept_email({
        "gmail_message_id": "creator-natural-1",
        "sender": "財經皓角 <creator@example.com>",
        "subject": "今日市場觀察",
        "body": "台股與美股市場摘要，僅供公開資訊整理。",
    })
    assert result["accepted"] is False
    assert result["status"] == "retired_source_suppressed"
    assert store.public_observations() == []
    assert store.health()["dlq_count"] == 1


def test_retired_creator_does_not_create_public_projection(tmp_path: Path) -> None:
    store = EmailStore(tmp_path / "mail.sqlite3")
    service = GmailIngressService(store, _config())
    result = service.accept_email({
        "gmail_message_id": "private-creator-message",
        "sender": "財經皓角 <creator@example.com>",
        "subject": "今日市場觀察",
        "body": "標題：AI 產業觀察\n重點：供應鏈仍需核對\n看法：保持中立",
    })
    assert result["accepted"] is False
    assert result["status"] == "retired_source_suppressed"
    assert store.public_observations() == []


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
