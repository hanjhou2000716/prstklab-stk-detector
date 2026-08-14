# Gate-Driven v3 state reconciliation (2026-08-14)

This is a migration checkpoint for the existing stacked implementation.  It
does not replace or reset earlier P0 work.  Statuses are evidence states, not
claims inferred from branch names or previous comments.

## Snapshot

| Field | Evidence |
|---|---|
| Branch | `feat/gmail-observability-contract` |
| HEAD | `976d1ed` (`docs(P0-25): record failure semantics evidence`) |
| Recovery checkpoint | `checkpoint/migration-2026-08-14-current3` (pre-task) |
| Tracked worktree | clean at checkpoint creation; historical untracked test artifacts are preserved and not staged |
| Local regression | `1155 passed` at `261c950` using a fresh isolated Windows temp directory; an earlier OneDrive/temporary run had filesystem-lock failures and was rerun without changing product assertions |
| Static checks | Changed-file Ruff, Mypy, compileall and `node --check site/app.js` passed at `7228915`; full legacy Railway lint remains a separate debt |
| Remote PR | [#583](https://github.com/hanjhou2000716/prstklab-stk-detector/pull/583), open and stacked on #582; remote checks for `261c950` are pending/requires refresh |

## Current task reconciliation

| Task | State | Evidence / next gate |
|---|---|---|
| Canonical NewsStory/provider contract | LOCKED | `tests/test_news_intelligence.py`, full regression |
| Official TWSE/MOPS/SEC/Fed adapters | NEEDS_REVERIFY | `tests/test_news_feed_adapters.py`; failure and 429 isolation; live feed evidence remains external |
| News release artifact production | LOCKED | `schemas/news-release.schema.json`, `news_snapshot_id`/`news_status` and hash written by `release_manifest`; targeted suite passed |
| News release-gate lineage | LOCKED | 59 targeted release/news/Mini App/delivery-gate tests; mismatched market snapshot fails closed |
| News Mini App browser rendering | NEEDS_REVERIFY | static contract loader is verified locally; real ready Pages browser evidence remains external |
| Railway/Telegram production acceptance | BLOCKED | protected runtime configuration and controlled recipient evidence are external prerequisites |
| FinancialJuice sanitized scheduled ingress | partially_integrated | `src/external_observation_input.py` rejects raw/private transport data; Railway sanitized bundle and live release evidence remain external |
| FinancialJuice release lineage and Mini App evidence | NEEDS_REVERIFY | `src/release_manifest.py`, `src/release_gate.py`, `site/app.js`; local contract and mismatch fixtures pass; ready Pages evidence remains external |
| FinancialJuice operational observability | PASS (local) / NEEDS_REVERIFY (external) | `src/external_observation_input.py`, `schemas/source-health.schema.json`, `site/app.js` | 52 targeted tests; source-health schema accepts the observability contract; Railway delivery evidence remains external | no raw/private fields or transport IDs exposed; missing input remains failed, not no-event | NEEDS_REVERIFY |
| Canonical failure semantics | PASS (local) | `src/failure_semantics.py`, `src/creator_health.py` | 8 targeted contract tests; Creator/source-health regression | `no_event` maps to `no_new_content`; parse/provider/configuration/release states remain distinct and fail-closed | PASS (local) |
| REQ-ADD-003 Railway runtime configuration boundary | PASS (local) / NEEDS_REVERIFY (external) | `railway-monitor/runtime_config.py`, `railway-monitor/app.py` | 87 Railway monitor/config tests; changed-file Ruff/Mypy/compile/node checks | canonical and legacy secret names remain compatible; missing/blank configuration is fail-closed and redacted | live Railway health evidence remains external | NEEDS_REVERIFY |

`PASS` is not promoted to `LOCKED` when the required objective evidence is not
available in this checkout.  `LOCKED` is reserved for a task whose local
implementation, required regression, and preservation evidence are all
present; it does not imply that an external production gate has passed.

## Affected requirement traceability

| Requirement | Task | Implementation | Verification | Regression | Status |
|---|---|---|---|---|---|
| REQ-P0-04-DOD-NEWS-01 | Bind News to release | `src/release_manifest.py`, `schemas/release-manifest.schema.json` | 63 targeted; 1133 full regression | mixed-release fixture | LOCKED |
| REQ-P0-05-DOD-NEWS-02 | Verify before notify | `src/release_gate.py` | 63 targeted; 1133 full regression | hash and snapshot mismatch | LOCKED |
| REQ-P0-14-DOD-NEWS-03 | Official source isolation | `src/news_feed_adapters.py`, `src/risk_news.py` | adapter parser/429 tests | one provider failure does not drop others; live endpoint evidence pending | NEEDS_REVERIFY |
| REQ-P0-20-DOD-NEWS-04 | Public UI evidence | `site/app.js` | browser/Pages smoke | release mismatch fallback | NEEDS_REVERIFY |
| REQ-ADD-001-DOD-01 | External intelligence enters canonical briefing only as sanitized observations | `src/external_observation_input.py`, `src/scheduled_delivery.py` | 24 targeted tests; 1139 full regression | raw/private/unknown records rejected; no Pages-path input | LOCKED (local) |
| REQ-ADD-001-DOD-02 | FinancialJuice source health and snapshot lineage remain explicit | `src/external_observation_input.py`, `src/scheduled_delivery.py`, workflow | scheduled snapshot binding test; release gate remains required | missing/rejected input cannot become no-event | NEEDS_REVERIFY (external bundle) |
| REQ-ADD-002-DOD-01 | External observation IDs, sources and status are release-bound | `src/release_manifest.py`, `schemas/release-manifest.schema.json`, `src/release_gate.py` | 78 targeted; 1144 full regression | count/hash/source mismatch blocks delivery; malformed count fails closed | LOCKED (local) |
| REQ-ADD-002-DOD-02 | Mini App exposes the same release-bound external observations and pending reason | `site/index.html`, `site/app.js`, `tests/test_mini_app_assets.py` | static asset contract and full regression | no row is rendered as confirmed without official/market evidence | NEEDS_REVERIFY (Pages browser) |
| REQ-P0-24-DOD-01 | FinancialJuice source health exposes privacy-safe receive/parse/error/qualification state | `src/external_observation_input.py`, `schemas/source-health.schema.json` | `tests/test_external_observation_input.py`, `tests/test_artifact_contract.py` (52 targeted passed) | metrics contain timestamps/counts only; no observation IDs, message IDs, raw content or recipients | missing/malformed input remains failed and cannot be treated as no-event | PASS (local) |
| REQ-P0-24-DOD-02 | Mini App renders FinancialJuice observability and notification pending reason | `site/app.js`, `tests/test_mini_app_assets.py` | Mini App asset contract included in 52 targeted tests | UI shows received time, >=8 count, pending clusters and parser errors; production browser evidence pending | source-health state remains fail-closed | NEEDS_REVERIFY (Pages browser) |
| REQ-P0-24-DOD-03 | Creator source rows expose privacy-safe receive/parse/error/delivery state | `src/creator_source_health.py`, `schemas/source-health.schema.json` | Creator/source-health/artifact suite (91 targeted passed) | timestamps/counts only; Gmail transport IDs are not copied | configuration missing and parser failure remain distinct | PASS (local) |
| REQ-P0-24-DOD-04 | Mini App renders Creator observability beside each optional provider | `site/app.js`, `tests/test_mini_app_assets.py` | asset contract plus 91 targeted tests | creator row remains optional and cannot become core market evidence | Pages browser evidence pending | NEEDS_REVERIFY (Pages browser) |
| REQ-P0-24-DOD-05 | Official News adapters expose fetch/parse/error/latency state per provider | `src/news_feed_adapters.py` | `tests/test_news_feed_adapters.py`, News Intelligence regression (45 targeted passed) | each provider remains isolated; 429 is recorded without retry; no raw response is published | failed provider does not suppress other market stories | PASS (local) |
| REQ-P0-24-DOD-06 | Gmail watch exposes privacy-safe receive/parse/error/delivery state without transport identifiers | `railway-monitor/gmail_watch.py` | `tests/test_railway_gmail_gateway.py` (12 targeted passed) | bounded timestamps/counters only; history/message IDs are excluded; configuration and stale watch remain fail-closed | invalid timestamps/counters do not leak cursor data or become a healthy state | PASS (local) |
| REQ-P0-25-DOD-01 | Shared failure vocabulary distinguishes empty, stale, parse, provider and release failures | `src/failure_semantics.py`, `src/creator_health.py` | `tests/test_failure_semantics.py`, `tests/test_creator_health.py` (8 targeted passed) | legacy `no_event` no longer becomes a provider failure; unknown states fail closed | no content is never promoted to alert-eligible | PASS (local) |
| REQ-ADD-003-DOD-01 | Railway runtime configuration has one standalone, redacted lookup boundary | `railway-monitor/runtime_config.py`, `railway-monitor/app.py` | `tests/test_railway_runtime_config.py`, `tests/test_railway_monitor.py` (87 passed); Ruff/Mypy/compile | both existing variable names remain supported; absent/blank secret produces `configuration_missing` without values | existing monitor secret lookup tests remain green | PASS (local) / NEEDS_REVERIFY (external) |

## Regression ledger

| Regression ID | Introduced by | Symptom | Root cause | Fix / evidence | Status |
|---|---|---|---|---|---|
| REG-NEWS-001 | prior release path | News artifact could be hashed but not checked by delivery gate | gate loader enumerated only core/Creator artifacts | `7f1fd60`, 51 targeted tests | CLOSED |
| REG-NEWS-002 | environment | Windows shared temp contains inaccessible historical pytest directories | inherited workspace hygiene | CI and isolated basetemp pass; no product assertion changed | ACCEPTED ENVIRONMENT DEBT |
| REG-MIG-001 | migration overlay | prior state document pointed at `c3f43d7` after later evidence commits | state reconciliation lag | `4b60f06`; 63 targeted and 1133 full regression passed | CLOSED |
| REG-MIG-002 | external observation lineage | malformed manifest count could raise before fail-closed result | defensive integer parsing in release gate | targeted release-gate suite and full isolated regression | CLOSED |
| REG-MIG-003 | verification environment | first full run timed out near 87% with one transient failure | rerun with a fresh isolated basetemp; no product assertion was changed | second full run `1146 passed` in 81.33s | ACCEPTED ENVIRONMENT EVENT |
| REG-MIG-004 | verification environment | OneDrive basetemp produced an asset-test `PermissionError` | rerun in isolated Windows temp; no product assertion was changed | `1147 passed` in 64.74s | ACCEPTED ENVIRONMENT EVENT |
| REG-P0-25-001 | legacy Creator health mapping | `status=no_event` was treated as an unknown failure by the Creator aggregate | shared `classify_failure` maps empty scans to `no_new_content`; 24 targeted source/Creator tests pass | CLOSED |

## Completion debt ledger

| Debt ID | Description | Resolution / owner | Status |
|---|---|---|---|
| DEBT-NEWS-001 | Live official feed and Pages publication evidence | run controlled release after PR #578 is merged | OPEN EXTERNAL |
| DEBT-NEWS-002 | Railway and Telegram delivery receipt evidence | protected runtime configuration; single-recipient dry-run | OPEN EXTERNAL |
| DEBT-NEWS-003 | Historical untracked test/temp artifacts | separate workspace hygiene task; do not stage during feature work | OPEN NON-PRODUCTION |
| DEBT-MIG-001 | Re-run required verification at migration HEAD | `63 passed, 1 skipped`; `1133 passed, 1 skipped`; Ruff/Mypy/compile/node checks | CLOSED |
| DEBT-FJ-001 | Railway has not yet supplied a live sanitized FinancialJuice bundle to the scheduled workflow | configure `EXTERNAL_OBSERVATIONS_PATH` with reviewed derived JSON; run release-gated workflow | OPEN EXTERNAL |
| DEBT-FJ-002 | Railway/Gmail/FinancialJuice operational metrics have not been observed in a ready public release | run a controlled release after #579 and verify source-health row plus Mini App browser | OPEN EXTERNAL |
| DEBT-P0-25-001 | Full repository regression had transient Windows raw-observation permission failures in one isolated run | fresh isolated temp rerun: `1155 passed` in 112.04s; no product assertion changed | CLOSED |
| DEBT-REQ-ADD-003-001 | Remaining Railway `app.py` extraction and live health acceptance are not covered by this incremental boundary task | continue with an isolated component extraction only after the current PR is reviewed; live Railway evidence requires protected runtime configuration | OPEN (SCOPED) |

### Migration audit update (2026-08-14, multi-market News release binding)

- `news.json` now publishes one release-bound envelope containing Taiwan and US
  News Intelligence views when both are present; legacy single-market payloads
  remain readable.
- The release gate validates each market payload and its shared provider
  registry. The Mini App verifies the News artifact hash, market snapshot and
  News snapshot before rendering either tab, including last-good fallback.
- Targeted release/news/Mini App/delivery-gate suite: `63 passed, 1 skipped`; full local regression: `1133 passed,
  1 skipped`; Ruff, Mypy, compile and `node --check` pass.
- PR [#579](https://github.com/hanjhou2000716/prstklab-stk-detector/pull/579)
  required checks pass for `763c7c4` (test-and-dry-run, CodeQL, dependency review,
  SBOM and duplicate CodeQL check). Pages/Railway/Telegram production acceptance remains
  external and fail-closed.

### Migration audit update (2026-08-14, sanitized external ingress)

- `EXTERNAL_OBSERVATIONS_PATH` is now an opt-in scheduled-workflow input. The
  loader accepts only `public_safe` FinancialJuice-derived records with stable
  observation IDs, rejects raw mail/Gmail transport identifiers/private fields,
  and never reads from the Pages tree.
- Accepted rows are attached to the same market snapshot and briefing consumed
  by the existing intelligence pipeline. Rejected/missing input is represented
  by an optional source-health row; it cannot be interpreted as a clean scan or
  independently trigger a high-risk alert.
- Targeted ingress/scheduled/workflow suite: `24 passed`; full local regression:
  `1139 passed, 1 skipped`; Ruff, Mypy and compileall pass.
- This closes the local canonical integration gap only. A Railway-provided
  sanitized bundle, ready release and controlled Telegram receipt are still
  external evidence gates and remain fail-closed.

### Migration audit update (2026-08-14, external observation release lineage)

- Sanitized FinancialJuice observations now contribute deterministic count,
  source list and observation-ID hash metadata to the same release manifest as
  market/research/event data. The release gate rejects count, source or hash
  mismatches before delivery; legacy manifests without the optional fields
  remain backward-compatible.
- Mini App has a release-bound “外部財經快訊” panel. It distinguishes
  `已核對`, `等待官方核對`, `等待市場同步` and the combined pending state;
  links are accepted only when they are HTTPS URLs from the sanitized record.
- Targeted release/lineage/Mini App suite: `78 passed`; isolated full local
  regression: `1144 passed, 1 skipped`; Ruff, Mypy, compileall and frontend
  syntax checks pass.
- Pages browser, Railway sanitized bundle and controlled Telegram receipt are
  still external gates. No production side effect was attempted.

### Gate audit evidence (2026-08-14)

- `python -m src.runtime_audit` exited 0 with `ok=true`; its warnings remain
  visible (market source gaps, building research, and missing ready production
  snapshots) and are not reclassified as “no risk”.
- `python -m src.delivery_smoke_test` is `BLOCKED` in this checkout because
  `TELEGRAM_CHAT_IDS` is not configured. No recipient or token was invented,
  and no production message was attempted. A controlled single-recipient test
  remains an external acceptance prerequisite.

### Migration audit update (2026-08-14, FinancialJuice operational observability)

- The optional FinancialJuice source-health row now exposes only privacy-safe
  operational metrics: last received/parsed timestamps, parser error count,
  count of vendor-importance >=8 items, pending event-cluster count and the
  resulting notification decision. Delivery time is intentionally null until
  a real receipt is recorded by the delivery pipeline.
- The source-health schema explicitly validates this nested contract. The Mini
  App renders the metrics beside the existing source status and keeps pending
  confirmation distinct from no-event and scan failure.
- Targeted observability/schema/Mini App suite: `52 passed`; Ruff and Mypy pass.
  Railway bundle, ready Pages release and Telegram receipt remain external
  evidence gates; no production side effect was attempted.
- Fresh isolated full regression after the observability change: `1146 passed`.
  `ruff check src tests`, `mypy src`, `compileall` and `node --check` pass.
  `python -m src.runtime_audit` exits 0 with the existing data-readiness
  warnings. The delivery smoke remains externally blocked because this
  checkout has no `TELEGRAM_CHAT_IDS`; no message was sent.
- PR [#580](https://github.com/hanjhou2000716/prstklab-stk-detector/pull/580)
  remote test-and-dry-run, CodeQL, dependency-review and SBOM checks all pass.
  It remains open and must be merged after #579; this does not constitute
  Railway, Pages or Telegram production acceptance.

### Migration audit update (2026-08-14, Creator operational observability)

- Optional Creator provider rows now expose privacy-safe operational metrics:
  observation count, receive/parse/delivery timestamps, parser error count and
  explicit no-observations state. The implementation never copies Gmail
  transport identifiers or raw content into the health contract.
- The source-health schema and Mini App accept/render the Creator metrics while
  keeping configuration missing, no-new-content and parser failure distinct.
- Creator/source-health/schema/Mini App targeted suite: `91 passed`; isolated
  full repository regression: `1147 passed`; Ruff, Mypy, compileall and node
  syntax checks pass. Railway and Pages browser evidence remain external.
- PR [#581](https://github.com/hanjhou2000716/prstklab-stk-detector/pull/581)
  remote test-and-dry-run, CodeQL, dependency-review and SBOM checks all pass.
  It remains open and stacked on #580; this is not Railway or Pages
  production acceptance.
- PR [#582](https://github.com/hanjhou2000716/prstklab-stk-detector/pull/582)
  remote test-and-dry-run, CodeQL, dependency-review and SBOM checks all pass.
  It remains open and stacked on #581; live feed freshness and production
  acceptance remain external.

### Migration audit update (2026-08-14, official News adapter observability)

- TWSE/MOPS/SEC/Fed adapter health rows now include privacy-safe checked and
  parsed timestamps, parser-error count and bounded latency. HTTP 429 remains a
  rate-limited provider result without retrying or aborting other providers.
- Targeted News adapter/contract suite: `45 passed`; isolated full regression:
  `1147 passed`; Ruff, Mypy, compileall and node syntax checks pass.
- This is local adapter evidence only. Live provider freshness, Pages release
  and Railway/Telegram production evidence remain external.

### Migration audit update (2026-08-14, Gmail watch observability)

- Gmail watch health now exposes a privacy-safe observability envelope with
  receive/parse/delivery timestamps, a bounded parser-error count and an
  explicit configuration-missing or stale state. Gmail history IDs, message
  IDs and raw mail are never copied into the health response.
- Targeted Gmail gateway suite: `12 passed` in an isolated Windows temp
  directory. The initial shared OneDrive/pytest temp attempt was rejected by
  an inherited Windows `PermissionError`; no product assertion failed.
- This is local contract evidence only. OAuth/PubSub configuration, Railway
  runtime health and controlled Telegram delivery remain external gates.

Remote evidence: PR [#583](https://github.com/hanjhou2000716/prstklab-stk-detector/pull/583)
passed test-and-dry-run, CodeQL, dependency-review and SBOM checks through
the privacy-boundary commit `7228915`. This does not promote the Gmail task to
Railway production PASS;
OAuth/PubSub and controlled delivery evidence are still external.

### Gmail public-health privacy boundary (2026-08-14)

- Railway `/health` now projects only the Gmail watch observability envelope;
  private Gmail history/message cursors are not exposed in the public health
  snapshot or push-success path.
- Targeted Gmail/monitor regression: `95 passed`; isolated full regression:
  `1149 passed, 1 skipped`; changed-file Ruff/Mypy/compile checks passed.
- PR #583 latest commit `7228915` passed the required remote test-and-dry-run,
  CodeQL, dependency-review and SBOM checks. Production Railway health and
  Telegram delivery still require protected external configuration.

## Gate decision

The canonical News release-lineage task and this migration verification are
`LOCKED` on this branch.  Do not merge solely
from local evidence while PR checks are pending.  Pages browser and protected
Railway/Telegram acceptance remain external gates; no production side effect
is attempted by this checkpoint.
