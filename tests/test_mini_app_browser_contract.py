"""Browser-level contract checks for the investor-facing Mini App shell."""

from __future__ import annotations

import functools
import hashlib
import json
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
            assert page.locator("#briefing-intelligence").get_attribute("hidden") is None
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


@pytest.mark.skipif(sync_playwright is None, reason="Playwright is not installed")
def test_mini_app_renders_financialjuice_evidence_from_release_fixture() -> None:
    """Exercise the real release loader and FJ evidence renderer together.

    The static contract tests prove that the labels exist in ``app.js``.  This
    fixture goes one step further: it serves a self-consistent, hash-bound
    release through the same fetch path used by Pages and asserts that a
    FinancialJuice row is actually rendered with vendor priority separated
    from PRStK risk and with an explicit pending-evidence state.
    """

    market = {
        "snapshot_id": "market-fixture-20260822",
        "generated_at": "2026-08-22T02:00:00+00:00",
        "data_status": "資料可用",
        "markets": {},
        "indices": [],
        "quotes": [],
        "events": {"items": []},
        "risk": {},
        "briefing": {},
        "source_health": {"sources": []},
        "external_observations": [
            {
                "observation_id": "obs-fj-fixture-1",
                "source_key": "financialjuice",
                "source": "FinancialJuice",
                "title": "公開外部事件（測試）",
                "summary": "等待官方與市場證據核對。",
                "official_confirmed": False,
                "market_sync_confirmed": False,
                "vendor_importance": 9,
                "prstk_risk": {"prstk_risk_level": "R2"},
                "release_id": "release-fj-fixture-20260822",
                "snapshot_id": "market-fixture-20260822",
                "published_at": "2026-08-22T01:59:00+00:00",
                "fetched_at": "2026-08-22T02:00:00+00:00",
                "source_url": "https://example.com/financialjuice-fixture",
            }
        ],
        "financialjuice_priority_decisions": [
            {
                "observation_id": "obs-fj-fixture-1",
                "notification_status": "eligible",
                "vendor_importance": 9,
                "notification_reason": "供應商重要度達 8/10",
            }
        ],
        "financialjuice_priority_events": [],
    }
    market_text = json.dumps(market, ensure_ascii=False, separators=(",", ":"))
    manifest = {
        "release_id": "release-fj-fixture-20260822",
        "status": "ready",
        "created_at": "2026-08-22T02:00:00+00:00",
        "market_snapshot_id": "market-fixture-20260822",
        "artifact_hashes": {"market.json": hashlib.sha256(market_text.encode()).hexdigest()},
        "artifact_paths": {"market.json": "data/market.json"},
    }
    manifest_text = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))

    handler = functools.partial(_QuietHandler, directory=str(SITE_ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()

            def fulfill_release(route) -> None:  # type: ignore[no-untyped-def]
                url = route.request.url
                if "/data/release-manifest.json" in url:
                    route.fulfill(status=200, content_type="application/json", body=manifest_text)
                elif "/data/market.json" in url:
                    route.fulfill(status=200, content_type="application/json", body=market_text)
                else:
                    route.continue_()

            page.route("**/data/**", fulfill_release)
            page.goto(
                f"http://127.0.0.1:{server.server_port}/index.html?e2e=financialjuice-ui",
                wait_until="domcontentloaded",
            )
            # The external panel is intentionally collapsed by default, so
            # wait for the rendered node rather than its visibility.
            page.wait_for_selector("#external-intelligence-content .external-insight", state="attached")

            external = page.locator("#external-intelligence-content .external-insight").first
            rendered = external.text_content() or ""
            for expected in (
                "公開外部事件（測試）",
                "FinancialJuice｜等待官方核對／市場同步",
                "供應商優先：可通知｜供應商重要度達 8/10",
                "來源重要度：9/10（不等同 PRStK 風險）",
                "PRStK Risk：R2",
                "發布鏈：release release-fj-fixture-20260822｜snapshot market-fixture-20260822｜observation obs-fj-fixture-1",
                "資料時間：",
                "等待官方與市場證據核對。",
                "公開來源",
            ):
                assert expected in rendered
            assert page.locator("#external-intelligence").get_attribute("hidden") is None
            browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc) or "executable doesn't exist" in str(exc):
            pytest.skip("Playwright Chromium is not installed")
        raise
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
