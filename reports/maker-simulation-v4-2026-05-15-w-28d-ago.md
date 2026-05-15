# Maker Simulation v4 — Corrected fee + train/test split (2026-05-15T04:01:53.391911+00:00)

**Method**: v3 plumbing + two fixes:
  (A) maker fee mode = `zero` (v3 used taker_rate, which was wrong; Polymarket docs: "makers never pay fees")
  (B) 10-day in-sample / 4-day OOS split. Top 18 groups picked by IN-SAMPLE daily $; their OOS sum reported separately.

**Window**: 14 days (2026-04-03 -> 2026-04-17)
**Basket size cap**: $100
**Trades fetched**: 47508 raw -> 2394 qualifying
**Days with trade activity**: in-sample 10, OOS 4
**takerOnly distribution across our markets**: {True: 139}

## Headline (with maker fee = 0)

| Verdict | Daily $ | Annualized |
|---|---:|---:|
| Naive (all 68 groups), in-sample | $+2.21 | $+806 |
| Naive (all 68 groups), OOS | $+0.66 | $+239 |
| Whole window (no split) | $+1.76 | $+644 |
| **Top 18 by in-sample, in-sample** | $+2.41 | $+879 |
| **Top 18 by in-sample, OOS** ← honest verdict | $+1.32 | $+482 |

If top-N OOS << top-N in-sample, the top-N looks like overfitting.
OOS / in-sample ratio for top-18: 0.55

## Top 18 groups — in-sample picked, OOS measured

| Rank | Group | Q | Best markup | IS daily $ | OOS daily $ | OOS/IS |
|---:|---|---|---:|---:|---:|---:|
| 1 | `0x2aa7cf1991dd...` | Will the Democrats win the Kan vs Will the | $0.050 | $+1.299 | $+0.000 | +0.00 |
| 2 | `0xf5f3857c3391...` | Will the Democrats win the Ohi vs Will the | $0.030 | $+0.280 | $+0.000 | +0.00 |
| 3 | `0x1304dee4404b...` | Will the Democrats win the Ari vs Will the | $0.010 | $+0.261 | $+0.147 | +0.56 |
| 4 | `0x8941a4153cb2...` | Will the Democrats win the Ver vs Will the | $0.050 | $+0.118 | $+0.575 | +4.88 |
| 5 | `0xd4118b02b567...` | Will the Democrats win the Pen vs Will the | $0.010 | $+0.107 | $+0.134 | +1.24 |
| 6 | `0xfbc9abdccc8a...` | Will the Democrats win the Flo vs Will the | $0.030 | $+0.096 | $+0.154 | +1.61 |
| 7 | `0x4e43ba407ed4...` | Will the Democrats win the Wis vs Will the | $0.050 | $+0.063 | $+0.026 | +0.41 |
| 8 | `0x96596827696d...` | Will the Democrats win the Lou vs Will the | $0.020 | $+0.057 | $+0.000 | +0.00 |
| 9 | `0xa80fa85f7e10...` | Will the Democrats win the Geo vs Will the | $0.010 | $+0.034 | $+0.000 | +0.00 |
| 10 | `0x2a010ed53626...` | Will the Democrats win the Flo vs Will the | $0.030 | $+0.013 | $+0.060 | +4.68 |
| 11 | `0x91b62611de4a...` | Will the Democrats win the Mas vs Will the | $0.010 | $+0.011 | $+0.000 | +0.00 |
| 12 | `0xd251f99f27d7...` | Will the Democrats win the New vs Will the | $0.020 | $+0.011 | $+0.000 | +0.00 |
| 13 | `0xdbf0dffb3b5c...` | Will the Democrats win the New vs Will the | $0.005 | $+0.011 | $+0.000 | +0.00 |
| 14 | `0xb61918837517...` | Will the Democrats win the Nor vs Will the | $0.010 | $+0.011 | $+0.000 | +0.00 |
| 15 | `0x287fa3a945e6...` | Will the Democrats win the Vir vs Will the | $0.010 | $+0.011 | $+0.000 | +0.00 |
| 16 | `0xee4444c07438...` | Will the Democrats win the Mis vs Will the | $0.020 | $+0.010 | $+0.000 | +0.00 |
| 17 | `0x50a317c8d911...` | Will the Democrats win the Okl vs Will the | $0.010 | $+0.009 | $+0.000 | +0.00 |
| 18 | `0x64111969ce49...` | Will the Democrats win the New vs Will the | $0.020 | $+0.007 | $+0.224 | +33.33 |

## Compared to prior versions

| Version | Method | Annualized | Issue |
|---|---|---:|---|
| v1 (mid-touch) | mid touch as fill proxy | $15,546 | mid touching != fill |
| v2 size-uncapped | sum of all SELL Yes | $918 | income computed at $100/fill regardless of trade size |
| v3 size-capped, taker fee | size cap added | -$263 naive / +$117 cherry-pick | maker fee wrongly = taker fee; no OOS check |
| **v4 this run** | size cap + maker_fee=zero + IS/OOS | $+239 OOS naive / $+482 OOS top-18 | fee per docs; cherry-pick now measured out-of-sample |

## Caveats (still standing)

- Queue priority: assumes we are first in line at our maker price level.
- Per-leg fills assumed independent within a day.
- Maker fee = 0 ignores `rebateRate` (20-25% of pool taker fees redistributed to makers). Real maker income could be modestly HIGHER. Conservative direction.
- Builder fees are not modeled. The maker-fee-zero assumption is for direct Polymarket platform fees; orders routed through a builder with `builder_maker_fee_bps` could pay a separate builder fee.
- 14 days is a short window; the in-sample / OOS split is *one* random partition, not k-fold. Repeat with different splits to test stability.
- Today's bestAsk/bestBid used to compute maker target — historical spread may have differed.

---
*Snapshot: 2026-05-15T04:01:53.391911+00:00*
