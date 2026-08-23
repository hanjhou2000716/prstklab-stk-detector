# P0 cross-check provenance fix (2026-08-15)

The post-merge Pages deployment exposed a producer/schema mismatch: market
artifacts emitted `crosscheck_sources[].label` and `url`, while the canonical
market contract requires `provider` and `source_url`. The release gate
correctly rejected the data instead of publishing an invalid release.

This fix keeps the display-compatible legacy fields and adds the canonical
fields at every producer boundary:

- Taiwan TWSE/TAIFEX cross-checks
- Binance/CoinGecko crypto cross-checks
- Yahoo/Stooq/Nasdaq public-market cross-checks
- legacy provider-map normalization

Verification:

- targeted cross-check/artifact tests: 53 passed
- full repository regression: 1246 passed, 1 skipped
- Ruff: pass
- Mypy: pass (167 source files)
- Python compileall: pass

The Pages deployment failure remains fail-closed until this producer fix is
merged and a fresh `data-release` snapshot is published. No invalid release
was exposed.

Rollback: revert this PR; the prior release-gate behavior remains fail-closed.
