# Gate-Driven v3 migration checkpoint — 2026-08-15

This is the authoritative reconciliation snapshot for the in-flight upgrade.
It is intentionally separate from older gate notes written before the latest
main release and does not promote historical claims to `PASS` without current
evidence.

## Repository snapshot

| Item | Evidence |
|---|---|
| Remote main at audit start | `587a27b155b92e9614fa5485d632fde28c087a64` |
| Audit branch base | `main` (origin/main `587a27b155b92e9614fa5485d632fde28c087a64`) |
| Current audit branch | `feat/REQ-ADD-039-gate-migration-audit` |
| Evidence code checkpoint | `2d523b8` (`docs: capture current Railway external gate status`) |
| Working tree | Clean at the snapshot; no uncommitted or untracked product changes. |
| Historical stack observed | PRs #566–#617 are already ancestors of current `main`; they are historical context, not an outstanding merge queue. |

Local full-regression evidence at this checkpoint: `python -m pytest -q
--basetemp=.pytest-full` completed with **1231 passed, 1 skipped** in 50.55s.
The workspace basetemp was removed after the run; no production data or
notification was touched.

## Requirement traceability (migration scope)

| Requirement | Task | Implementation | Verification | Evidence | Regression | Status |
|---|---|---|---|---|---|---|
| P0-09 / P0-12 | REQ-ADD-039-T01 | Railway Gmail parses a bounded public-safe observation projection | `tests/test_railway_gmail_gateway.py` | 17 targeted tests pass; no raw body/sender/transport IDs in projection | duplicate and DLQ tests pass | PASS |
| P0-09 / P0-12 | REQ-ADD-039-T02 | Authenticated `/external-observations` export and client | `tests/test_railway_observation_client.py` | signature, status, schema and private-field rejection tests pass | missing config remains fail-closed | PASS |
| P0-09 / P0-12 | REQ-ADD-039-T03 | Scheduled delivery merges Railway and reviewed local observations | `tests/test_scheduled_delivery.py` plus external-input tests | 27 targeted/regression tests pass | local reviewed input remains usable when Railway is unavailable | PASS |
| P0-24 / P0-29 | REQ-ADD-039-T04 | Gate-driven evidence and debt ledgers | this document and canonical `docs/p0-requirement-traceability.md` | PR #618 at HEAD `2d523b8`: quality run `31845113369` and security run `31845113354` passed (CodeQL, dependency review, SBOM, full test-and-dry-run) | no merge performed; scoped photo smoke is recorded below | PASS / LOCKED |

`PASS` above is limited to the listed implementation and tests. It is not a
claim that the entire product or all original P0 DoDs are complete.

The full P0-01..P0-29 requirement index and its current external-gate debt are
maintained in the canonical `docs/p0-requirement-traceability.md` registry and
covered by `tests/test_p0_traceability_registry.py`; this checkpoint does not
create a second registry.

## Integration matrix (current evidence)

| Module | Files exist | Tests | Formal pipeline | JSON | Mini App | Telegram | Status |
|---|---:|---:|---:|---:|---:|---:|---|
| Source adapters / market snapshot | yes | yes | yes | yes | yes | yes | production |
| Release manifest / release gate | yes | yes | yes | yes | yes | yes | production |
| Alert lifecycle / budget / dedup | yes | yes | yes | yes | yes | yes | production |
| Telegram delivery receipts | yes | yes | yes | yes | n/a | yes | production |
| Mini App deep links / release fallback | yes | yes | yes | yes | yes | n/a | production |
| Creator / FinancialJuice registry | yes | yes | partial | partial | partial | partial | partially_integrated |
| Railway Gmail → sanitized public observation export | yes | yes | this PR | this PR | pending deploy | pending acceptance | partially_integrated |
| Event clustering / impact graph | yes | yes | partial | partial | partial | partial | partially_integrated |
| Macro surprise / regime / contagion | yes | yes | partial | partial | partial | partial | partially_integrated |
| Strategy registry / point-in-time backtest | yes | yes | partial | partial | partial | n/a | partially_integrated |
| Private portfolio risk | yes | yes | no public pipeline | no public output | isolated | no | experimental |
| Advice gate / paper portfolio | yes | yes | partial | partial | partial | no trade action | experimental |

