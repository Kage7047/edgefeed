# EdgeFeed — Build Plan v2 (revised after research + live spike)

> Supersedes the original `prediction-market-edge-tool-BUILD-PLAN.md`.
> The original's architecture, repo layout (§6), data model (§8), and compliance
> guardrails (§2) still stand — keep them. This document records what **changed**
> after (a) verifying the 2026 API/fee reality, (b) researching the competitive
> landscape, and (c) running a live zero-cost spike against both venues.
> Date: 2026-09-13.

---

## 0. TL;DR — is this a viable $0 B2C product?

**Qualified yes — but not as a plain "cross-venue arb scanner."** That specific
product is now a crowded red ocean. The viable wedge is **curated quality + speed +
news-latency + distribution**, monetized to an audience that demonstrably pays.

- ✅ **Market is large and paying.** Polymarket ~643k active traders (Apr 2026);
  combined Poly+Kalshi volume ~$44.8B/month (Jun 2026). Incumbent tools charge real
  money (ArbBets $59/mo).
- ✅ **$0 to build and run the MVP.** Public data is free; Telegram, SQLite, Vercel
  Hobby, Stripe Payment Link, and Oracle Cloud Always Free cover the whole MVP with
  $0 fixed cost.
- ⚠️ **The plan's stated moat is gone.** Cross-venue matching at scale is already
  shipped by ArbBets (990+ matched markets, 100+ arbs/day), Oddpool, Predictefy,
  StartupHub.ai (free API + MCP), an Apify actor, and open-source bots. The v1 claim
  that this is "thin and hard to build" is **false in 2026.**
- ⚠️ **Naive arb edges look thin after fees.** Polymarket now charges taker fees too
  (V2, Mar 2026), and the live spike found **no arb surviving fees** in sampled pairs.
  Edges also close in **15–60s**, so a 30–60s poller validates demand but is too slow
  to *be* the product.

**Strategic consequence:** treat arb as the **free, top-of-funnel hook** and make the
**paid tier the news-latency + realtime differentiator**. Do not try to out-arb the
incumbents on coverage; win on trust (curated, verified, track-record) and on the
harder signal they mostly don't do (news-latency).

---

## 1. Competitive reality (new section)

| Tool | What it does | Price | Implication |
|---|---|---|---|
| ArbBets | 990+ matched markets, 100+ arbs/day, API | $59/mo | Direct incumbent; proves willingness to pay AND that coverage isn't a moat |
| Oddpool | Cross-venue data, depth, arb, datasets | paid/data | Competes on data breadth |
| Predictefy | Multi-venue arb scanner | freemium | Commodity arb |
| StartupHub.ai | Cross-venue arb feed + free JSON API + MCP | free | Commoditizing the raw signal |
| Apify actor / OSS bots | DIY arb finders | ~free | Floor price of arb ≈ $0 |

**Takeaway:** the raw arb number is being commoditized toward free. Differentiate on
(1) **precision/trust** (curated + verified + public track record — most tools surface
spreads that evaporate), (2) **news-latency** (few do it well; it's the plan's Phase 3),
(3) **distribution + UX** (Telegram-native, great edge cards, a niche community).

---

## 2. Verified technical facts (replaces the §13 VERIFY items)

**Polymarket** — public, no auth for reads.
- Gamma metadata: `https://gamma-api.polymarket.com/markets` (`closed=false&active=true`,
  supports `order=volumeNum&ascending=false`, `limit`/`offset`). Fields: `question`,
  `outcomes`, `outcomePrices`, `clobTokenIds` (JSON-string arrays), `volume`, `liquidity`.
- CLOB book: `https://clob.polymarket.com/book?token_id=<id>` → `{bids:[{price,size}],
  asks:[{price,size}]}` (prices 0–1 strings; best ask = **min** ask price).
- Order **placement** is IP-gated (US/UK/EU blocked). **Reads are fine** — we only display.

**Kalshi** — public reads, but discovery must use events.
- ⚠️ **Do NOT use the flat `/markets` firehose for discovery** — ~99.97% is auto-generated
  parlay combos (`MVE`/`CROSSCATEGORY`) with no prices. Use
  `GET /trade-api/v2/events?status=open&with_nested_markets=true` and flatten nested
  markets, skipping any ticker containing `MVE`/`CROSSCATEGORY`.
- ⚠️ **Fields renamed:** prices are `yes_ask_dollars`, `yes_bid_dollars`,
  `no_ask_dollars` (in **dollars**, ×100 for cents). Sizes are `_fp` fixed-point
  (`yes_ask_size_fp`, `volume_fp`), liquidity is `liquidity_dollars`. The old
  cents-named fields (`yes_ask`, etc.) are gone.
- Orderbook: `GET /trade-api/v2/markets/{ticker}/orderbook` for depth.
- REST reads need no auth. **WebSocket requires RSA request signing even for public
  channels** — so Phase-2 realtime needs a (free) Kalshi API key + RSA-PSS/SHA-256 signing.

