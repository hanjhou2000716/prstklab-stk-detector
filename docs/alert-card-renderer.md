# Alert card renderer

`src/alert_card_renderer.py` produces a fixed 1080x1350 PNG using Playwright
and Chromium.  The production workflows install both the Python dependencies
and the pinned Playwright browser before any delivery job runs.

The renderer validates dimensions and pixel content after the screenshot.  If
Playwright, Chromium, Pillow, or the screenshot is unavailable, it raises a
typed `RendererError`.  Scheduled delivery records `renderer_error_type` and
stops before calling Telegram `sendPhoto`; it never sends a solid or blank
fallback image.

`fallback_card()` exists only for offline diagnostics and unit fixtures.  It is
not a delivery fallback.  After fixing the runtime, rerun the delivery job;
the release gate and the normal retry path remain intact.
