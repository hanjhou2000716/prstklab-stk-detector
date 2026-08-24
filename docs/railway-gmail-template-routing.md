# Railway Gmail source routing

## Why messages were rejected

The Railway ingress identified a known Creator or FinancialJuice sender and
then required a small set of English template labels before invoking the
canonical parser. Real Gmail editions legitimately change their labels and
often contain Chinese prose, so those messages were recorded as
`known_source_template_not_matched` even though the source identity was
trusted.

## Current contract

- A source marker in a decoded Gmail subject or human sender display name is
  enough to enter the canonical parser when both subject and body are present.
- A provider domain by itself is **not** trusted. Generic mail from a known
  domain with an unrelated subject remains in the DLQ.
- The canonical parser still decides whether the content is usable. If its
  template adapter cannot extract a structured record, the compatibility
  parser may produce an explicitly unverified review row; otherwise the
  message remains `unsupported_template`/`parse_failed`.
- A message that routes successfully but yields no public-safe observation is
  treated as a parser failure, never as a successful empty scan.

This keeps the route tolerant to normal editorial wording changes without
turning arbitrary mail into an alert. Creator observations remain unverified
until the existing review, cross-source and release gates pass.

## Verification

The regression suite covers:

- FinancialJuice subject identity with a short natural-language body.
- RFC 2047-decoded Creator display name and subject.
- Generic provider-domain mail with no source-labelled subject (still DLQ).
- Canonical parser failure propagation and no-public-observation protection.

Rollback is a single revert of the routing commit; the previous strict
template gate is restored without changing stored raw mail (raw content is
never published).
