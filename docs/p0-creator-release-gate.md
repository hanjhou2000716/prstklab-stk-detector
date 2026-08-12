# Creator release gate

The creator release builder is the public boundary after email parsing. It
rejects parser failures (`parse_failed`, `unsupported_template`,
`invalid_source`, and `duplicate`) before normalization or release assembly.
Adapter-produced records must also declare `required_fields_present=true`.
Records without an episode title are rejected even when their source is known.

This separation keeps an email that was received but could not be parsed out of
the public creator drawer. The input remains available to the private Railway
DLQ for template review. No parser failure is converted into an empty but
healthy release, and no unverified creator opinion unlocks a high-risk alert.

The gate is additive and backward-compatible with sanitized historical records
that omit `parse_status`; those records continue through the existing
normalizer, subject to the existing source and deduplication checks.
