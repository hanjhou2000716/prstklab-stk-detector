# Creator Intelligence pipeline boundary

`build_creator_intelligence_release` is the only offline producer entry point
for creator-safe releases. It accepts sanitized records, normalizes source and
episode identity, deduplicates episodes, drops private or unknown records, and
builds an artifact tied to the parent market/event release. Empty accepted
input is a valid `ready` artifact with `source_state=no_creator_insights`; it is
not evidence that a creator source failed.
