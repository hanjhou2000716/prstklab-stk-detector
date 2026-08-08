# Alert card renderer

`src/alert_card_renderer.py` produces a fixed 1080×1350 PNG.  CI/runtime uses
Playwright when Chromium is available; a deterministic PNG fallback is emitted
when the browser or font is unavailable.  This keeps Telegram `sendPhoto`
shape stable without inventing market data.  Renderer errors are represented by
the fallback card and must remain visible in the release audit.
