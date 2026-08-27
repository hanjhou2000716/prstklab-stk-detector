# Gate-Driven v3 migration audit — 2026-08-28

This checkpoint reconciles the current repository and external observations
without resetting or redoing the existing Creator/FJ/News work.  Statuses use
the migration protocol vocabulary: `NOT_STARTED`, `IN_PROGRESS`,
`NEEDS_REVERIFY`, `PASS`, `FAIL`, `BLOCKED`, `REOPENED`, and `LOCKED`.

## Snapshot

| Field | Evidence |
|---|---|
| Branch | `feat/zero-cost-worker-token-contract` |
| HEAD | `7c5a7e4d` (`docs: reconcile gate-driven migration state`) |
| Base | `origin/main` at `34fe90e8` |
| PR | [#801](https://github.com/hanjhou2000716/prstklab-stk-detector/pull/801), open, clean, non-draft |
| Recovery checkpoint | `789719eb` and the follow-up evidence commit `ce50eee3` |
| Working tree | tracked changes clean; historical untracked test artifacts preserved and not staged |
| Canonical overlap audit | `python scripts/verify_canonical_overlap.py` → `status=pass`, `failed_count=0` |
| Local regression | `1493 passed`; targeted acceptance suite `30 passed` with isolated workspace temp |
| Static checks | Ruff, Mypy, compileall, frontend syntax and Worker typecheck passed |
| PR checks | test-and-dry-run, CodeQL, dependency review and SBOM all successful |

## Current task reconciliation

| Task | State | Evidence / next gate |
|---|---|---|
| Canonical Creator/FJ/news ownership | `LOCKED` | overlap audit and regression evidence show one registry/classifier/parser path |
| Release and Telegram fail-closed contract | `LOCKED` (local) | release-gate and delivery tests pass; production receipt remains external |
| Worker source and health classification | `PASS` (local/runtime) | `worker/src/index.ts` typechecks; dashboard deployment `ba4dd5f6` reports `version=zero-cost-worker-1` and explicit configuration state |
| Cloudflare Worker public reachability | `PASS` (runtime) | `/api/health` returns HTTP 200; this proves reachability only |
| Supabase-backed Worker canary | `BLOCKED` | deployed response is `database=unavailable`; provider secrets are not configured |
| Railway rollback path | `PASS` (preserved) / `NEEDS_REVERIFY` (canary) | Railway is retained as rollback-only until Worker canary succeeds |
| Full production acceptance | `BLOCKED` | requires provider secrets, ready release, Pages verification and controlled Telegram receipt |

## Requirement traceability (current checkpoint)

| Requirement | Implementation | Verification | Evidence | Status |
|---|---|---|---|---|
| Canonical provider/classifier ownership | `config/creator_providers.json`, `src/creator_provider_registry.py`, `src/event_classifier.py` | overlap audit + full regression | `canonical-overlap-audit-2026-08-28.json` | `PASS` → `LOCKED` |
| Creator/FJ/news integration does not duplicate paths | `src/creator_intelligence_pipeline.py`, `src/external_event_pipeline.py`, `src/news_intelligence.py` | full regression | `creator-fj-overlap-regression-2026-08-28.json` | `PASS` → `LOCKED` |
| Worker health distinguishes configuration from provider failure | `worker/src/index.ts` | Worker typecheck + source review | PR #801 | `PASS` (local) |
| Public health response is recorded without secrets | `docs/evidence/zero-cost-worker-public-health-2026-08-28.json` | JSON parse + public HTTPS probe | redacted health evidence | `PASS` (observation) |
| No false production canary claim | `docs/zero-cost-production-acceptance.md` | acceptance contract tests | health response + runbook | `PASS` → `LOCKED` |
| Supabase/GitHub/Telegram secrets available to Worker | Cloudflare Worker Secret Variables | provider-side canary | names are absent from the accessible settings view | `BLOCKED` |
| Canonical Worker source deployed | Cloudflare dashboard deployment `ba4dd5f6` | public `/api/health` | `docs/evidence/zero-cost-worker-deploy-recheck-2026-08-28.json` | `PASS` (reachability/source version) |

## Regression ledger

| Regression ID | Symptom | Root cause | Fix / evidence | Status |
|---|---|---|---|---|
| `REG-WORKER-001` | `/health` was probed as if it were canonical | wrong route assumption | `/api/health` is now documented and verified | `CLOSED` |
| `REG-WORKER-002` | API reachable but database unavailable could be mistaken for recovery | reachability and readiness were conflated | fail-closed health classification and public evidence | `CLOSED` |
| `REG-ENV-001` | pytest could not scan inherited OneDrive temp directories | Windows workspace permissions | isolated workspace temp rerun: 30 targeted tests passed | `ACCEPTED ENVIRONMENT EVENT` |

## Completion debt ledger

| Debt ID | Description | Resolution / owner | Status |
|---|---|---|---|
| `DEBT-WORKER-001` | Add `SUPABASE_SERVICE_ROLE_KEY` to Worker Secret Variables | operator/provider UI | `OPEN EXTERNAL` |
| `DEBT-WORKER-002` | Add `GITHUB_DISPATCH_TOKEN` to Worker Secret Variables | operator/provider UI | `OPEN EXTERNAL` |
| `DEBT-WORKER-003` | Add `TELEGRAM_BOT_TOKEN` to Worker Secret Variables | operator/provider UI | `OPEN EXTERNAL` |
| `DEBT-WORKER-004` | Deploy the current Worker source with token-authorized Wrangler or dashboard deployment | deployment owner | `OPEN EXTERNAL` |
| `DEBT-WORKER-005` | Run ready-release → Pages → Mini App → single-recipient Telegram canary and receipt query | deployment owner | `OPEN EXTERNAL` |
| `DEBT-ENV-001` | Historical untracked test artifacts in the shared checkout | separate hygiene task; never stage during feature work | `OPEN NON-PRODUCTION` |

## Gate decision

The local canonical architecture and regression gates pass.  The production
canary is intentionally not marked `PASS`: the public Worker is reachable but
its current deployment cannot reach Supabase, and no token-authorized deploy or
provider-secret entry is available to this checkout.  No Telegram message was
sent and no high-risk notification was enabled.
