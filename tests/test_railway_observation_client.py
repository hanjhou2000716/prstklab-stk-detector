from __future__ import annotations

from src import railway_observation_client as client


def test_observation_export_url_uses_stable_route() -> None:
    assert client.observation_export_url("https://railway.example/health") == "https://railway.example/external-observations?limit=100"


def test_missing_configuration_is_explicit_and_safe(monkeypatch) -> None:
    monkeypatch.delenv("RAILWAY_OBSERVATIONS_URL", raising=False)
    monkeypatch.delenv("RAILWAY_STATUS_URL", raising=False)
    rows, health = client.load_railway_observations(secret="secret")
    assert rows == []
    assert health["status"] == "configuration_missing"


def test_loader_keeps_only_public_safe_rows(monkeypatch) -> None:
    class Response:
        status_code = 200

        def json(self):
            return {"status": "ready", "observations": [
                {"observation_id": "safe-1", "source": "financialjuice", "public_safe": True, "unexpected": "drop"},
                {"observation_id": "private-1", "source": "financialjuice", "public_safe": True, "body": "secret"},
            ]}

    seen = {}

    def fake_get(url, **kwargs):
        seen.update({"url": url, **kwargs})
        return Response()

    monkeypatch.setattr(client.httpx, "get", fake_get)
    rows, health = client.load_railway_observations(url="https://railway.example/health", secret="secret")
    assert [row["observation_id"] for row in rows] == ["safe-1"]
    assert health["status"] == "ready"
    assert health["rejected_count"] == 1
    assert "unexpected" not in rows[0]
    assert seen["headers"]["X-PRSTK-Signature"].startswith("sha256=")


def test_loader_rejects_unknown_source_and_private_transport_fields(monkeypatch) -> None:
    class Response:
        status_code = 200

        def json(self):
            return {"status": "ready", "observations": [
                {"observation_id": "other", "source": "other", "public_safe": True},
                {"observation_id": "private", "source": "financialjuice", "public_safe": True, "message_id": "private"},
            ]}

    monkeypatch.setattr(client.httpx, "get", lambda *_args, **_kwargs: Response())
    rows, health = client.load_railway_observations(url="https://railway.example/health", secret="secret")
    assert rows == []
    assert health["rejected_count"] == 2
