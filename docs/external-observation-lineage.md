# External observation release lineage

The read-only external acceptance probe now verifies two separate claims:

1. Railway exposed a bounded, public-safe observation projection; and
2. the same reviewed observation set was published by Pages.

The probe never stores observation IDs, message IDs, mail content, senders,
recipients, or secrets. It calculates a one-way SHA-256 over sorted pairs of
`observation_id` and normalized source label. The release manifest contains the
matching count, source list, status (`ready` or `no_event`) and identity hash.

The market artifact's `external_observations` is the complete sanitized set
returned by the Railway export, including registered Creator providers. The
market-event classifier consumes the derived `financialjuice_observations`
subset only; Creator material remains in the attributed-content lane. This
separation prevents editorial observations from being treated as FinancialJuice
market evidence while still proving that every reviewed row reached the same
release.

If the Railway projection is healthy but the manifest is missing or differs,
the `external_observations` gate becomes `needs_reverify` and the overall
acceptance remains fail-closed. This prevents a healthy ingress from being
mistaken for proof that the observation reached the published release.

The check is read-only and does not promote a release, send Telegram, or alter
Railway/Gmail configuration. A successful production capture must show both
`external_observations.status=pass` and `pages_artifacts.status=pass`.
