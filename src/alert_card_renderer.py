"""Deterministic 1080x1350 alert-card renderer with a safe fallback."""
from __future__ import annotations

import struct
import zlib
from html import escape
from pathlib import Path
from typing import Any

WIDTH, HEIGHT = 1080, 1350

def _png(width: int = WIDTH, height: int = HEIGHT, rgb: tuple[int, int, int] = (17, 28, 46)) -> bytes:
    """Create a valid solid PNG without a native image dependency."""
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    def chunk(name: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data) & 0xffffffff)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")

def fallback_card(path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_png())
    return target

def build_card_html(alert: dict[str, Any]) -> str:
    title = escape(str(alert.get("title") or "PRStK 市場情報"))
    state = escape(str(alert.get("lifecycle_state") or "observation"))
    reason = escape(str(alert.get("trigger_reason") or "本輪資訊待核對"))
    return f"""<!doctype html><html lang='zh-Hant'><meta charset='utf-8'><style>html,body{{margin:0;width:{WIDTH}px;height:{HEIGHT}px;background:#111c2e;color:#fff;font-family:Arial,sans-serif}}main{{box-sizing:border-box;padding:72px;width:100%;height:100%}}h1{{font-size:56px;line-height:1.2}}p{{font-size:34px;line-height:1.45;background:#203f5d;padding:28px;border-radius:20px}}</style><main><h1>PRStK 市場情報</h1><p>{title}</p><p>狀態：{state}</p><p>{reason}</p></main></html>"""

def render_alert_card(alert: dict[str, Any], output: str | Path) -> Path:
    """Render with Playwright when installed; otherwise emit deterministic fallback."""
    target = Path(output)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return fallback_card(target)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1)
            page.set_content(build_card_html(alert), wait_until="load")
            target.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(target), type="png", full_page=False)
            browser.close()
        return target
    except Exception:
        return fallback_card(target)
