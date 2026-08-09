"""Browser-level contract checks for the investor-facing Mini App shell."""

from __future__ import annotations

import functools
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

try:  # Keep local/offline unit runs usable when Chromium is not installed.
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - minimal environments
    sync_playwright = None  # type: ignore[assignment]


SITE_ROOT = Path(__file__).resolve().parents[1] / "site"


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return


@pytest.mark.skipif(sync_playwright is None, reason="Playwright is not installed")
def test_mini_app_investor_shell_and_drawer_contract() -> None:
    """Verify real DOM defaults and the one investor opt-in technical drawer."""

    handler = functools.partial(_QuietHandler, directory=str(SITE_ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.route("**/telegram.org/**", lambda route: route.abort())
            page.goto(
                f"http://127.0.0.1:{server.server_port}/index.html?e2e=ui-contract",
                wait_until="domcontentloaded",
            )

            assert page.locator("#briefing-report").get_attribute("open") == ""
            assert page.locator("#source-health").get_attribute("open") is None
            assert page.locator("#briefing-intelligence").get_attribute("open") is None
            assert page.locator(".technical-details").count() >= 2
            assert page.locator(".technical-details[open]").count() == 0

            body_text = page.locator("body").inner_text()
            assert "歷史百分位未取得" not in body_text
            assert "資料 2026-" not in body_text

            technical = page.locator("#briefing-report > .technical-details")
            technical.locator("summary").click()
            assert technical.get_attribute("open") == ""
            browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc) or "executable doesn't exist" in str(exc):
            pytest.skip("Playwright Chromium is not installed")
        raise
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