## Regression ledger

| ID | Symptom | Root cause / mitigation | Evidence | Status |
|---|---|---|---|---|
| REG-039-01 | OneDrive can intermittently fail raw-observation temp-file replacement | Environment/filesystem behavior; rerun on CI/Linux or a local non-synced checkout | prior baseline runs, not reproduced by targeted tests | OPEN / needs reverify |
| REG-039-02 | Railway export unavailable when URL/secret are absent | Client returns `configuration_missing`; local reviewed input remains valid and no alert is invented | client test | CLOSED |
| REG-039-03 | Invalid/private Gmail-derived row could enter release | Sanitized allowlist and SQLite privacy boundary reject it | ingress + external-input tests | CLOSED |

## Current external evidence

The following evidence was captured after the migration checkpoint and is
explicitly scoped; it does not claim a complete production acceptance:

- Public Pages manifest: `release-957714e850293f39`, `status=ready`; all six
  declared artifact hashes (`market`, `research`, `event`, `source-health`,
  `creator-release`, `creator-insights`) matched the public bytes.
- Railway `/health`: monitor `running/healthy`; GDELT remains rate-limited
  (`HTTP_429`) and GitHub dispatch remains permission-denied (`HTTP_403`), so
  those are open runtime configuration issues rather than hidden successes.
- Scoped photo smoke: Actions run `31839093636`, job `94891873503`, one
  recipient only; Railway receipt projected `delivered`, `delivered_count=1`,
  `failed_count=0`, `recipient_count=1`, `receipt_matches=true`, trace
  `photo-smoke-b09bb97240c54a9f`.
- No broadcast, merge, or user-visual confirmation of the Mini App WebView
  was performed in this checkpoint.

### Post-checkpoint reconciliation evidence

- Overlap audit commits: `c94fcee`, `2d523b8` on PR #618.
- Latest quality run: `31840194185` (success); latest security run:
  `31840194207` (success, including CodeQL, dependency review and SBOM).
- Public Creator release remains `ready` with one sanitized insight; public
  source-health exposes Creator provider rows. FinancialJuice remains optional
  and has no public row until its sanitized Railway bundle is configured.
- The current live Railway projection still reports GDELT `HTTP_429` and
  dispatch callback `HTTP_403`; these are explicitly open external gates.

- Mini App loader preference fix (`a09bb30`) now selects the bounded public
  Creator insight projection before the internal envelope. Targeted UI and
  fallback tests: `4 passed`; latest PR quality run `31841614424` and security
  run `31841613208` passed.

## Completion-debt ledger

| Debt ID | Description | Resolution / next gate | Status |
|---|---|---|---|
| DEBT-039-01 | Ruff is not installed in this local runtime | Remote CI Ruff gate passed; local environment remains unable to reproduce it without network/cache access | CLOSED (CI evidence) |
| DEBT-039-02 | Railway GDELT 429 and GitHub dispatch 403 remain live runtime configuration issues; Mini App WebView visual acceptance is pending | Fix provider rate-limit/backoff configuration and protected dispatch permission; then perform post-merge acceptance | OPEN / external |
| DEBT-039-03 | Full repository regression and all original P0 DoDs not rerun on this checkpoint | Local full regression is 1231 passed / 1 skipped; rerun on latest main and update traceability evidence | OPEN |
| DEBT-039-04 | Existing older gate notes contain PASS claims predating this snapshot | Treat this document as current authority; reverify each mapped DoD | OPEN |

## Preservation contracts

- **PC-001** market/risk/research pipelines remain unchanged unless they consume
  the new optional observation projection.
- **PC-002** release gate and stale/fail-closed rules remain mandatory; no
  Railway failure can create a qualifying alert.
- **PC-003** Telegram delivery remains release-bound and single-recipient
  testing only; this checkpoint performs no production broadcast.
