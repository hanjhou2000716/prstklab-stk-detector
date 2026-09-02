import asyncio
import base64
import sys
from pathlib import Path

RAILWAY_MODULES = Path(__file__).parents[1] / "railway-monitor"
sys.path.insert(0, str(RAILWAY_MODULES))

from email_router import route_source  # noqa: E402
from email_store import EmailStore  # noqa: E402
from gmail_history_sync import (  # noqa: E402
    _decode_header_value,
    message_record,
    sync_gmail_history,
    sync_latest_financialjuice,
)
from gmail_watch import GmailWatchConfig  # noqa: E402

from gmail_ingress import GmailIngressService  # noqa: E402


def _encoded(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def _message(message_id: str = "m-1") -> dict:
    body = "\n".join((
        "Original headline: Oil supply update",
        "Importance: 9/10",
        "Possible impact: energy and rates",
        "AI commentary: public discovery only",
    ))
    return {
        "id": message_id,
        "threadId": "thread-1",
        "internalDate": "1787537742000",
        "labelIds": ["INBOX", "UNREAD"],
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": "RocketStock <jetmaie.fintech@gmail.com>"},
                {"name": "Subject", "value": "FinancialJuice breaking news"},
                {"name": "Date", "value": "Sun, 23 Aug 2026 19:15:42 -0700 (PDT)"},
            ],
            "body": {"data": _encoded(body)},
        },
    }


class _Response:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _Client:
    def __init__(self, *args, **kwargs):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return _Response({"access_token": "test-token"})

    async def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if url.endswith("/history"):
            return _Response({"historyId": "h1", "history": [{"messagesAdded": [{"message": {"id": "m-1"}}]}]})
        return _Response(_message())


class _ExpiredCursorClient(_Client):
    async def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if url.endswith("/history"):
            return _Response({"error": {"status": "NOT_FOUND"}}, status_code=404)
        return _Response(_message())


class _AttachmentClient(_Client):
    async def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if url.endswith("/history"):
            return _Response({"historyId": "h1", "history": [{"messagesAdded": [{"message": {"id": "m-1"}}]}]})
        if "/attachments/" in url:
            return _Response({"data": _encoded(
                "重要性評分: 10/10\n"
                "📝 繁體中文翻譯: 某公司據報正在評估合作。\n"
                "💡 AI 評論: 目前仍未正式確認。\n"
                "⚠️ 可能影響: 可能影響 AI 伺服器供應鏈。"
            )})
        message = _message()
        message["payload"] = {
            "mimeType": "multipart/alternative",
            "headers": message["payload"]["headers"],
            "parts": [
                {"mimeType": "text/plain", "body": {"data": _encoded("Importance: 10/10\n📝 繁體中文翻譯:")}},
                {"mimeType": "text/html", "body": {"attachmentId": "rich-html"}},
            ],
        }
        return _Response(message)


class _UnavailableAttachmentClient(_AttachmentClient):
    async def get(self, url, **kwargs):
        if "/attachments/" in url:
            self.calls.append(("GET", url, kwargs))
            return _Response({"error": "attachment_unavailable"}, status_code=404)
        return await super().get(url, **kwargs)


class _DeletedMessageClient(_Client):
    async def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if url.endswith("/history"):
            return _Response({"historyId": "h1", "history": [{"messagesAdded": [{"message": {"id": "deleted"}}]}]})
        return _Response({"error": "message_deleted"}, status_code=404)


class _LatestFinancialJuiceClient(_Client):
    async def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if url.endswith("/messages"):
            return _Response({"messages": [{"id": "m-latest"}]})
        return _Response(_message("m-latest"))


def _config() -> GmailWatchConfig:
    return GmailWatchConfig(
        topic_name="projects/test/topics/gmail",
        label_ids=("INBOX",),
        oauth_state="configured",
        audience="https://railway.example/gmail/push",
        service_account="push@example.iam.gserviceaccount.com",
        oauth_client_id="client",
        oauth_client_secret="secret",
        refresh_token="refresh",
    )


def test_message_record_extracts_only_parser_fields() -> None:
    record = message_record(_message())
    assert record["gmail_message_id"] == "m-1"
    assert "Oil supply update" in record["body"]
    assert record["source_published_at"] == "2026-08-24T02:15:42+00:00"
    assert "payload" not in record


def test_message_record_prefers_semantically_rich_html_over_plain_stub() -> None:
    html_body = """
    <html><body>
      <div><strong>重要性評分:</strong><span>10/10</span></div>
      <div><strong>📝 繁體中文翻譯:</strong><p>某公司據報正在評估合作。</p></div>
      <div><strong>💡 AI 評論:</strong><p>目前仍未正式確認。</p></div>
      <div><strong>⚠️ 可能影響:</strong><p>可能影響 AI 伺服器供應鏈。</p></div>
    </body></html>
    """
    message = _message("multipart-rich")
    message["payload"] = {
        "mimeType": "multipart/alternative",
        "headers": message["payload"]["headers"],
        "parts": [
            {"mimeType": "text/plain", "body": {"data": _encoded("Importance: 10/10\n📝 繁體中文翻譯:")}},
            {"mimeType": "text/html", "body": {"data": _encoded(html_body)}},
        ],
    }

    record = message_record(message)

    assert "某公司據報正在評估合作" in record["body"]
    assert "可能影響 AI 伺服器供應鏈" in record["body"]


