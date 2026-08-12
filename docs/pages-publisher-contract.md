# Pages publisher contract

Every workflow that uploads a Pages artifact must rebuild and validate the
cache-busted static asset manifest after restoring and updating `data-release`.
This prevents a refreshed data snapshot from being served with an older
`app.js`, stylesheet, or hero asset in Telegram WebView.

The contract is fail-closed: `src.build_assets` or `src.asset_contract` failure
stops the publisher before upload. `deploy-pages.yml` remains the full release
gate; event, briefing, dashboard, emergency and monitor publishers now share
the same static-asset boundary.

Rollback: revert this PR. The immutable `data-release` snapshot remains
available for the previous successful Pages deployment.