- **PC-004** raw Gmail body, sender, attachment and transport identifiers never
  enter public artifacts.
- **PC-005** local reviewed `EXTERNAL_OBSERVATIONS_PATH` remains a safe fallback
  when Railway is unavailable.

## Recovery / rollback

The branch is a recoverable checkpoint based on the latest audited `main`
(`587a27b155b92e9614fa5485d632fde28c087a64`). Rollback is a PR revert (or branch deletion before merge);
it removes the Railway export path while leaving prior release and Telegram
gates intact.
No merge, deploy, release publication, or production notification is part of
this checkpoint.
## Migration snapshot: 2026-08-15 continuation

- Branch: `feat/REQ-ADD-039-gate-migration-audit`
- HEAD: `2d523b8`
- `origin/main`: `587a27b155b92e9614fa5485d632fde28c087a64`
- Working tree: clean before this evidence update.
- Recovery checkpoint: the previous `2d523b8` commit is the rollback point for this continuation; no reset or force-push is required.

### Reconciled state

| Area | Status | Evidence |
|---|---|---|
| Creator public artifact precedence | PASS | `site/app.js`, `tests/test_creator_insight_ui_contract.py`; 4 targeted tests and `node --check site/app.js` |
| Public release manifest/hash binding | PASS | live Pages manifest `release-957714e850293f39`; six artifact SHA-256 checks matched |
| Full local regression | PASS | `python -m pytest -q --basetemp=.pytest-final`: 1231 passed, 1 skipped |
| Runtime audit | NEEDS_REVERIFY | `python -m src.runtime_audit` is structurally valid but reports local checked-in data gaps |
| Railway/GDELT | NEEDS_REVERIFY | Railway health is running; GDELT is bounded at HTTP 429 and health callback is HTTP 403 |
| Telegram photo delivery | NEEDS_REVERIFY | scoped one-recipient photo smoke previously delivered with matching receipt; no current broadcast was sent |
| Gmail ingress | BLOCKED | Railway reports `configuration_missing`; OAuth/PubSub credentials are not available in this workspace |

### Stale PR overlap

PRs whose heads are already ancestors of `origin/main` are superseded, not additional production pipelines. They may be closed without deleting branches after posting the superseded explanation. PR #546 and #554 require file-level reconciliation because their heads are not local ancestors, but all their implementation paths are present on `origin/main` under later commits (`71c1441`, `f9b9683`, `87058ef`, `d7857c6`).

The overlap cleanup closed the verified stale set #545, #546, #549–#554 and
#566–#576. Remaining older stacked PRs are intentionally not mass-closed by
this checkpoint until each head is individually compared with `origin/main`.
This avoids treating an unverified branch as superseded. The canonical active
continuation remains PR #618.

### Completed individual overlap audit

The remaining stacked Creator, external-intelligence, source-health, strategy,
news and release PRs were subsequently checked one by one. Their heads were
ancestors of `origin/main`, or their exact behavior was present in later
mainline commits; they were closed as superseded without deleting branches:

`#479–#482`, `#486–#493`, `#496–#516`, `#520–#522`, `#527–#533`,
`#543–#554`, and `#566–#576` (with gaps representing PRs that were not open).

The only remaining open PR in the repository is the canonical continuation
`#618`. This cleanup changed no source or release data and does not constitute
mainline merge or production acceptance.

### Latest Railway health capture

The live `/health` endpoint remains reachable and the monitor heartbeat is
healthy. It currently reports Jin10 healthy, delivery receipt consistency for
the scoped photo smoke, GDELT `HTTP_429` with bounded fallback disabled for the
current cycle, and the health callback `HTTP_403`. Gmail remains
`configuration_missing`; no credentials or private payloads were read. These
states remain external acceptance debt and are intentionally not promoted to
PASS by a local test.

Post-checkpoint regression: `python -m pytest -q --basetemp=.pytest-final`
returned `1231 passed, 1 skipped`; the temporary directory was removed and the
working tree is clean. PR #618 CI is green (quality/dry-run, CodeQL,
dependency-review and SBOM).

