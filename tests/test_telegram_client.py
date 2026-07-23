import pytest

from src.telegram_client import validate_brief


def test_accepts_30_character_brief():
    validate_brief("測" * 30)


def test_rejects_over_30_character_brief():
    with pytest.raises(ValueError, match="超過 30 字"):
        validate_brief("測" * 31)


def test_rejects_blank_brief():
    with pytest.raises(ValueError, match="不可空白"):
        validate_brief("   ")

