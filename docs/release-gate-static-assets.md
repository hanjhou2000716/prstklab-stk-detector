# Release gate and static assets

When a Pages publisher emits `asset-manifest.json`, the local delivery gate
also validates the hashed `app.js`, `styles.css`, and hero asset. This prevents
Telegram WebView from receiving a data release paired with an older shell.
Legacy rollback fixtures without an asset manifest remain readable; new
publishers must build and validate the manifest before upload.
