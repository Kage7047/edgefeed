# 4. The ledger records opportunity lifecycles, not snapshots

**Status:** accepted, 2026-11-04

**Context.** One snapshot proves nothing: edges flicker. The go/no-go question needs frequency,
duration and size.

**Decision.** Each scan stores every pair's top-of-book quote and spread. An opportunity row is
opened when an edge clears the recording bar, updated (scans seen, best size and profit) while it
lasts, and closed on the first scan where it is gone. A pair whose fetch failed is treated as
unknown and does not close anything. The store is SQLAlchemy Core, SQLite by default and Postgres
in Docker; the collector writes and the API only reads.

**Consequences.** `edgefeed report` can state medians and p90s of edge duration and the number of
worth-it edges per day. Quotes are pruned after 30 days to keep SQLite small; opportunities are
kept forever.
