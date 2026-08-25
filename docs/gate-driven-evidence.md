# Gate-Driven v3 evidence contract

`config/gate_evidence.json` is the machine-readable companion to the existing
P0 traceability documents. It does not create a second runtime pipeline or
upgrade an external result by assumption. It records, for each P0 requirement:

- implementation paths;
- verification paths;
- objective evidence references;
- regression and preservation identifiers; and
- one of the allowed Gate-Driven statuses.

`LOCKED` is only valid when implementation, verification, evidence, regression
and preservation references are all present. The default audit therefore
returns `needs_reverify` while known external debt remains open; it never
turns missing Gmail, Railway, Pages or Telegram evidence into `no_event` or a
successful production claim.

Run the structural/offline audit with:

```text
python scripts/verify_gate_evidence.py
```

The final merge/production gate is intentionally stricter:

```text
python scripts/verify_gate_evidence.py --strict
```

Strict mode fails until the completion-debt and regression ledgers contain no
`OPEN` entries. This separation lets normal CI prove the registry is valid
without masking the fact that external acceptance still needs real evidence.

## Migration and rollback

The registry is additive and reads the existing `docs/p0-requirement-traceability.md`
evidence; it does not rewrite release data, Gmail state, Railway state or
Telegram receipts. A missing or malformed entry fails closed. To roll back,
revert this PR; the existing runtime gates and historical traceability document
remain unchanged.

## Verification

- `python scripts/verify_gate_evidence.py` — structural audit, reports open
  external debt as `needs_reverify`.
- `python -m pytest -q --basetemp=.tmp-gate-pytest-20260825 tests/test_gate_evidence.py tests/test_p0_traceability_registry.py tests/test_canonical_overlap_audit.py` — 8 passed.
- Full repository regression on this branch — 1414 passed.
- Ruff, Mypy, compileall, canonical-overlap and intelligence-contract audits
  passed.
