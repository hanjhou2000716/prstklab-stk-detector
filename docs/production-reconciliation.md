# Production reconciliation (2026-08-09)

`main` is the only production source of truth. A merged PR is only production when its commit is an ancestor of `origin/main` and the files are present on `main`.

## Current baseline

| Area | Main evidence | State | Action |
| --- | --- | --- | --- |
| Release manifest / Pages gate | `src/release_gate.py`, `site/data/release-manifest.json`, PR #323 | production | keep |
| Immutable data release writer | `src/data_release.py`, PR #304 | production | keep |
| Alert lifecycle / budget | `src/alert_contract.py`, `src/alert_lifecycle.py`, PR #305 | production | keep |
| Source health and research state | `src/research_health.py`, `src/source_health.py`, PRs #306--311 | partial_in_main | verify before extending |
| Intelligence evidence | `src/market_impact_graph.py`, `src/macro_surprise.py`, PRs #264--289 | production | keep |
| Offline delivery and CI gates | `.github/workflows/quality.yml`, `src/system_dry_run.py`, PR #290 | production | keep |
| Renderer recovery | `src/alert_card_renderer.py`, `site/app.js`, PR #323 | production_photo | scheduled, official-event and emergency delivery render a validated 1080x1350 card and fail closed on renderer errors |
| Telegram production transport | `src/telegram_client.py`, `src/scheduled_delivery.py`, PRs #346/#427 | photo_production | release-gated `sendPhoto` with a deep-link button; photo smoke remains available for one-recipient diagnostics |

## Branch / PR inventory

PRs #284--#305 and #312--#323 are merged to `main` and their merge commits are present in the current `origin/main`. PRs #306--#311 are open stacked branches whose scope is represented partially by later merged work. They must not be merged as a stale stack; re-create only demonstrated gaps from latest `main`.

The current `main` baseline already contains the production photo transport. Do not use the older #351/#352 text-transport notes as merge instructions; they are historical stack artifacts. PR #450 is a separate MOPS provider-resilience fix and remains reviewable against `main`.

## Verification

```powershell
git fetch origin --prune
git merge-base --is-ancestor <merge-sha> origin/main
git show origin/main:src/release_gate.py
git show origin/main:site/app.js
```

This document is additive and has no runtime migration. Roll back by reverting its commit.
