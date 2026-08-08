import importlib.util
import struct

import pytest

from src.alert_card_renderer import HEIGHT, WIDTH, RendererError, fallback_card, render_alert_card


def test_fallback_card_is_fixed_png(tmp_path):
    path = fallback_card(tmp_path / "fallback.png")
    data = path.read_bytes()
    assert data.startswith(b"\x89PNG")
    width, height = struct.unpack(">II", data[16:24])
    assert (width, height) == (WIDTH, HEIGHT)


def test_renderer_requires_formal_runtime_or_produces_valid_card(tmp_path):
    try:
        path = render_alert_card({"title": "測試", "lifecycle_state": "observation"}, tmp_path / "alert.png")
    except RendererError as exc:
        if importlib.util.find_spec("playwright") is not None and exc.error_type not in {"playwright_missing", "chromium_unavailable"}:
            pytest.fail(f"renderer failed despite Playwright being installed: {exc}")
        assert exc.error_type in {"playwright_missing", "chromium_unavailable"}
        return
    assert path.exists() and path.stat().st_size > 100
    width, height = struct.unpack(">II", path.read_bytes()[16:24])
    assert (width, height) == (WIDTH, HEIGHT)
