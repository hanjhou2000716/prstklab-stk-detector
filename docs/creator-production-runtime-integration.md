# Creator production runtime integration

This integration branch consolidates the previously reviewed Creator and
external-intelligence runtime stack onto the current `main` branch.  It does
not merge any historical branch by itself and does not publish private Gmail
content or Creator media.

## Runtime path

The scheduled runtime now follows this order:

1. load sanitized Creator records;
2. build the release candidate and pass the existing release gate;
3. classify Creator provider health separately from core market health;
4. read the signed Railway delivery history when configured;
5. dispatch only a newly published Creator episode;
6. persist notification lineage in the private Railway delivery history.

FinancialJuice and other external-event records use the shared event
classifier and evidence gate.  Vendor importance remains distinct from PRStK
risk, and Creator commentary never contributes to event evidence authority.

## Fail-closed rules

- A configured Railway history endpoint that cannot be verified blocks a new
  Creator delivery instead of risking a duplicate notification.
- Parser failures and filtered records are reported as source failures, not as
  `no_new_content`.
- Creator provider failure does not block a valid core market release.
- Creator notifications are emitted only after the public release gate.
- Public artifacts contain structured summaries and hashes only; raw Gmail
  bodies, recipient IDs and private media are excluded.

## Migration

All contract changes are additive.  Deployments without Creator configuration
remain in `configuration_missing`; existing market, event and research release
paths continue to operate.  Railway adds a signed read-only delivery-history
route and accepts the bounded `notification_keys` field in delivery callbacks.

Required secrets and variables are documented in the existing Creator runtime
runbook.  Their values must remain in GitHub/Railway secret stores.

## Verification

- `uv run ruff check src tests`
- `uv run mypy src`
- focused Creator/Gmail/FinancialJuice/release tests: 118 passed
- full repository regression: 1014 passed
- runtime audit completed without blocking issues; the checked-in sample data
  remains intentionally non-ready and reports its missing event/research
  snapshots as warnings rather than being promoted to production
- offline external-intelligence E2E passed without network or secrets
- production E2E passed with a mocked single recipient, a 1080x1350 rendered
  card, a ready Creator release and a delivery receipt

## Rollback

Revert this integration merge commit.  The previous ready public release and
core market/event monitoring remain valid; disable Creator notification and
Gmail ingestion variables before redeploying Railway if an external provider
must be isolated.
