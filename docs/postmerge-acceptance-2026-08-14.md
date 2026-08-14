# Post-merge acceptance evidence — 2026-08-14

## Main verification

- Main commit: `d92fe65eb3ee774c10883bde151215b7b19217a7`
- Full regression: **1,228 passed, 1 skipped** (local non-OneDrive temp
  directory)
- Ruff: pass
- Mypy: pass (`166` source files)
- Python compileall: pass
- Mini App JavaScript syntax: pass
- Runtime audit: `ok=true`, no invariant issues

The first OneDrive-rooted run is recorded as an environment failure (`WinError
5` while pytest enumerated the shared temp directory). The same suite was then
rerun from a local non-OneDrive temporary directory; this is the authoritative
post-merge evidence. The raw-observation directory-race fix is covered by
targeted tests and CI in PR #614.

## Pages

Read-only public checks returned HTTP 200 for the dashboard and `app.js`.
`release-manifest.json` reported `status=ready` with release
`release-957714e850293f39`, market snapshot `c7466b534b3d117e`, research
snapshot `research-8b8ec8f6e5ee51aa`, and event snapshot
`event-f67c25c9f5e6f24d`. The app bundle contains the manifest loader.

## Railway

The public `/health` endpoint returned HTTP 200 and runtime `healthy`; the
monitor was running and Jin10 was healthy. Gmail now reports
`configuration_missing` (the prior standalone `ModuleNotFoundError` is gone).
GDELT is explicitly `failed` with `HTTP_429`, not live and not alertable; the
health callback is `permission_denied`/`HTTP_403` and remains bounded. Delivery
is now `delivered`. Controlled photo acceptance completed with the approved
single recipient only: Actions run `31827926863` / job `94856425277` completed
successfully. The log reports `photo_card_dimensions=1080x1350`,
`photo_delivery_delivered=1`, and `photo_delivery_failed=0`; the Telegram
button was built with alert, release and snapshot deep-link parameters.
Railway receipt trace `photo-smoke-07dbd32ec6474fec` reports `delivered`,
`recipient_count=1`, `receipt_matches_last_outbox=true`, and no failed
recipients.

## Remaining external gates

- Configure/authorize Railway Gmail watch and health callback permissions.
- Recipient UI visual confirmation is not represented by the API receipt; the
  delivery contract and deep-link payload are verified by Actions and Railway.
- Verify live source freshness after the next successful market/research
  release.

Exactly one controlled production Telegram photo was sent to the approved test
recipient; no broadcast was performed.

## Rollback

Revert the relevant merge commit. This document has no runtime or data-release
side effect.