def test_message_record_decodes_rfc2047_creator_headers_before_routing() -> None:
    encoded_subject = "=?UTF-8?B?6LKh57aT55qT6KeS?="  # 財經皓角
    encoded_from = "=?UTF-8?B?6LKh57aT55qT6KeS?= <creator@example.com>"  # 財經皓角
    message = _message()
    message["payload"]["headers"] = [
        {"name": "From", "value": encoded_from},
        {"name": "Subject", "value": encoded_subject},
    ]
    record = message_record(message)
    assert "皓角" in record["sender"]
    assert "皓角" in record["subject"]
    assert _decode_header_value(encoded_subject) == record["subject"]
    routed = route_source(sender=record["sender"], subject=record["subject"], body="今日市場觀察")
    assert routed["source"] == "haojiao"


def test_sync_history_routes_message_and_saves_public_projection(tmp_path) -> None:
    store = EmailStore(tmp_path / "mail.sqlite3")
    store.save_cursor(last_history_id="h0")
    ingress = GmailIngressService(store, _config())
    result = asyncio.run(sync_gmail_history(_config(), store, ingress, client_factory=_Client))
    assert result == {"status": "healthy", "processed": 1, "failed": 0, "duplicate": 0}
    health = store.health()
    assert health["public_observation_count"] == 1
    assert health["source_health"]["financialjuice"]["parsed_count"] == 1
    assert store.cursor()["last_history_id"] == "h1"


def test_sync_history_fetches_text_attachment_before_ingress(tmp_path) -> None:
    store = EmailStore(tmp_path / "mail.sqlite3")
    store.save_cursor(last_history_id="h0")
    ingress = GmailIngressService(store, _config())
    result = asyncio.run(sync_gmail_history(_config(), store, ingress, client_factory=_AttachmentClient))
    assert result == {"status": "healthy", "processed": 1, "failed": 0, "duplicate": 0}
    observation = store.public_observations(limit=1)[0]
    assert "某公司據報正在評估合作" in observation["vendor_translation"]
    assert "可能影響 AI 伺服器供應鏈" in observation["vendor_possible_impact"]


def test_sync_history_keeps_message_when_optional_text_attachment_is_unavailable(tmp_path) -> None:
    store = EmailStore(tmp_path / "mail.sqlite3")
    store.save_cursor(last_history_id="h0")
    ingress = GmailIngressService(store, _config())
    result = asyncio.run(sync_gmail_history(_config(), store, ingress, client_factory=_UnavailableAttachmentClient))
    assert result == {"status": "healthy", "processed": 1, "failed": 0, "duplicate": 0}


def test_sync_history_skips_deleted_history_messages(tmp_path) -> None:
    store = EmailStore(tmp_path / "mail.sqlite3")
    store.save_cursor(last_history_id="h0")
    ingress = GmailIngressService(store, _config())
    result = asyncio.run(sync_gmail_history(_config(), store, ingress, client_factory=_DeletedMessageClient))
    assert result == {"status": "healthy", "processed": 0, "failed": 0, "duplicate": 0, "skipped": 1}


def test_sync_latest_financialjuice_reprocesses_one_message_without_moving_cursor(tmp_path) -> None:
    store = EmailStore(tmp_path / "mail.sqlite3")
    store.save_cursor(last_history_id="h0")
    ingress = GmailIngressService(store, _config())
    result = asyncio.run(sync_latest_financialjuice(_config(), store, ingress, client_factory=_LatestFinancialJuiceClient))
    assert result == {"status": "healthy", "processed": 1, "failed": 0, "duplicate": 0}
    assert store.cursor()["last_history_id"] == "h0"
    assert store.health()["public_observation_count"] == 1


def test_expired_history_cursor_is_cleared_and_reported_as_gap(tmp_path) -> None:
    store = EmailStore(tmp_path / "mail.sqlite3")
    store.save_cursor(last_history_id="expired")
    ingress = GmailIngressService(store, _config())
    result = asyncio.run(
        sync_gmail_history(_config(), store, ingress, client_factory=_ExpiredCursorClient)
    )
    assert result == {
        "status": "history_cursor_expired",
        "processed": 0,
        "failed": 1,
        "duplicate": 0,
        "history_gap": True,
    }
    cursor = store.cursor()
    assert cursor["last_history_id"] is None
    assert cursor["watch_expiration"] is None
    assert cursor["watch_error"] == "history_cursor_expired"
