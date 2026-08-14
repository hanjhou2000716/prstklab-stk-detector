# REQ-ADD-012 — Railway event-ledger boundary

## Scope

`railway-monitor/ledger_store.py` is the canonical persistence boundary for
event-ledger identities, source URL merging, category cooldowns, escalation
exceptions, reminder timestamps and retention. The monitor still owns event
normalization and policy decisions; it passes normalized identity facts to the
store and keeps the existing `SeenStore` API for compatibility.

## Safety contract

- Canonical keys and verified source URLs remain stable across polling cycles.
- A repeated event is suppressed during cooldown unless it is new, escalated,
  or the cooldown has elapsed.
- Ledger retention remains at least 30 days; no event evidence is removed by a
  short operator-configured window.
- This module does not classify or fabricate market evidence and cannot bypass
  the release gate or Telegram delivery policy.

## Verification and rollback

- `tests/test_railway_ledger_store.py` covers first observation, source merge,
  cooldown/escalation behavior and retention.
- Combined ledger/delivery/classification/monitor suite: `94 passed` in an
  isolated workspace basetemp. Changed-module Ruff, `mypy src`, compileall and
  frontend syntax checks pass.
- Revert the extraction commit to restore the prior compatibility methods;
  SQLite rows and schema are additive and remain readable.
