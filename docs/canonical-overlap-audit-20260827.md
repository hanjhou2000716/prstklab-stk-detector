# Canonical overlap audit — 2026-08-27

This checkpoint records the migration audit performed on the current
`feat/t6-quality-security-e2e` tree.  It is a reconciliation artifact, not a
claim that the external Railway or Telegram acceptance gates are complete.

## Canonical ownership

The production paths remain single-owner:

| Capability | Canonical producer | Consumer path | Result |
|---|---|---|---|
| Creator Intelligence | `src/creator_intelligence_pipeline.py` | briefing release → Mini App / opt-in delivery | PASS (offline) |
| FinancialJuice | `src/financialjuice_contract.py` + `src/financialjuice_priority.py` | sanitized external observation → release projection | PASS (offline) |
| News classification | `src/news_intelligence.py` + `src/event_classifier.py` | Taiwan/US scoped news artifact | PASS (offline) |
| Release gate | `src/release_manifest.py` + `src/release_gate.py` | Pages publish → notification decision | PASS (offline) |
| Telegram delivery | `src/telegram_client.py` and release-gated callers | per-recipient receipt | PASS (offline) |
| Gmail Watch | `railway-monitor/gmail_watch.py` via `GmailWatchManager` | Railway ingress and health projection | PASS (overlap audit) |
| Railway generated bundles | `scripts/sync_railway_canonical_parser.py` | standalone monitor image | PASS (bundle check) |

No second Creator provider registry, FinancialJuice parser, news classifier,
release gate, or Telegram dispatcher was introduced by this continuation.
Compatibility wrappers remain transport adapters and do not own policy.

## Objective evidence

The following read-only checks were executed from the repository checkout:

```text
python scripts/verify_canonical_overlap.py       # status: pass, failed_count: 0
python scripts/sync_railway_canonical_parser.py --check  # status: pass
python scripts/sync_railway_shared_classifier.py --check # status: pass
python scripts/verify_intelligence_contracts.py  # status: pass
```

Focused contract suites are green:

```text
Creator / FinancialJuice / external intelligence: 38 passed
Release / renderer / Telegram / Mini App / Pages: 118 passed
```

The full local suite on this tree is green (`1493 passed` in CI run
`33074923588`). Ruff, Mypy, compilation, offline delivery, and the core
coverage gate also passed; the project coverage was 81.19% and the core
release/delivery coverage was 90.03%.

## Reconciled external gates

These remain explicitly `OPEN` in `config/gate_evidence.json` and must not be
silently changed to PASS by an offline test:

- `REG-GDELT-429` / `DEBT-GDELT-001`: observe a successful post-backoff poll.
- `REG-GMAIL-PERSISTENCE` / `DEBT-GMAIL-PERSISTENCE-001`: mount Railway
  `/data`, restart the service, and capture
  `storage.restart_continuity=verified`.
- `REG-UX-001` / `DEBT-UX-001`: complete a controlled non-broadcast Telegram
  WebView interaction check.

The current local runtime audit therefore remains fail-closed when the checked
in `site/data` manifest is invalid or incomplete.  No stale or unverified
artifact is promoted, and no production Telegram broadcast is implied by this
document.

The latest sanitized Railway probe is recorded in
[`docs/evidence/railway-volume-probe-2026-08-27.json`](evidence/railway-volume-probe-2026-08-27.json):
the service endpoints returned HTTP 404, so the previously attached Volume is
not yet accompanied by a reachable deployment or restart-continuity evidence.

The Railway control plane was checked again on 2026-08-27.  It reports the
`/data` Volume attached at 500 MB, but the service is offline with no active
deployment and the workspace trial is expired.  This control-plane evidence is
kept separately from the HTTP probe in
[`docs/evidence/railway-control-plane-2026-08-27.json`](evidence/railway-control-plane-2026-08-27.json).
It does not establish a successful redeploy or restart-continuity proof.

The post-refresh acceptance on 2026-08-29 verified the Cloudflare Worker and
Pages release path. Railway callback permission is therefore closed under the
approved observability-only fallback; the remaining Railway item is Gmail
restart continuity, which still requires a reachable deployment and restart
probe. See
[`docs/evidence/external-acceptance-after-refresh-20260829.md`](evidence/external-acceptance-after-refresh-20260829.md).

## Rollback

Reverting the checkpoint commit removes only this audit note.  Existing release
gate, source-quality, privacy, and notification behavior is unchanged.
