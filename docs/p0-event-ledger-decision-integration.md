# P0 Event Ledger Decision Integration

The official event delivery path now writes release-gate and alert-budget
suppression decisions to the durable event ledger before returning a safe
skip. This makes Mini App/event-history explanations match the actual send
decision; it does not alter cooldown, release-gate, or fail-closed policy.

Verification: official monitor regression tests cover a budget suppression and
assert the existing no-send behaviour remains unchanged.
