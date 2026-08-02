from src.delivery_smoke_test import run_smoke_test, validate_delivery_configuration


def _configure(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_IDS", "111,222")
    monkeypatch.setenv("DASHBOARD_URL", "https://example.test/app")
    # An ignored local .env may exist; an explicit empty environment value
    # prevents dotenv from loading a real token during this unit test.
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "")
    monkeypatch.delenv("RAILWAY_STATUS_URL", raising=False)
    monkeypatch.delenv("RAILWAY_STATUS_SHARED_SECRET", raising=False)


def test_delivery_smoke_defaults_to_non_network_dry_run(monkeypatch):
    _configure(monkeypatch)
    report = run_smoke_test()
    assert report["ok"] is True
    assert report["recipient_count"] == 2
    assert report["smoke_text_length"] <= 30
    assert "token" not in str(report).lower()


def test_delivery_smoke_requires_callback_pair(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setenv("RAILWAY_STATUS_URL", "https://railway.example")
    report = validate_delivery_configuration()
    assert report["ok"] is False
    assert any("configured together" in error for error in report["errors"])


def test_delivery_smoke_rejects_legacy_singular_recipient(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_IDS", "100,200")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "100")
    monkeypatch.setenv("DASHBOARD_URL", "https://example.test/app")

    report = validate_delivery_configuration()

    assert report["ok"] is False
    assert report["legacy_singular_configured"] is True
    assert any("TELEGRAM_CHAT_ID is deprecated" in error for error in report["errors"])


def test_delivery_smoke_requires_https_callback(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_IDS", "100")
    monkeypatch.setenv("DASHBOARD_URL", "https://example.test/app")
    monkeypatch.setenv("RAILWAY_STATUS_URL", "http://railway.test")
    monkeypatch.setenv("RAILWAY_STATUS_SHARED_SECRET", "secret")

    report = validate_delivery_configuration()

    assert report["ok"] is False
    assert any("RAILWAY_STATUS_URL must use HTTPS" in error for error in report["errors"])


def test_delivery_smoke_send_requires_bot_token(monkeypatch):
    _configure(monkeypatch)
    report = run_smoke_test(send=True)
    assert report["ok"] is False
    assert report["errors"] == ["TELEGRAM_BOT_TOKEN is empty"]
