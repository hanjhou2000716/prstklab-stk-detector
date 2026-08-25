# Evidence: FinancialJuice release-lineage contract

Requirement: P0-12 / P0-29 — reviewed FinancialJuice observations must reach
the release lane without losing provenance or changing PRStK risk.

## Local evidence

- `tests/test_financialjuice_release_contract.py`
- scheduled preparation and priority regression suite: **30 passed**
- the contract is called by `src/scheduled_delivery.py` before `write_snapshot`
- invalid lineage emits `financialjuice_release_contract_blocked` and does not
  write a publishable snapshot

## External boundary

Railway Gmail/PubSub configuration and a real qualifying FinancialJuice
delivery receipt remain external acceptance gates. This change does not claim
that live ingress is healthy or that a production Telegram message was sent.
Those states remain explicit (`configuration_missing`, `no_new_content`, or
`needs_reverify`) until observed from the deployed main release.
