# Maker Simulation v4 — Corrected fee + train/test split (2026-05-15T04:03:10.554424+00:00)

**Method**: v3 plumbing + two fixes:
  (A) maker fee mode = `zero` (v3 used taker_rate, which was wrong; Polymarket docs: "makers never pay fees")
  (B) 10-day in-sample / 4-day OOS split. Top 18 groups picked by IN-SAMPLE daily $; their OOS sum reported separately.

**Window**: 14 days (2026-03-20 -> 2026-04-03)
**Basket size cap**: $100
**Trades fetched**: 48025 raw -> 1331 qualifying
**Days with trade activity**: in-sample 10, OOS 4
**takerOnly distribution across our markets**: {True: 139}

## Headline (with maker fee = 0)

| Verdict | Daily $ | Annualized |
|---|---:|---:|
| Naive (all 68 groups), in-sample | $+0.36 | $+132 |
| Naive (all 68 groups), OOS | $-3.06 | $-1,117 |
| Whole window (no split) | $-0.62 | $-225 |
| **Top 18 by in-sample, in-sample** | $+0.36 | $+132 |
| **Top 18 by in-sample, OOS** ← honest verdict | $+0.40 | $+147 |

If top-N OOS << top-N in-sample, the top-N looks like overfitting.
OOS / in-sample ratio for top-18: 1.12

## Top 18 groups — in-sample picked, OOS measured

| Rank | Group | Q | Best markup | IS daily $ | OOS daily $ | OOS/IS |
|---:|---|---|---:|---:|---:|---:|
| 1 | `0xf5f3857c3391...` | Will the Democrats win the Ohi vs Will the | $0.030 | $+0.126 | $+0.168 | +1.34 |
| 2 | `0x82cc8472987c...` | Will the Democrats win the Kan vs Will the | $0.020 | $+0.036 | $+0.000 | +0.00 |
| 3 | `0x4e43ba407ed4...` | Will the Democrats win the Wis vs Will the | $0.050 | $+0.033 | $+0.133 | +4.08 |
| 4 | `0x64111969ce49...` | Will the Democrats win the New vs Will the | $0.020 | $+0.028 | $+0.000 | +0.00 |
| 5 | `0x2aa7cf1991dd...` | Will the Democrats win the Kan vs Will the | $0.030 | $+0.028 | $+0.017 | +0.62 |
| 6 | `0xcd24472b2d86...` | Will the Democrats win the Col vs Will the | $0.020 | $+0.026 | $+0.000 | +0.00 |
| 7 | `0x5a57c20b2083...` | Will the Democrats win the Ida vs Will the | $0.020 | $+0.025 | $+0.062 | +2.43 |
| 8 | `0xc28de9467003...` | Will the Democrats win the Tex vs Will the | $0.020 | $+0.018 | $+0.000 | +0.00 |
| 9 | `0xd251f99f27d7...` | Will the Democrats win the New vs Will the | $0.030 | $+0.013 | $+0.021 | +1.64 |
| 10 | `0x2a010ed53626...` | Will the Democrats win the Flo vs Will the | $0.030 | $+0.009 | $+0.001 | +0.11 |
| 11 | `0xd4118b02b567...` | Will the Democrats win the Pen vs Will the | $0.020 | $+0.008 | $+0.000 | +0.00 |
| 12 | `0xfbc9abdccc8a...` | Will the Democrats win the Flo vs Will the | $0.030 | $+0.006 | $+0.000 | +0.00 |
| 13 | `0x67d0d210eee8...` | Will the Democrats win the Sou vs Will the | $0.005 | $+0.004 | $+0.000 | +0.00 |
| 14 | `0xac17bb3e2188...` | Will the Democrats win the New vs Will the | $0.005 | $+0.002 | $+0.002 | +1.07 |
| 15 | `0xa80fa85f7e10...` | Will the Democrats win the Geo vs Will the | $0.010 | $+0.000 | $+0.000 | +0.00 |
| 16 | `0x22725f09e6a3...` | Will the Democratic Party cont vs Will the | $0.005 | $+0.000 | $+0.000 | +0.00 |
| 17 | `0xd4ec843b5228...` | Will the Democratic Party cont vs Will the | $0.005 | $+0.000 | $+0.000 | +0.00 |
| 18 | `0xdc4bd1724b69...` | Will the Republicans win the 2 vs Will the | $0.005 | $+0.000 | $+0.000 | +0.00 |

## Compared to prior versions

| Version | Method | Annualized | Issue |
|---|---|---:|---|
| v1 (mid-touch) | mid touch as fill proxy | $15,546 | mid touching != fill |
| v2 size-uncapped | sum of all SELL Yes | $918 | income computed at $100/fill regardless of trade size |
| v3 size-capped, taker fee | size cap added | -$263 naive / +$117 cherry-pick | maker fee wrongly = taker fee; no OOS check |
| **v4 this run** | size cap + maker_fee=zero + IS/OOS | $-1,117 OOS naive / $+147 OOS top-18 | fee per docs; cherry-pick now measured out-of-sample |

## Caveats (still standing)

- Queue priority: assumes we are first in line at our maker price level.
- Per-leg fills assumed independent within a day.
- Maker fee = 0 ignores `rebateRate` (20-25% of pool taker fees redistributed to makers). Real maker income could be modestly HIGHER. Conservative direction.
- Builder fees are not modeled. The maker-fee-zero assumption is for direct Polymarket platform fees; orders routed through a builder with `builder_maker_fee_bps` could pay a separate builder fee.
- 14 days is a short window; the in-sample / OOS split is *one* random partition, not k-fold. Repeat with different splits to test stability.
- Today's bestAsk/bestBid used to compute maker target — historical spread may have differed.

---
*Snapshot: 2026-05-15T04:03:10.554424+00:00*
