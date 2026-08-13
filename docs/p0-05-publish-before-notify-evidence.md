# P0-05：發布成功後才推播 — Gate evidence

## Contract

Production notification paths must be ordered as:

`prepare → schema/release validation → immutable/public publish → public release gate → Telegram → delivery receipt`.

The scheduled brief, official event and emergency workflows now have explicit
static contract tests. Their send steps require `release_gate.outputs.allowed`
and carry the release/snapshot identity into the receipt callback. The Creator
lane is additionally gated by the parent release and its opt-in flag. The
`notify.yml` photo smoke path remains a separate, explicitly scoped test path
requiring one supplied recipient and is not a production broadcast.

## Traceability

| Requirement | Task | Implementation | Verification | Regression | Status |
|---|---|---|---|---|---|
| REQ-P0-05-DOD-01 | Release-before-notify workflow contract | `.github/workflows/scheduled-brief.yml`, `official-event-monitor.yml`, `emergency-alert.yml` | `tests/test_publish_notify_contract.py::test_*requires*gate` | send steps cannot be moved before gate without CI failure | PASS / LOCKED |
| REQ-P0-05-DOD-02 | Delivery receipt lineage | production workflow receipt env blocks | `test_production_receipts_bind_release_and_snapshot` | receipt remains tied to release/snapshot | PASS / LOCKED |
| REQ-P0-05-DOD-03 | Scoped non-production photo smoke | `.github/workflows/notify.yml` | `test_scoped_photo_smoke_is_explicitly_separate_from_production_delivery` | no production recipient broadcast in CI | PASS / LOCKED |

## Evidence

- Local targeted contract suite: recorded in the PR checks.
- Full repository CI must pass before this task is marked locked in the
  migration ledger.

## Rollback

Revert the atomic test/documentation commit. Existing runtime release gates
remain unchanged; no data or secret migration is required.
