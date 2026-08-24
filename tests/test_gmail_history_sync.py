import asyncio
import base64
import sys
from pathlib import Path

RAILWAY_MODULES = Path(__file__).parents[1] / "railway-monitor"
sys.path.insert(0, str(RAILWAY_MODULES))

from email_store import EmailStore  # noqa: E402
from gmail_history_sync import message_record, sync_gmail_history  # noqa: E402
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
