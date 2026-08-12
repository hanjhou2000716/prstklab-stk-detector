"""Deterministic 1080x1350 alert-card renderer.

Production delivery is fail-closed: a missing Playwright/Chromium runtime or
an invalid screenshot raises :class:`RendererError` and the caller must not
send a photo.  ``fallback_card`` is retained only for offline diagnostics and
unit fixtures; it is never a Telegram delivery fallback.
"""
from __future__ import annotations

import struct
from html import escape
from pathlib import Path
from typing import Any

WIDTH, HEIGHT = 1080, 1350


class RendererError(RuntimeError):
    """The card could not be rendered or failed post-render validation."""

    def __init__(self, error_type: str, message: str | None = None) -> None:
        self.error_type = error_type
        super().__init__(message or error_type)


def _png(width: int = WIDTH, height: int = HEIGHT) -> bytes:
    """Create a visible diagnostic PNG without a native image dependency.

    This is deliberately not used by production delivery.  The two-tone image
    makes accidental use obvious in local fixtures instead of looking like a
    valid but empty black card.
    """
    import zlib

    def chunk(name: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + name
            + data
            + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)
        )

    rows = []
    for y in range(height):
        color = (202, 94, 38) if y < 8 else (17, 28, 46)
        rows.append(b"\x00" + bytes(color) * width)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b"")


def fallback_card(path: str | Path) -> Path:
    """Write a diagnostic-only card for tests and local troubleshooting."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_png())
    return target


def build_card_html(alert: dict[str, Any]) -> str:
    title = escape(str(alert.get("title") or "PRStK 市場情報"))
    state = escape(str(alert.get("lifecycle_state") or "observation"))
    reason = escape(str(alert.get("trigger_reason") or "資料整理與核對中"))
    release_id = escape(str(alert.get("release_id") or "待核對"))
    snapshot_id = escape(str(alert.get("snapshot_id") or "待核對"))
    def text(key: str, default: str) -> str:
        value = alert.get(key)
        return escape(str(value if value not in (None, "") else default))

    def evidence(key: str, default: str) -> str:
        value = alert.get(key)
        if isinstance(value, (list, tuple)):
            value = "；".join(str(item) for item in value if item not in (None, ""))
        return escape(str(value if value not in (None, "") else default))

    event = text("event", "公開事件資料整理中，等待核對。")
    importance = text("importance", "重要性仍需以公開來源與市場反應確認。")
    transmission = text("market_transmission", "尚無足夠市場證據判定傳導方向。")
    watch = text("watch", "觀察後續官方資料與可比較行情。")
    sources = evidence("source_evidence", "來源核對狀態：待核對。")
    market = evidence("market_evidence", "市場同步狀態：待核對。")
    invalidation = text("invalidation_condition", "若來源或行情核對不成立，取消本次判定。")
    return f"""<!doctype html>
<html lang="zh-Hant"><meta charset="utf-8">
<style>
html,body{{margin:0;width:{WIDTH}px;height:{HEIGHT}px;background:#f4f2ed;color:#102f4b;font-family:Arial,'Noto Sans CJK TC',sans-serif}}
main{{box-sizing:border-box;padding:64px 72px;width:100%;height:100%}}
.brand{{font-size:26px;letter-spacing:4px;color:#c85d27;font-weight:700}}
h1{{font-size:58px;line-height:1.18;margin:34px 0 30px}}
.state{{display:inline-block;background:#c85d27;color:#fff;font-size:30px;padding:12px 22px;border-radius:12px}}
.panel{{margin-top:32px;background:#fff;border:2px solid #d3d9dd;border-radius:24px;padding:28px}}
.panel p{{font-size:30px;line-height:1.34;margin:0 0 16px}}
.label{{color:#c85d27;font-weight:700}}
.meta{{font-size:22px;line-height:1.55;color:#4b6378}}
.footer{{position:absolute;left:72px;bottom:62px;font-size:20px;color:#4b6378}}
</style><main><div class="brand">PRStK MARKET INTELLIGENCE</div>
<h1>{title}</h1><div class="state">狀態｜{state}</div>
<section class="panel"><p>{reason}</p><div class="meta">release｜{release_id}<br>snapshot｜{snapshot_id}</div></section>
<div class="footer">僅供公開資訊整理與教育性觀察，不構成投資建議。</div>
</main><section class="panel"><p><span class="label">事件：</span>{event}</p><p><span class="label">為何重要：</span>{importance}</p><p><span class="label">可能連動：</span>{transmission}</p><p><span class="label">股市觀察：</span>{watch}</p><p><span class="label">來源：</span>{sources}</p><p><span class="label">行情核對：</span>{market}</p><p><span class="label">失效條件：</span>{invalidation}</p></section></html>"""


def _validate_png(target: Path) -> None:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - exercised in deployment
        raise RendererError("pillow_missing", "Pillow is required to validate alert cards") from exc
    try:
        with Image.open(target) as image:
            if image.size != (WIDTH, HEIGHT):
                raise RendererError("invalid_dimensions", f"expected {WIDTH}x{HEIGHT}, got {image.size}")
            rgb = image.convert("RGB")
            colors = rgb.getcolors(maxcolors=1024)
            if colors is not None and len(colors) <= 1:
                raise RendererError("blank_image", "rendered card is a single color")
            if rgb.getbbox() is None:
                raise RendererError("blank_image", "rendered card has no visible pixels")
    except RendererError:
        raise
    except Exception as exc:
        raise RendererError("invalid_png", str(exc)) from exc


def render_alert_card(alert: dict[str, Any], output: str | Path) -> Path:
    """Render and validate a card; never silently return a blank fallback."""
    target = Path(output)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RendererError("playwright_missing", "Playwright is required for production card delivery") from exc
    browser = None
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1)
            page.set_content(build_card_html(alert), wait_until="load")
            target.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(target), type="png", full_page=False)
        _validate_png(target)
        return target
    except RendererError:
        raise
    except Exception as exc:
        error_type = "chromium_unavailable" if "browser" in str(exc).lower() or "executable" in str(exc).lower() else "render_failed"
        raise RendererError(error_type, str(exc)) from exc
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
