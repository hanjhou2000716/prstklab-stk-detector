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
