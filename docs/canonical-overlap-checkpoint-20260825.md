# Canonical Creator／FinancialJuice overlap checkpoint (2026-08-25)

This checkpoint records the current stacked continuation. It does not create a
second Creator, FinancialJuice, news classifier, or Telegram dispatcher.

## Canonical path

```text
provider registry / adapter
→ sanitized observation
→ shared event classifier
→ evidence, lifecycle and quality gates
→ release manifest + artifact hashes
→ Pages
→ Mini App / release-gated Telegram
→ delivery receipt
```

Creator content remains editorial enrichment. FinancialJuice vendor priority
does not become PRStK risk evidence. Official confirmation and relevant market
synchronization remain separate gates.

## Current stack

| PR | Responsibility | State |
|---|---|---|
| #757 | redacted external acceptance gate summary | open, CI green |
| #758 | shared classifier for news and live events | open, CI green |
| #759 | shared classification evidence in news cards | open, CI green |
| #760 | signed, privacy-safe external observation probe | open, CI green |
| #761 | bind the reviewed observation set to the public release manifest | open, CI green |

PR #761 is based on the #760 branch and is the current checkpoint head. The
stack must be merged in order; no branch should be deleted before its dependent
PR is merged.

## Evidence state

- Local targeted acceptance/release-gate suite: 37 passed.
- Full isolated repository regression at the checkpoint: 1409 passed.
- Ruff, Mypy and `compileall`: passed.
- PR #761 Actions: test-and-dry-run, CodeQL, dependency review and SBOM all
  passed.
- The acceptance probe stores only counts, normalized source labels and a
  one-way observation identity hash. Raw mail, transport IDs, recipients and
  secrets remain outside the artifact.

## Controlled external capture (branch evidence)

The read-only capture on the PR branch reached the live Railway endpoints on
2026-08-25. Railway returned a ready sanitized set with two observations from
`financialjuice` and `jenny`; Gmail Watch was healthy and the Creator/FJ
projections were present. The same capture also showed that the public Pages
manifest still described an older observation set, so the lineage gate correctly
reported count, source and identity-hash mismatches. GDELT was independently
reported as HTTP 429 and delivery was partial; neither condition was treated as
success.

The branch now publishes the complete sanitized set in
`market.json.external_observations` and keeps the FinancialJuice-only derived
input in `financialjuice_observations`. A manual scheduled run defaults to
`notify=false`, so an operator can publish and verify a release without sending
Telegram or Creator messages. The first attempt was rejected before any job
step because the `github-pages` environment only allows protected branches;
this is an environment policy boundary, not a renderer or data failure. After
the stack is merged to `main`, run the same publish-only dispatch and then run
the read-only external acceptance probe again.

## External gates still open

The following require a controlled post-merge run and cannot be fabricated by
local tests:

1. Railway Gmail Watch and sanitized Creator/FinancialJuice observations.
2. The same observation set appearing in a `status=ready` Pages release.
3. Single-recipient Telegram receipt bound to alert, snapshot and release IDs.
4. Telegram WebView visual/deep-link acceptance.
5. Live source freshness and provider health (including bounded GDELT 429).

Until those proofs exist, the external acceptance state remains
`NEEDS_REVERIFY`; no high-risk alert or production broadcast is enabled by
this checkpoint.

## Rollback

Revert the PR #761 commit to remove the external lineage comparison. Existing
release validation, privacy redaction, notification deduplication and
fail-closed behavior remain unchanged.
