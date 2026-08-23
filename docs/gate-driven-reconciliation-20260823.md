# Gate-Driven reconciliation — 2026-08-23

This is the migration checkpoint for the Creator Intelligence, FinancialJuice,
News and production-delivery work.  It is an evidence ledger, not a claim that
external providers are healthy.  The audit starts from the current `main` and
does not resurrect or merge historical stacked branches.

## Snapshot

| Item | Observed value |
|---|---|
| Repository | `hanjhou2000716/prstklab-stk-detector` |
| `origin/main` | `314c047845bab508bc5e45d27cd22b3f8f15be23` |
| `origin/data-release` | `81135899c40c1dac670fc8dce4b702e72877eeb1` |
| Open PRs at audit time | none |
| Working tree | clean on `feat/gate-driven-reconciliation` |
| Local regression | 1,358 passed, 0 failed, 0 skipped |
| Browser contract | 2 passed with Playwright Chromium 1.62.0 |
| Canonical overlap | pass; zero drift and zero missing generated bundles |
| Python/JavaScript syntax | pass (`compileall`, `node --check`) |
| Ruff | pass (`ruff check src tests`) |
| Mypy | pass (`mypy src`, 177 source files) |

## Canonical pipeline decision

The following are the only production owners for their respective boundaries:

| Boundary | Canonical owner | Railway/generated copy | Evidence |
|---|---|---|---|
| Creator identity and routing | `src/creator_provider_registry.py` + `config/creator_providers.json` | `railway-monitor/creator_providers.json` | `scripts/verify_canonical_overlap.py` |
| Creator/Jenny parsing | `src/external_source_parsers.py` and `src/creator_source_adapters.py` | generated `railway-monitor/src/*` bundle | `scripts/sync_railway_canonical_parser.py --check` |
| FinancialJuice contract and risk boundary | `src/financialjuice_contract.py` + `src/external_event_risk.py` | generated Railway parser bundle | vendor priority is not PRStK risk |
| Event classification | `src/event_classifier.py` | `railway-monitor/shared_event_classifier.py` | generated hash parity |
| Public News normalization | `src/news_intelligence.py` + `src/news_feed_adapters.py` | none; Railway only reports source health | provider registry and URL-safety tests |
| Release and notification | `src/release_manifest.py` + `src/release_gate.py` | Railway receipt/outbox only | publish-before-notify tests |

No second Creator, FinancialJuice, or event-classifier implementation may be
introduced.  Railway files are generated compatibility bundles, not a second
source of truth.

## Requirement / evidence reconciliation

The original P0-01…P0-29 rows remain in
[`docs/p0-requirement-traceability.md`](p0-requirement-traceability.md).  The
following records the current evidence boundary after the migration audit.

| Requirement group | Implementation and verification | Current state |
|---|---|---|
| Artifact schemas, invariants, release manifest and hash gate | `src/artifact_contract.py`, `src/release_manifest.py`, `src/release_gate.py`; release and artifact suites pass | PASS / LOCKED |
| Market provenance, cross-check and freshness | market provenance/cross-check/freshness suites pass; stale data remains visible but cannot alert | PASS / LOCKED |
| Research candidate state and Advice Gate | research state, strategy registry, explainability and advice-gate suites pass; no valid backtest release means observation-only | PASS / LOCKED |
| Event classifier, evidence, lifecycle, budget and ledger | canonical classifier overlap pass; event/evidence/lifecycle/dedup suites pass | PASS / LOCKED |
| Telegram delivery contract and photo renderer | caption/lifecycle/photo/sendPhoto/receipt suites pass; controlled photo smoke previously delivered one scoped recipient | PASS / LOCKED (external reverify retained) |
| Mini App release loader and deep links | browser contract 2/2 pass; release mismatch and archived-release fallbacks covered | PASS / LOCKED |
| Creator registry, sanitized parsing and media boundary | creator provider, parser, privacy, media and release-lineage suites pass | PASS / LOCKED (fresh production input still external) |
| Creator morning batch and consensus | batch, consensus, correlation and briefing integration suites pass | PASS / LOCKED |
| FinancialJuice compound parsing and vendor-priority separation | compound envelope, parser, priority and notification suites pass | PASS / LOCKED (Railway ingress evidence external) |
| News provider routing, relevance, dedup and URL safety | news adapter, market-scope, interest-graph and browser suites pass | PASS / LOCKED |
| Railway health, retry, GDELT and Gmail boundaries | health/dispatch/cache/Gmail suites pass; 401/403/429 semantics are fail-closed | PASS / LOCKED (live provider reverify required) |
| Backup, rollback and disaster recovery | release/data rollback and tamper-detection suites pass | PASS / LOCKED |

`PASS / LOCKED` above means the implementation and regression contract are
verified locally.  It does not convert a provider outage or missing external
credential into a healthy state.

## Verification commands and results

The audit was run from a clean worktree based on `origin/main`:

```text
python scripts/verify_canonical_overlap.py
python scripts/sync_railway_canonical_parser.py --check
python -m compileall -q src railway-monitor
node --check site/app.js
python -m pytest -q --basetemp=<isolated-temp>
python -m pytest -q tests/test_mini_app_browser_contract.py --basetemp=<isolated-temp>
python -m src.system_dry_run
python -m src.production_acceptance --manifest <data-release-manifest> --site-root <data-release-site>
```

Observed results:

- `verify_canonical_overlap`: pass, `failed_count=0`.
- Full regression: `1,358 passed, 0 failed, 0 skipped`.
- Mini App browser contract: `2 passed` with the declared Playwright dependency
  and Chromium installed.
- Offline dry-run: pass; lifecycle is `pending_confirmation`, advice is
  `observation_only`, photo contract is `1080x1350`, and delivery is mocked.
- Data-release production acceptance: pass for the immutable ready manifest;
  checked-in stale/invalid `main/site/data` is not promoted.

## External gates that remain open

The post-merge read-only capture is recorded in
[`docs/evidence/external-acceptance-2026-08-23.json`](evidence/external-acceptance-2026-08-23.json)
from Actions run `32639107890` at main `029ea3b87599afffb349f3909c1ac406ec7ba28e`.
It confirms Railway/Pages reachability and hash integrity without any write or
Telegram side effect, while retaining the two provider failures below.

These are intentionally not inferred from local tests:

| Gate | Latest observed state | Safe policy |
|---|---|---|
| Gmail Watch / Pub/Sub | OAuth/watch path previously returned HTTP 403 | report configuration/authorization failure; never treat it as no mail |
| GDELT discovery | upstream returned HTTP 429 | bounded backoff/cache; discovery-only; no high-risk promotion |
| FinancialJuice Railway ingress | requires a fresh sanitized observation bundle in a ready release | keep source unavailable/pending until lineage is observed |
| Railway restart continuity | not proven by local tests | keep receipt/watch/classification continuity as NEEDS_REVERIFY |
| Formal backtest | current production release reports unavailable | Advice Gate remains observation-only |

If a new release fails schema, hash, freshness, or public propagation checks,
the previous successful release remains public and no Telegram notification is
sent.  This is the required fail-closed rollback path.

## Regression and completion debt

- No duplicate canonical provider/classifier drift was found.
- No open local regression was found in the 1,358-test run.
- External completion debt remains for Gmail authorization, GDELT rate-limit
  recovery, FinancialJuice Railway observation, and Railway restart continuity.
- No production broadcast or secret value was used during this audit.

The project may continue from this checkpoint without restarting P0 work.  Any
future change touching a locked boundary must reopen its row, rerun the listed
targeted tests and the full regression, then relock it with new evidence.