### Gate v3 continuation verification — 2026-08-15

- Snapshot rechecked on HEAD `2d523b8`; working tree was clean before this
  documentation update and `origin/main` remains `587a27b155b92e9614fa5485d632fde28c087a64`.
- Full repository regression: `python -m pytest -q --basetemp=.pytest-migration`
  returned **1231 passed, 1 skipped**; the temporary directory was removed.
- JavaScript syntax: `node --check site/app.js` passed.
- Runtime audit returned `ok=true` with explicit warnings for checked-in
  market gaps, building research, and missing local event/research/ready
  manifest artifacts. These warnings are not promoted to production PASS.
- Delivery dry-run returned `ok=true`, one synthetic recipient, HTTPS dashboard,
  configured callback, and no errors; no Telegram API was called.
- After pushing this checkpoint, PR #618 checks completed successfully:
  quality/dry-run run `31845718851` and security/CodeQL/dependency-review/SBOM
  run `31845718813`.

The only current open PR remains #618. This evidence update does not merge,
deploy, publish, or send a production notification. Production acceptance is
still **INCOMPLETE** until the external Railway permissions/configuration and
post-merge Pages/Mini App checks are reverified.

### Railway observation release wiring (continuation checkpoint)

The scheduled prepare path now calls the canonical sanitized Railway export
when `RAILWAY_OBSERVATIONS_URL`/`RAILWAY_STATUS_URL` and the shared secret are
configured. Remote rows are merged by `observation_id` over the reviewed local
fallback, and the resulting rows travel through the existing briefing,
release-manifest and source-health paths. Unknown providers and private
transport fields are rejected with a counted parser error; a failed remote
export leaves a local reviewed row visible but marks the source `partial`.

Evidence on this checkpoint:

- targeted ingress/scheduled-delivery tests: **27 passed**;
- full repository regression: **1235 passed, 1 skipped**;
- `uv run --locked ruff check src tests`: **passed**;
- `uv run --locked mypy src`: **passed**;
- `node --check site/app.js`: **passed**;
- runtime audit is structurally valid but still reports checked-in data gaps;
- delivery smoke is dry-run only and made no Telegram API call.

This fixes the local integration gap; it does not promote Railway's live GDELT
429, callback 403, or missing Gmail configuration to PASS. Post-merge main,
Pages/Mini App and production delivery evidence remain required.

### Latest checkpoint evidence (f854cbd)

- PR #618 remains open, non-draft and clean; no merge was performed.
- GitHub Actions quality/dry-run, CodeQL, dependency review and SBOM checks
  all passed for commit `f854cbd` (quality run `31847434368`, security run
  `31847434404`).
- The local Railway observation wiring is therefore covered by both targeted
  tests and the repository quality gate. This is implementation evidence, not
  live Railway or post-merge production acceptance.

### Gate v3 migration overlay reconciliation (fc2aefe)

The mid-flight migration overlay was applied to the current branch without a
reset or merge. The recovery point is the latest atomic commit on this branch
(`fc2aefe`, `fix: enforce Railway observation privacy allowlist`); the earlier
Railway wiring commits (`f854cbd`, `a3a68d2`) remain its ancestors. No product
files are left in an uncommitted state. The only local verification residue is
an inaccessible, untracked pytest coverage directory created by a timed-out
coverage run; it is not staged, published, or part of the release.

Migration classification at this checkpoint:

| Area | State | Evidence / next gate |
|---|---|---|
| Railway observation allowlist | LOCKED | 27 targeted ingress/scheduled tests; unknown providers and private transport fields are rejected with a counted failure |
| Railway observations in scheduled release | PASS | remote rows merge by `observation_id`, local reviewed rows remain the fail-closed fallback, and source health marks remote failure as partial |
| Repository-shared Railway classifier | NEEDS_REVERIFY | local root-only import isolation proves the fallback cannot dispatch; live deployment must report `classifier_mode=repository-shared` |
| GDELT and health callback | NEEDS_REVERIFY | live Railway evidence remains `HTTP_429` / `HTTP_403`; no local test may promote these to healthy |
| Pages / Mini App / Telegram production acceptance | NEEDS_REVERIFY | PR #618 is open; post-merge release, browser and single-recipient receipt evidence are still required |
| Full local regression | PASS (local) | `1235 passed, 1 skipped`; Ruff, Mypy and JavaScript syntax checks passed |

