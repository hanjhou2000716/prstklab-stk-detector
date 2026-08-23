# Canonical overlap audit

`python scripts/verify_canonical_overlap.py` is a read-only, offline guard for
the production boundaries that previously could drift silently.

It verifies that:

- Railway root and packaged policy JSON are byte-independent copies of the
  canonical `config/` payloads (compared after JSON parsing).
- Every generated Railway Python module carries a canonical source marker and
  a SHA-256 matching the current `src/` module.
- Email intelligence derives Creator identities from the provider registry.
- News feeds derive their catalog from the canonical News Intelligence
  registry, rather than maintaining a second provider table.

The check does not call Railway, Gmail, Telegram, or any external endpoint and
does not read secrets. A non-zero exit means the generated deployment bundle
must be regenerated and reviewed before release.
