# P1-05 source-policy evidence — 2026-08-26

## Scope

This change makes the versioned market source policy part of every normalized
quote's provenance.  It does not replace provider fetchers or claim that an
unavailable second source was observed.

- `TAIEX`: TWSE cash is the displayed value; TAIFEX TXF is a direction/time
  check only (`comparison_basis=direction_only`).
- `TPEx`: TPEx is primary and TWSE MIS is the declared secondary source.
- `BTC`/`ETH`, commodities and VIX retain their declared policy thresholds.
- `TPEx`/`TPEX` labels resolve to the same policy; no case-sensitive fallback
  can silently turn a declared source into `policy_missing`.

## Verification

- Targeted contract and artifact tests: **49 passed**.
- Full repository regression: **1464 passed** (`--basetemp=.tmp-full-source-policy-20260826c`).
- Ruff checks for changed modules: **pass**.
- Mypy checks for changed modules: **pass**.
- GitHub PR #791 security checks: dependency review, SBOM and CodeQL **pass**;
  quality/dry-run was **pass** after the latest push.

## Limitations and rollback

This evidence is local/CI evidence only; it does not assert live Railway,
Pages or Telegram availability.  Reverting the source-policy commits restores
the previous provenance shape without deleting market data or event history.
