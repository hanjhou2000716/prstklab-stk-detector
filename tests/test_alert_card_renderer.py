import importlib.util
import struct
import sys
import types

import pytest

from src.alert_card_renderer import (
    HEIGHT,
    WIDTH,
    RendererError,
    _validate_png,
    build_card_html,
    fallback_card,
    render_alert_card,
)


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


def test_card_html_escapes_fields_and_keeps_required_contract():
    html = build_card_html({"title": "<script>", "lifecycle_state": "confirmed", "trigger_reason": "&", "release_id": "r", "snapshot_id": "s"})
    assert "&lt;script&gt;" in html
    assert "<script>" not in html
    assert "release" in html and "snapshot" in html


def test_card_html_uses_safe_defaults():
    html = build_card_html({})
    assert "PRStK" in html
    assert "observation" in html


def test_validate_png_rejects_corrupt_file(tmp_path):
    pytest.importorskip("PIL.Image")
    target = tmp_path / "corrupt.png"
    target.write_bytes(b"not-a-png")
    with pytest.raises(RendererError):
        _validate_png(target)


def test_renderer_uses_injected_playwright_runtime(monkeypatch, tmp_path):
    target = tmp_path / "rendered.png"
    class Page:
        def set_content(self, *args, **kwargs): return None
        def screenshot(self, *, path, **kwargs): fallback_card(path)
    class Browser:
        def new_page(self, **kwargs): return Page()
        def close(self): return None
    class Context:
        def __enter__(self): return types.SimpleNamespace(chromium=types.SimpleNamespace(launch=lambda **kwargs: Browser()))
        def __exit__(self, *args): return None
    module = types.ModuleType("playwright.sync_api")
    module.sync_playwright = lambda: Context()
    package = types.ModuleType("playwright")
    monkeypatch.setitem(sys.modules, "playwright", package)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", module)
    result = render_alert_card({"title": "x"}, target)
    assert result == target and target.exists()


def test_validate_png_rejects_single_color_and_wrong_dimensions(tmp_path):
    pytest.importorskip("PIL.Image")
    from PIL import Image

    single = tmp_path / "single.png"
    Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0)).save(single)
    with pytest.raises(RendererError, match="single color"):
        _validate_png(single)
    wrong = tmp_path / "wrong.png"
    Image.new("RGB", (10, 10), (0, 0, 0)).save(wrong)
    with pytest.raises(RendererError, match="expected"):
        _validate_png(wrong)
