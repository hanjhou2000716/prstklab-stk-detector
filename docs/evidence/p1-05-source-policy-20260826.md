# P1-05 source-policy evidence — 2026-08-26

## Scope

This change makes the versioned market source policy part of every normalized
quote's provenance.  It does not replace provider fetchers or claim that an
unavailable second source was observed.  The release restore path also treats
the selected `site/data` tree as an exact snapshot, removing local public
artifacts that are absent from the immutable branch so a manifest cannot be
combined with stale files.

- `TAIEX`: TWSE cash is the displayed value; TAIFEX TXF is a direction/time
  check only (`comparison_basis=direction_only`).
- `TPEx`: TPEx is primary and TWSE MIS is the declared secondary source.
- `BTC`/`ETH`, commodities and VIX retain their declared policy thresholds.
- `TPEx`/`TPEX` labels resolve to the same policy; no case-sensitive fallback
  can silently turn a declared source into `policy_missing`.

## Verification

- Targeted source-policy, artifact and data-release tests: **66 passed**.
- Full repository regression: **1468 passed** (`--basetemp=.tmp-full-source-policy-20260826e`).
- Ruff checks for changed modules: **pass**.
- Mypy checks for changed modules: **pass**.
- `src.runtime_audit`: contract audit **pass**; local stale-data warnings remain
  explicit and do not qualify a release.
- `src.production_e2e`: offline release, renderer, photo and Telegram contract
  checks **pass** without production side effects.
- GitHub PR #791 security checks: dependency review, SBOM and CodeQL **pass**;
  quality/dry-run was **pass** after the latest push.

## Limitations and rollback

This evidence is local/CI evidence only; it does not assert live Railway,
Pages or Telegram availability.  Reverting the source-policy commits restores
the previous provenance shape without deleting market data or event history.
