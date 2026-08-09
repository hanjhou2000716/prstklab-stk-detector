# Alert card renderer

`src/alert_card_renderer.py` produces a fixed 1080x1350 PNG using Playwright
and Chromium. It is a development/visual-preview and explicitly scoped
`photo_test` dependency; scheduled, official-event and emergency production
workflows use `requirements-production.txt` and never install a browser.

The renderer validates dimensions and pixel content after the screenshot.  If
Playwright, Chromium, Pillow, or the screenshot is unavailable, it raises a
typed `RendererError`.  The scoped photo smoke records `renderer_error_type`
and stops before calling Telegram `sendPhoto`; production text delivery does
not depend on the renderer and never sends a solid or blank fallback image.

`fallback_card()` exists only for offline diagnostics and unit fixtures.  It is
not a delivery fallback.  After fixing the runtime, rerun the delivery job;
the release gate and the normal retry path remain intact.
