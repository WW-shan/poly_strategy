# Maker Simulation v4 — Corrected fee + train/test split (2026-05-15T04:00:51.953413+00:00)

**Method**: v3 plumbing + two fixes:
  (A) maker fee mode = `zero` (v3 used taker_rate, which was wrong; Polymarket docs: "makers never pay fees")
  (B) 10-day in-sample / 4-day OOS split. Top 18 groups picked by IN-SAMPLE daily $; their OOS sum reported separately.

**Window**: 14 days (2026-04-17 -> 2026-05-01)
**Basket size cap**: $100
**Trades fetched**: 44759 raw -> 2751 qualifying
**Days with trade activity**: in-sample 10, OOS 4
**takerOnly distribution across our markets**: {True: 142}

## Headline (with maker fee = 0)

| Verdict | Daily $ | Annualized |
|---|---:|---:|
| Naive (all 71 groups), in-sample | $+0.63 | $+228 |
| Naive (all 71 groups), OOS | $+0.23 | $+83 |
| Whole window (no split) | $+0.51 | $+187 |
| **Top 18 by in-sample, in-sample** | $+1.73 | $+631 |
| **Top 18 by in-sample, OOS** ← honest verdict | $+0.42 | $+155 |

If top-N OOS << top-N in-sample, the top-N looks like overfitting.
OOS / in-sample ratio for top-18: 0.25

## Top 18 groups — in-sample picked, OOS measured

| Rank | Group | Q | Best markup | IS daily $ | OOS daily $ | OOS/IS |
|---:|---|---|---:|---:|---:|---:|
| 1 | `0x5cddfa5bafea...` | Will the Democrats win the Geo vs Will the | $0.050 | $+0.392 | $+0.000 | +0.00 |
| 2 | `0x8941a4153cb2...` | Will the Democrats win the Ver vs Will the | $0.050 | $+0.225 | $+0.031 | +0.14 |
| 3 | `0x2ecd963d91df...` | Will the Democrats win the Iow vs Will the | $0.050 | $+0.211 | $+0.027 | +0.13 |
| 4 | `0xf5f3857c3391...` | Will the Democrats win the Ohi vs Will the | $0.030 | $+0.179 | $+0.350 | +1.96 |
| 5 | `0x82cc8472987c...` | Will the Democrats win the Kan vs Will the | $0.010 | $+0.157 | $+0.000 | +0.00 |
| 6 | `0x2aa7cf1991dd...` | Will the Democrats win the Kan vs Will the | $0.010 | $+0.103 | $+0.000 | +0.00 |
| 7 | `0xffde13841676...` | Will the Democrats win the Min vs Will the | $0.010 | $+0.098 | $+0.000 | +0.00 |
| 8 | `0x4e43ba407ed4...` | Will the Democrats win the Wis vs Will the | $0.050 | $+0.092 | $+0.000 | +0.00 |
| 9 | `0xd034d33ba5c4...` | Will the Democrats win the Okl vs Will the | $0.020 | $+0.091 | $+0.000 | +0.00 |
| 10 | `0x64111969ce49...` | Will the Democrats win the New vs Will the | $0.020 | $+0.051 | $+0.000 | +0.00 |
| 11 | `0xb61918837517...` | Will the Democrats win the Nor vs Will the | $0.010 | $+0.032 | $+0.000 | +0.00 |
| 12 | `0x1304dee4404b...` | Will the Democrats win the Ari vs Will the | $0.010 | $+0.024 | $+0.000 | +0.00 |
| 13 | `0x8397b62d3e02...` | Will the Democrats win the Neb vs Will the | $0.010 | $+0.020 | $+0.000 | +0.00 |
| 14 | `0xa80fa85f7e10...` | Will the Democrats win the Geo vs Will the | $0.010 | $+0.016 | $+0.016 | +0.98 |
| 15 | `0xb5ba431e070b...` | Will the Democrats win the Con vs Will the | $0.010 | $+0.016 | $+0.000 | +0.00 |
| 16 | `0xac17bb3e2188...` | Will the Democrats win the New vs Will the | $0.010 | $+0.013 | $+0.000 | +0.00 |
| 17 | `0xfbc9abdccc8a...` | Will the Democrats win the Flo vs Will the | $0.030 | $+0.006 | $+0.000 | +0.00 |
| 18 | `0xe5f54ca9f896...` | Will the Democrats win the New vs Will the | $0.010 | $+0.005 | $+0.000 | +0.00 |

## Compared to prior versions

| Version | Method | Annualized | Issue |
|---|---|---:|---|
| v1 (mid-touch) | mid touch as fill proxy | $15,546 | mid touching != fill |
| v2 size-uncapped | sum of all SELL Yes | $918 | income computed at $100/fill regardless of trade size |
| v3 size-capped, taker fee | size cap added | -$263 naive / +$117 cherry-pick | maker fee wrongly = taker fee; no OOS check |
| **v4 this run** | size cap + maker_fee=zero + IS/OOS | $+83 OOS naive / $+155 OOS top-18 | fee per docs; cherry-pick now measured out-of-sample |

## Caveats (still standing)

- Queue priority: assumes we are first in line at our maker price level.
- Per-leg fills assumed independent within a day.
- Maker fee = 0 ignores `rebateRate` (20-25% of pool taker fees redistributed to makers). Real maker income could be modestly HIGHER. Conservative direction.
- Builder fees are not modeled. The maker-fee-zero assumption is for direct Polymarket platform fees; orders routed through a builder with `builder_maker_fee_bps` could pay a separate builder fee.
- 14 days is a short window; the in-sample / OOS split is *one* random partition, not k-fold. Repeat with different splits to test stability.
- Today's bestAsk/bestBid used to compute maker target — historical spread may have differed.

---
*Snapshot: 2026-05-15T04:00:51.953413+00:00*
