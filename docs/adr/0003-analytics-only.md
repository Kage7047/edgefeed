# 3. Analytics only: no keys, no orders, no custody

**Status:** accepted, 2026-11-04

**Context.** Executing trades would need venue accounts and keys, KYC, and would put the
project under trading regulation in most jurisdictions. Polymarket order placement is also
geo-restricted.

**Decision.** EdgeFeed reads public market data only. It has no API keys and no code path that
places an order. Output is a ledger, a dashboard and alerts, each with a not-financial-advice
notice.

**Consequences.** The ledger measures whether an edge *was available*, not whether a fill would
have happened; latency between a scan and a human or bot acting is not modelled. That is why the
report counts an edge as actionable only if it was still there on a second scan.
