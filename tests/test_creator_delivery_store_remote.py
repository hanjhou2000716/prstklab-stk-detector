from src import creator_delivery_store


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {"notification_keys": ["n-1", "n-2", "n-1"]}


def test_remote_creator_history_request_is_signed(monkeypatch):
    captured = {}

    def post(*args, **kwargs):
        captured["url"] = args[0] if args else kwargs.get("url")
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr(creator_delivery_store.requests, "post", post)
    creator_delivery_store.load_remote_creator_delivery_history("https://railway.example", "secret")
    assert captured["url"].endswith("/creator-delivery-history")
    assert captured["headers"]["X-PRSTK-Signature"].startswith("sha256=")


def test_remote_creator_history_is_bounded_and_deduplicated(monkeypatch):
    monkeypatch.setattr(creator_delivery_store.requests, "post", lambda *_args, **_kwargs: _Response())
    rows, status = creator_delivery_store.load_remote_creator_delivery_history("https://railway.example", "secret")
    assert status == "healthy"
    assert [row["notification_key"] for row in rows] == ["n-1", "n-2"]


def test_remote_creator_history_fails_soft_without_secret():
    rows, status = creator_delivery_store.load_remote_creator_delivery_history("https://railway.example", "")
    assert rows == []
    assert status == "secret_missing"
