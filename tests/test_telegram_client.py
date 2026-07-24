import pytest

from src.telegram_client import mini_app_button, validate_brief


def test_accepts_30_character_brief():
    validate_brief("測" * 30)


def test_rejects_over_30_character_brief():
    with pytest.raises(ValueError, match="超過 30 字"):
        validate_brief("測" * 31)


def test_rejects_blank_brief():
    with pytest.raises(ValueError, match="不可空白"):
        validate_brief("   ")


def test_mini_app_button_uses_telegram_web_app_field():
    assert mini_app_button("https://example.github.io/app/") == {
        "text": "開啟稜量 Mini App",
        "web_app": {"url": "https://example.github.io/app/"},
    }


def test_mini_app_button_rejects_non_https_url():
    with pytest.raises(ValueError, match="HTTPS"):
        mini_app_button("http://example.test/app")
