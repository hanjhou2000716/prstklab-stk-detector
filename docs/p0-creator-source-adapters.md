# P0 Creator source adapters

`src/creator_source_adapters.py` is the production parser boundary for the
Haojiao and Gooaye creator newsletters. It accepts only sanitized text held in
memory and returns derived, public-safe fields. The adapter recognizes labelled
sections for title, fact, opinion, takeaway, and risk; it never infers a claim
from an unlabeled paragraph.

An accepted record is marked `parse_status=parsed`, carries a stable
`template_fingerprint`, and keeps `verification_state=unverified` until the
official-source and market-synchronization gates independently pass. An
unknown or changed template is returned as `unsupported_template` with a
reason and fingerprint. Historical sanitized fixtures may use the compatibility
parser, which is explicitly labelled `legacy-creator-parser` and is not used to
silently promote an event.

The adapter output contains no raw body, attachment, local path, or private
URL. Railway ingestion must persist the raw message only in the private store
and place unsupported templates in the DLQ for operator review. Rollback is
additive: revert the adapter binding and retain the prior parser for historical
replay.
