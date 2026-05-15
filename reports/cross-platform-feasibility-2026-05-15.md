# Cross-platform Polymarket↔Kalshi feasibility audit (2026-05-15)

Status: **feasibility audit only, not yet a thesis test**. Found enough
infrastructure issues that a real thesis test needs more time than the
1-hour probe allowed.

## What I tested

The user asked to test the cross-platform thesis (option D from the
research-summary post-mortem): are there persistent price gaps between the
same event on Polymarket and Kalshi that retail couldn't arb away?

This was research-only — the user is based in China and Kalshi is US-only
for execution. Same as the longtail thesis, the value is in establishing
whether alpha exists, not in trading it.

## Five things I learned about the Kalshi API

1. **Public API is accessible from China.** No auth needed for read
   endpoints (`/markets`, `/markets/{ticker}/orderbook`, `/events`,
   `/series`). Verified via `external-api.kalshi.com/trade-api/v2/`.

2. **`/markets?status=open` is dominated by useless multivariate parlays.**
   Sampled 3000 markets through cursor pagination; 100% were
   `KXMVE*`/`KXMVS*` parlay tickers with zero liquidity (no quotes, no
   trades). The default ordering front-loads these.

3. **Real liquid markets are reachable via `series_ticker` queries.**
   Targeted query through 17 known-active series (KXBTC, KXETH, KXFED,
   KXCPI, KXJOBS, KXNBA, KXNFL, KXMLB, etc.) returned 520 single-event
   markets. Of those, 300 had non-empty orderbooks; **27 had quotes on
   both YES and NO**.

4. **`orderbook_fp.yes_dollars` and `no_dollars` are BIDS, not asks.**
   Confirmed by inspection: `KXFED-27APR-T4.25` has yes_dollars max =
   $0.26 and no_dollars max = $0.57. Their sum is < $1, which would be
   instant arb if they were asks. The actual relationships:
   - `best_yes_bid` = max(yes_dollars[*][0])  → last entry, since sorted ascending
   - `best_no_bid` = max(no_dollars[*][0])
   - `yes_ask = 1 - best_no_bid` (synthetic — you can buy YES by shorting NO)
   - `no_ask = 1 - best_yes_bid`
   - bid-ask spread = ask - bid; e.g., on KXFED-27APR-T4.25:
     yes is bid $0.26 / ask $0.43 → spread $0.17, which is huge.

5. **Markets `yes_ask` field in the list endpoint is always None.** The
   listing returns market metadata but no quotes; quotes are only in the
   per-market `/orderbook` endpoint. So scanning requires N orderbook
   calls (one per ticker).

## The harder problem: matching events across venues

Even with corrected interpretation, the thesis test needs **matched
events**. This is the real bottleneck. Examples of why naive matching
fails:

| Topic | Kalshi structure | Polymarket structure |
|---|---|---|
| BTC price | `KXBTC-26MAY1517-B85750` (hourly ladder, ≥ $85,750 at 2026-05-15 17:00 EDT) | "Will Bitcoin hit $150k by June 30, 2026?" (date-bounded threshold) |
| Fed rate | `KXFED-27APR-T4.25` (rate level at FOMC) | "Will the Fed cut rates 25bps at April 2027 FOMC?" (decision binary) |
| 2028 president | `KXPRES28-*` (couldn't find via series_ticker query — 0 events returned) | "Will Trump win 2028 US Presidential Election?" |
| Sport | game-level (`KXMLB-26MAY15...`) per game per outcome | only major championships, not individual games |

In short: same EVENTS exist on both venues, but the BINARIES are
sliced differently. To test the thesis we'd need either:
- An LLM-driven semantic match (which is what WW's `cross_platform.py`
  has: `match_polymarket_kalshi_markets` does Jaccard + LLM verification),
  but it requires both venues' NDJSON files which we don't have on disk.
- A small hand-curated set of ~10 pairs we manually verify.

## What's in the repo now

- `scripts/probe_cross_platform.py` — direct two-venue probe with manual
  pair list. Currently has placeholder empty MANUAL_PAIRS list; needs
  hand-curated mapping to run usefully.
- This report (`reports/cross-platform-feasibility-2026-05-15.md`).

## Two paths forward

**Path A: Use WW's existing pipeline** (`run_cross_platform_scan_once.sh`).
It's a 6-step pipeline that already handles: Kalshi collection, jaccard
matching, LLM semantic verification, orderbook scanning. Bootstrap cost:
need to get `data/polymarket-gamma.ndjson` and the Kalshi candidates
file in shape first. Estimate: 3-4 hours to first verdict.

**Path B: Hand-curate ~10 pairs and run the probe.** Skip the matcher
entirely. Focus on a few known events (2026 NBA Finals, Fed rate
decisions, BTC threshold markets). Estimate: 1-2 hours to first verdict
but limited to the events we manually find.

**Path C: Park the thesis.** Acknowledge the infrastructure cost is
higher than first-pass test should cost. Move to a different research
direction (LLM infra collaboration with WW, or single-platform thesis
not yet tested like hold-to-resolution).

The probe script now uses Kalshi synthetic asks (`1 - best_opposite_bid`).
Before Path A or B gives a real verdict, it still needs hand-curated pairs
or the existing verified-pair pipeline inputs.

---
*Snapshot: 2026-05-15T07:50:00+00:00*
