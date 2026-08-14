# P0-12 multilingual event matching evidence

## Contract

News and live-event records share one classifier. It normalizes Unicode width,
case, whitespace, punctuation and all descriptive fields before evaluating
Traditional Chinese, Simplified Chinese and English aliases. A match records
the category, reason and matched terms; an unmatched record remains explicitly
unclassified and cannot silently become a notification.

This contract is classification only. Official-source and market-synchrony
gates remain separate and are still required for strict geopolitical alerts.

## Verification

`tests/test_p0_12_multilingual_event_contract.py` covers Traditional/Simplified
policy aliases, case-insensitive English entities/actions, all-field context,
Unicode-width normalization and explicit no-match behavior. Existing event
classifier, crosscheck and alert regression suites remain required.

## Rollback and preservation

Revert the atomic P0-12 evidence/test commit if needed. The existing classifier
and strict notification gate remain unchanged; rollback must not treat a
keyword match as official confirmation or market synchronization.

## Traceability

- Requirement: P0-12 multilingual event matching
- DoD: multilingual aliases and normalized matching are auditable and do not
  bypass evidence gates
- Evidence: targeted contract tests, existing classifier/crosscheck suites,
  and required PR CI
