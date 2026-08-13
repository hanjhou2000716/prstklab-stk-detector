# External event pipeline

Scheduled reports and live source monitors use the same `build_external_event`
contract. It combines the full story fields, source observations, classifier
result, event cluster, official confirmation, and market synchronisation into
one fail-closed decision.

FinancialJuice remains a discovery source. Its vendor importance is metadata,
not PRStK risk. A relay item stays `pending_confirmation` until the required
official and market evidence is present. The result keeps `pending_reasons`
(`等待官方核對`／`等待市場同步` or the corresponding policy reason) for the
Mini App; it is never silently dropped.

The pipeline emits a versioned `external-event.schema.json` envelope and can be
used by offline E2E tests without Gmail, network access, or Telegram delivery.
Missing evidence remains observable and cannot become an R3/R4 notification.