The migration overlay therefore leaves the overall project **INCOMPLETE**.
`PASS` is only asserted for the scoped local task above; it is not a claim of
full P0 completion or production acceptance. Any future change to a locked
area must reopen its task, rerun its original tests and record new evidence.

Post-push evidence for this reconciliation commit (`4dec871`): PR #618
quality `test-and-dry-run` run `31848719631` and security run `31848719725`
both passed (CodeQL, dependency review and SBOM). The PR remains open and
unmerged; these checks do not substitute for post-merge production acceptance.

### P0-26 provider-registry drift repair (current continuation)

The Railway standalone bundle was found to be a duplicate, mojibake-prone
Creator registry and `email_router.py` also carried a second hard-coded Creator
marker table. The duplicate table was removed from the active fallback path and
`railway-monitor/creator_providers.json` was restored to the canonical
`config/creator_providers.json` contract. The new regression test compares both
decoded registries exactly. Targeted Railway/Gmail and monitor tests pass
(`101 passed`); targeted Ruff for the changed router/test files and
`python -m compileall -q railway-monitor` also pass. A full Railway-wide Ruff
run still reports pre-existing lint debt in `railway-monitor/app.py`; it is
tracked as existing completion debt and was not broadened into this atomic fix.

State: **PASS locally / NEEDS_REVERIFY externally**. The live service must still
prove repository-shared classifier packaging and post-merge release/Telegram
acceptance; no production notification was sent by this task.

Remote evidence for atomic commit `55ff046` on PR #618: quality
`test-and-dry-run` run `31849906527` / job `94923605186` passed; security run
`31849906489` passed CodeQL (`94923605412`), dependency review
(`94923605301`) and SBOM (`94923605305`); the separate CodeQL check
`94923736064` also passed. These checks verify the registry contract and test
suite only; they do not replace external Railway or post-merge acceptance.

### Creator routing whitelist deduplication (next atomic task)

The repository-level email router had already checked the canonical Creator
registry first, but retained a second hard-coded Creator fallback table. That
table is now removed; only FinancialJuice aliases remain outside the registry.
`test_creator_source_routing_uses_canonical_registry_markers` protects the
canonical path and the full repository regression is **1237 passed, 1 skipped**.
Changed-file Ruff and `python -m compileall -q src railway-monitor` pass. The
task is **PASS locally / NEEDS_REVERIFY externally** because live Gmail/Railway
configuration and receipt evidence remain outside the local repository gate.
Remote evidence for `b97bc91` on PR #618: test-and-dry-run run
`31850654835` / job `94925667803` passed; CodeQL run `31850654722` / job
`94925667563`, dependency review job `94925667502`, SBOM job `94925667545`,
and the separate CodeQL check `94925796640` all passed.

### Shared Creator template adapter (current continuation)

The Creator template parser previously had provider IDs duplicated in a local
`_LABELS` map. It now builds that map from the canonical registry and uses a
shared public-safe section vocabulary. Unknown identities still fail closed;
adding a configured provider no longer requires editing a second identity
allowlist. Targeted adapter/parser/registry tests pass (**21 passed**).

State: **PASS locally / NEEDS_REVERIFY externally**. This is an adapter
contract repair only; live Gmail/Railway configuration, repository-shared
classifier packaging, Pages release and Telegram receipt evidence remain open
external gates.

The adapter repair was rebased onto the post-merge `main` commit
`c64a54b` and delivered as PR #619 (`feat/REQ-ADD-040-creator-adapter-contract`)
because PR #618 had already merged before this continuation was pushed.
PR #619 remote evidence: test-and-dry-run run `31851768583` / job
`94928745542`, CodeQL run `94928878624`, security CodeQL job `94928745694`,
dependency review job `94928745662`, and SBOM job `94928745833` all passed.

