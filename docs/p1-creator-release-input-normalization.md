# Creator release input normalization

Release identity uses creator content, not derived timestamps or validation
fields. `generated_at`, status, validation errors, artifact hashes and lineage
IDs are excluded from the identity seed. This prevents equivalent creator
payloads from creating different parent release IDs merely because a worker ran
at a different time or produced a different diagnostic message.
