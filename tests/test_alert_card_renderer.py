import struct

from src.alert_card_renderer import HEIGHT, WIDTH, fallback_card, render_alert_card


def test_fallback_card_is_fixed_png(tmp_path):
    path = fallback_card(tmp_path / "fallback.png")
    data = path.read_bytes()
    assert data.startswith(b"\x89PNG")
    width, height = struct.unpack(">II", data[16:24])
    assert (width, height) == (WIDTH, HEIGHT)

def test_renderer_has_safe_fallback(tmp_path):
    path = render_alert_card({"title": "測試", "lifecycle_state": "observation"}, tmp_path / "alert.png")
    assert path.exists() and path.stat().st_size > 100
