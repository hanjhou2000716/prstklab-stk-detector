# P0-18 external alert trust boundary

External alerts are accepted only from the registered source set, with HTTPS
provenance and signed canonical payloads. GDELT requires independent domains;
black-swan/conflict warnings require market synchronization, and high-risk
escalation additionally requires explicit official confirmation. Signature
verification covers the normalized event, time and evidence so tampering cannot
silently change delivery eligibility.

The contract tests cover provenance rejection, high-risk confirmation and HMAC
tamper detection. Unverified external observations remain visible but cannot
cross the high-risk notification gate.