Remote evidence for atomic commit `5a72d0b` on PR #618: the existing quality
and security suites remain green after the push — `test-and-dry-run` run
`31850654835` / job `94925667803`, CodeQL run `94925796640`, security CodeQL
job `94925667563`, dependency review job `94925667502`, and SBOM job
`94925667545`. These checks provide CI evidence for the adapter change; they
do not substitute for live Railway, Pages, Mini App or Telegram acceptance.

### Creator parser contract hardening (follow-up)

The shared adapter now validates the registry `parser` field before parsing.
An unknown or future parser version returns `unsupported_parser` and remains
DLQ-safe; it cannot silently fall through to the v2 template. The registry
provider loop and parser-mismatch regression now pass alongside the full suite:
**1239 passed, 1 skipped**. Changed-file Ruff also passes. This follow-up is
part of PR #619 and remains local/CI evidence only until live Gmail/Railway
acceptance is captured.

### REQ-ADD-042: canonical news feed projection

The official news adapter no longer owns a second provider identity catalog.
`news_intelligence.PROVIDER_REGISTRY` is the source of truth for official feed
URL, parser kind, market, timeout, authority tier and disabled-source state;
`news_feed_adapters.feed_catalog()` is a projection used for fetching and
source-health reporting. Discovery providers without a feed endpoint remain
excluded from the official evidence path. Targeted news adapter, intelligence
and routing tests pass locally; live TWSE/MOPS/SEC/Fed freshness evidence is
still `NEEDS_REVERIFY` under the external gates above.

PR #621 remote evidence: `test-and-dry-run` run `31853786392` / job
`94934561198` passed; CodeQL run `94934682932` and security CodeQL job
`94934561115`, dependency review `94934561091`, and SBOM `94934561084` all
passed. These checks verify the canonical projection and regression suite;
they do not replace live source-freshness or post-merge acceptance evidence.

### REQ-ADD-043: Railway keyword bundle parity

The standalone Railway keyword bundle is now structurally identical to the
canonical `config/event_keywords.json`. This closes a policy-drift path where
the root-only image could classify the same Jin10/GDELT headline with a
reduced alias set. The new regression compares both parsed JSON documents;
dispatch remains blocked unless the repository-shared classifier is active.
Local live-mode evidence is **PASS**; Railway `classifier_mode=repository-shared`
and production delivery remain **NEEDS_REVERIFY** external gates.

### REQ-ADD-044: Railway repository-shared classifier package

The root-only Railway image now carries a generated
`railway-monitor/shared_event_classifier.py` produced from the canonical
`src/event_classifier.py`. The generator rewrites only the keyword-file path
to the sibling bundle; it does not introduce a second policy implementation.
`tests/test_railway_monitor.py` verifies isolated root imports use
`classifier_mode=repository-shared` and that the generated bundle is current.
The quality workflow runs the generator in `--check` mode, so classifier source
changes cannot silently leave a stale Railway artifact. Local evidence is
targeted **103 passed** and repository regression **1245 passed, 1 skipped**;
live Railway health and delivery remain
**NEEDS_REVERIFY** until `/health` reports the shared mode.
PR #623 remote evidence: quality run `31856149233` and security run
`31856149334` completed successfully.

Verification evidence for this continuation: targeted Railway/classifier/Gmail
suite **106 passed**; repository regression **1244 passed, 1 skipped**;
`uv run ruff check src tests`, `uv run mypy src`, and Python compilation passed.
Runtime audit and offline system dry-run passed; delivery smoke remains
configuration-failed locally because production Telegram recipients are not
loaded, which is an intentional external gate rather than a test bypass.

PR #622 remote evidence: quality run `31855118955` / job `94938300129`,
CodeQL run `94938400149`, security CodeQL job `94938300133`, dependency review
`94938300102`, and SBOM `94938300165` passed. This proves the bundle parity
contract in CI; it does not replace live Railway classifier or Telegram
acceptance.
