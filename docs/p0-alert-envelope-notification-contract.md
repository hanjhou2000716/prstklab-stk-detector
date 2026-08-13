# P0 Alert Envelope Notification Contract

The common alert envelope now carries the same `notification_id` used by the
budget, ledger and external fan-out paths. It is derived from the explicit
alert ID first, then the compound item or event cluster identity. Existing
release provenance and lifecycle validation remains mandatory.
