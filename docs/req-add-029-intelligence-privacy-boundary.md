# REQ-ADD-029 — Intelligence privacy boundary

## Scope

Direct callers of the shared intelligence pipeline may provide a parsed
FinancialJuice envelope instead of using the scheduled file loader. The
pipeline now applies the same privacy boundary in that path: transport IDs,
raw mail fields and recipient metadata are removed before clustering or risk
evaluation.

Unresolved compound envelopes are ignored rather than converted into an event.
This keeps the existing fail-closed contract while preserving the separate
parser/source-health signal for the caller.

## Verification

The intelligence pipeline and contract suite covers compound fan-out,
privacy-field removal, unresolved envelopes, pending evidence, and confirmed
cross-source behavior. The scheduled loader remains the canonical runtime
boundary; this defensive guard prevents accidental leakage from direct use.

## Rollback

Revert the atomic commit. The scheduled loader's privacy boundary and existing
event classification remain unchanged.
