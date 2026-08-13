# P0-22 event timeline and feedback evidence

Timeline retrieval preserves the event-cluster continuity key while applying
auditable exact filters. Feedback accepts only the documented labels, strips
recipient identifiers, requires review, and reports quality metrics only from
reviewed rows. Feedback never changes notification policy automatically.

Rollback is the atomic commit revert; the existing timeline and review queue
remain available.