**Fees (the crux — VERIFY before trusting a number).**
- Kalshi taker: `ceil_to_cent(0.07 × C × (1−C))` per contract, C in dollars; peaks
  ~1.75–2¢ near C=0.50.
- Polymarket taker (V2, Mar 2026): category-capped per share — **geopolitics/world = 0¢**,
  politics/finance/tech ≈ 1¢, sports/econ/culture/weather ≈ 1.25¢, crypto ≈ 1.75¢.
  (Historically 0% — this is new and it materially tightens the arb math.)
- **Design change:** the threshold must be **per-category**, not a single
  `ARB_MIN_NET_SPREAD_CENTS=3`. Prioritize **fee-free Polymarket categories
  (geopolitics/world)** in curation — you only pay one venue's fee there.

---

## 3. The $0 stack (replaces §5/§11 for the MVP)

| Need | v1 (paid) | v2 ($0) |
|---|---|---|
| Always-on host | Hetzner VPS | **Oracle Cloud Always Free** Arm VM (only real always-on free tier left) |
| Scheduler (alt) | — | **GitHub Actions cron** (≥5-min cadence; fine for the free/delayed tier) |
| DB | Postgres+Redis | **SQLite** (keep through validation) |
| Alerts | Telegram | Telegram Bot API (free) |
| Landing | Next.js/Vercel | Vercel Hobby (free) |
| Payments | Stripe Billing | Stripe **Payment Link** + manual fulfillment (free fixed cost) |
| LLM | provider | **none in MVP** (curated = no COGS) |

Recurring fixed cost through the validation gate: **$0.**

---

## 4. Revised phase plan

### Phase 0 — Scaffold (unchanged intent)
Repo per original §6; `.env.example`; base `VenueClient`; SQLite models; lint+test CI.
**Reuse the spike's verified ingestion code** (`spike/arb_spike.py`) as the seed for
`core/ingestion/kalshi.py` (events endpoint!) and `polymarket.py`.

### Phase 1 — MVP: curated arb as the FREE hook (~2 weeks)
Changes from v1:
- **Kalshi ingestion via `/events?with_nested_markets=true`**, combo-filtered, new field names.
- **Per-category fee model**; curate toward **fee-free/low-fee** overlaps first.
- **20–30 curated pairs** across liquid politics/geopolitics/econ (spike shows auto-match
  is too sparse to trust). Start the `curated_pairs.yaml` from what the spike surfaces.
- **Track-record ledger from day 1** = the trust asset AND the marketing content.
- **Telegram free channel** posts curated arb; realtime is the paid promise (Phase 2/3).
- Landing page: live/recent verified edges, free-join CTA, Stripe link, waitlist + referral, disclaimer.

**Acceptance / Validation gate (revised):** run the detector on a cron for ≥1 week over
curated pairs and **log every candidate**. Proceed only if:
1. Real edges survive fees + liquidity filter **repeatably** (not just once). *If they
   essentially never do → the arb kill-signal fired; pivot the paid tier to news-latency now.*
2. Free channel gains organic subscribers (a few dozen).
3. A handful pay / join the paid waitlist.
4. Interviews confirm actionability.

### Phase 2 — Realtime + auto-matching (bring FORWARD; it's the product, not a nicety)
Edges close in 15–60s, so the **sellable** product needs the low-latency path sooner.
- Kalshi WebSocket (RSA-signed) + Polymarket CLOB WS.
- Auto-matching = **embeddings + LLM adjudication + deterministic guardrails**, NOT fuzzy
  strings (spike showed fuzzy is too sparse). Must filter Kalshi combos before embedding.
- SQLite → Postgres + Redis. Backtest harness.

### Phase 3 — News-latency tier = THE paid differentiator (elevate priority)
This is the least-commoditized signal and the real reason to pay. Build it as a first-class
paid tier, not an afterthought. News ingestion → event→market mapping → LLM judgment with
hard cost controls → latency budget + hit-rate calibration.

### Phase 4 — Platform (unchanged): FastAPI, accounts, Stripe Billing tiers, dashboard, more venues (Opinion/Predict.fun widen the arb surface).

### Phase 5 — Execution assist (unchanged): deep-links only; no custody. Handle per §2.

---

## 5. Immediate next steps
1. ✅ Spike built + run (`spike/`) — thesis probed at $0.
2. **Run the spike on a schedule for a week** over curated pairs; log to SQLite. This IS
   the start of the track-record ledger and the real validation gate.
3. Promote `spike/arb_spike.py` ingestion into `core/ingestion/*` (Phase 0 scaffold).
4. Decide the wedge now: **arb = free hook, news-latency = paid moat.** Build accordingly.

---
*Backing evidence: see `spike/README.md` for the live findings, and the research sources
in the session transcript (fees, API guides, competitive landscape, free-tier hosting).*
