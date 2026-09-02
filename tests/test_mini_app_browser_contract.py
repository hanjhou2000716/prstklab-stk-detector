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
            assert page.locator("#briefing-system-analysis").get_attribute("open") is None
            assert page.locator("#briefing-system-analysis").get_attribute("hidden") is None
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
        "events": {
            "items": [{
                "kind": "external_event",
                "source": "FinancialJuice",
                "source_key": "financialjuice",
                "brief_title": "FJ 快訊｜重要度 10/10｜伊朗：美國攻擊電信和通信基礎設施。",
                "title": "伊朗：美國攻擊電信和通信基礎設施。",
                "event": "伊朗：美國攻擊電信和通信基礎設施。",
                "why_important": "來源快訊標示重要度 10/10；來源影響評估：可能推升全球風險溢酬；仍待官方或第二來源核對。",
                "possible_linkage": "可能影響美股與美國利率預期。關聯市場：NASDAQ、US10Y（資料待更新）。",
                "stock_observation": "NASDAQ、US10Y 為主要關聯市場，目前尚未出現明顯同步異動，持續觀察。",
                "linked_markets": ["NASDAQ", "US10Y"],
                "market_evidence": [
                    {
                        "ticker": "NASDAQ",
                        "name": "那斯達克綜合指數",
                        "price": 26099.77,
                        "change": -271.12,
                        "change_percent": -1.03,
                        "quote_date": "2026-09-01",
                        "quote_source": "Yahoo Finance public daily quote",
                        "freshness": "recent_close",
                        "data_status": "最近收盤",
                        "stale_used": False,
                    },
                    {
                        "ticker": "US10Y",
                        "name": "美國10年債殖利率",
                        "price": 4.79,
                        "change": -0.01,
                        "change_percent": -0.21,
                        "quote_date": "2026-09-02",
                        "quote_source": "Yahoo Finance public daily quote",
                        "freshness": "recent_close",
                        "data_status": "最近收盤",
                        "stale_used": False,
                    },
                ],
            }],
        },
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
            manifest_failed = False

            def fulfill_release(route) -> None:  # type: ignore[no-untyped-def]
                url = route.request.url
                if "/data/release-manifest.json" in url:
                    if manifest_failed:
                        route.fulfill(
                            status=200,
                            content_type="application/json",
                            body=json.dumps({"status": "invalid", "validation_errors": ["fixture failure"]}),
                        )
                    else:
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
            alert = page.locator("#alert-card")
            alert_text = alert.text_content() or ""
            for expected in (
                "伊朗：美國攻擊電信和通信基礎設施。",
                "來源快訊標示重要度 10/10",
                "可能影響美股與美國利率預期",
                "NASDAQ",
                "US10Y",
                "26,099.77",
                "4.79",
                "最近收盤",
            ):
                assert expected in alert_text
            assert "本事件暫無可顯示的公開報價" not in alert_text
            assert page.locator("#briefing-system-analysis").get_attribute("hidden") is None

            # A later invalid publication must keep the same validated release
            # instead of leaving the app in a permanent loading/error state.
            manifest_failed = True
            page.reload(wait_until="domcontentloaded")
            page.wait_for_selector("#external-intelligence-content .external-insight", state="attached")
            assert page.locator("#data-status").text_content() == "資料降級"
            assert "目前沿用上一個成功版本" in (page.locator("#market-focus").text_content() or "")
            assert "資料降級" in (page.locator("#release-health").text_content() or "")
            assert "公開外部事件（測試）" in (page.locator("#external-intelligence-content").text_content() or "")
            browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc) or "executable doesn't exist" in str(exc):
            pytest.skip("Playwright Chromium is not installed")
        raise
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
