import pytest

from src.alert_caption import make_caption, validate_caption


def test_caption_compacts_whitespace_and_verified_state():
    caption = make_caption(subject="台指", change="  +2.9%  ", verified=True, icon="🟠")
    validate_caption(caption)
    assert "  " not in caption


def test_caption_long_subject_uses_safe_fallback():
    caption = make_caption(subject="非常長的事件標題" * 20, change="+99.99%", state="等待核對", icon="⚠️")
    validate_caption(caption)
    assert len(caption) <= 40


def test_validate_caption_rejects_empty_and_long():
    with pytest.raises(ValueError):
        validate_caption("")
    with pytest.raises(ValueError):
        validate_caption("x" * 41)
