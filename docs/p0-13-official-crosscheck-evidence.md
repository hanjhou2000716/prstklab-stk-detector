# P0-13 official-source crosscheck evidence

## Contract

Crosscheck is provenance-aware. An event is only marked `official_confirmed`
when an official source and an independent domain share the same normalized
event anchors. Repeated reports from one domain remain pending; missing source
URL/provenance remains visible but unverified. Crosscheck status never by
itself asserts market direction or authorizes a high-risk alert.

## Verification

`tests/test_p0_13_official_crosscheck_contract.py` covers official plus
independent-domain confirmation, same-domain duplicate protection, and missing
provenance. Existing event-crosscheck and event-evidence suites remain part of
the required regression set.

## Rollback and preservation

Revert the atomic P0-13 test/evidence commit if necessary. Preserve the
fail-closed pending state and source URL lineage; do not replace provenance
with a provider label alone.

## Traceability

- Requirement: P0-13 official/source crosscheck
- DoD: official confirmation and independent source evidence are explicit;
  unverified events remain visible and non-deliverable
- Evidence: targeted crosscheck/evidence tests and required PR CI
