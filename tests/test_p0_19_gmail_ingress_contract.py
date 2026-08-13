"""P0-19 Gmail ingress trust-boundary and replay contract tests."""

import base64
import json
import sys
from pathlib import Path

import pytest

RAILWAY_MODULES = Path(__file__).parents[1] / "railway-monitor"
sys.path.insert(0, str(RAILWAY_MODULES))

from email_store import EmailStore  # noqa: E402
from gmail_watch import GmailWatchConfig  # noqa: E402

from gmail_ingress import GmailIngressError, GmailIngressService  # noqa: E402


def _config() -> GmailWatchConfig:
    return GmailWatchConfig(
        topic_name="projects/p/topics/t",
        label_ids=("Label_1",),
        oauth_state="configured",
        audience="https://railway.example/gmail/push",
        service_account="push@example.iam.gserviceaccount.com",
    )


def _push(history_id: str = "123") -> bytes:
    payload = {"emailAddress": "bot@example.com", "historyId": history_id}
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    return json.dumps({"message": {"data": encoded, "publishTime": "2026-08-13T00:00:00Z"}}).encode()


def _headers() -> dict[str, str]:
    return {
        "authorization": "Bearer verified-jwt",
        "x-goog-authenticated-audience": "https://railway.example/gmail/push",
        "x-goog-authenticated-user-email": "accounts.google.com:push@example.iam.gserviceaccount.com",
    }


def test_p0_19_rejects_oversized_pubsub_payload(tmp_path: Path) -> None:
    service = GmailIngressService(EmailStore(tmp_path / "mail.sqlite3"), _config())
    with pytest.raises(GmailIngressError, match="push_body_too_large"):
        service.decode_push(b"x" * (256 * 1024 + 1), _headers())


def test_p0_19_accept_push_is_cursor_only_and_restart_safe(tmp_path: Path) -> None:
    store = EmailStore(tmp_path / "mail.sqlite3")
    service = GmailIngressService(store, _config())
    first = service.accept_push(_push("100"), _headers())
    replay = service.accept_push(_push("100"), _headers())
    assert first["accepted"] is True
    assert replay["accepted"] is True
    assert store.cursor()["last_history_id"] == "100"
    assert store.health()["raw_content_stored"] is False


def test_p0_19_rejects_malformed_encoded_notification(tmp_path: Path) -> None:
    service = GmailIngressService(EmailStore(tmp_path / "mail.sqlite3"), _config())
    body = json.dumps({"message": {"data": "not-base64"}}).encode()
    with pytest.raises(GmailIngressError, match="invalid_pubsub_envelope"):
        service.decode_push(body, _headers())


def test_p0_19_missing_gateway_configuration_fails_closed(tmp_path: Path) -> None:
    service = GmailIngressService(EmailStore(tmp_path / "mail.sqlite3"), GmailWatchConfig.from_env({}))
    with pytest.raises(GmailIngressError, match="configuration_missing"):
        service.decode_push(_push(), _headers())
