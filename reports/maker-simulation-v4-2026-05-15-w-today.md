# Maker Simulation v4 — Corrected fee + train/test split (2026-05-15T04:04:02.459101+00:00)

**Method**: v3 plumbing + two fixes:
  (A) maker fee mode = `zero` (v3 used taker_rate, which was wrong; Polymarket docs: "makers never pay fees")
  (B) 10-day in-sample / 4-day OOS split. Top 18 groups picked by IN-SAMPLE daily $; their OOS sum reported separately.

**Window**: 14 days (2026-05-01 -> 2026-05-15)
**Basket size cap**: $100
**Trades fetched**: 38341 raw -> 1355 qualifying
**Days with trade activity**: in-sample 11, OOS 4
> Note: this report was generated before the simulator default window end was normalized to UTC midnight, so it includes a partial UTC boundary day. Future no-`--end-date` runs use the intended clean 10 / 4 split.
**takerOnly distribution across our markets**: {True: 140}

## Headline (with maker fee = 0)

| Verdict | Daily $ | Annualized |
|---|---:|---:|
| Naive (all 69 groups), in-sample | $+0.45 | $+164 |
| Naive (all 69 groups), OOS | $+0.18 | $+65 |
| Whole window (no split) | $+0.38 | $+138 |
| **Top 18 by in-sample, in-sample** | $+0.56 | $+205 |
| **Top 18 by in-sample, OOS** ← honest verdict | $+0.60 | $+218 |

If top-N OOS << top-N in-sample, the top-N looks like overfitting.
OOS / in-sample ratio for top-18: 1.06

## Top 18 groups — in-sample picked, OOS measured

| Rank | Group | Q | Best markup | IS daily $ | OOS daily $ | OOS/IS |
|---:|---|---|---:|---:|---:|---:|
| 1 | `0xd4ec843b5228...` | Will the Democratic Party cont vs Will the | $0.010 | $+0.250 | $+0.487 | +1.95 |
| 2 | `0xb61918837517...` | Will the Democrats win the Nor vs Will the | $0.010 | $+0.073 | $+0.000 | +0.00 |
| 3 | `0x2aa7cf1991dd...` | Will the Democrats win the Kan vs Will the | $0.030 | $+0.064 | $+0.000 | +0.00 |
| 4 | `0x7bd878bdc3cd...` | Will the Democrats win the Nev vs Will the | $0.050 | $+0.035 | $+0.000 | +0.00 |
| 5 | `0x2ecd963d91df...` | Will the Democrats win the Iow vs Will the | $0.050 | $+0.030 | $+0.000 | +0.00 |
| 6 | `0x7146f4aff656...` | Will the Democrats win the Ill vs Will the | $0.050 | $+0.023 | $+0.000 | +0.00 |
| 7 | `0x82cc8472987c...` | Will the Democrats win the Kan vs Will the | $0.010 | $+0.014 | $+0.000 | +0.00 |
| 8 | `0x209eca0d8c37...` | Will the Democrats win the Wyo vs Will the | $0.050 | $+0.014 | $+0.000 | +0.00 |
| 9 | `0x2a010ed53626...` | Will the Democrats win the Flo vs Will the | $0.050 | $+0.013 | $+0.000 | +0.00 |
| 10 | `0xc28de9467003...` | Will the Democrats win the Tex vs Will the | $0.020 | $+0.010 | $+0.008 | +0.86 |
| 11 | `0x4e43ba407ed4...` | Will the Democrats win the Wis vs Will the | $0.050 | $+0.009 | $+0.000 | +0.00 |
| 12 | `0x8941a4153cb2...` | Will the Democrats win the Ver vs Will the | $0.050 | $+0.009 | $+0.000 | +0.00 |
| 13 | `0x1304dee4404b...` | Will the Democrats win the Ari vs Will the | $0.010 | $+0.008 | $+0.000 | +0.00 |
| 14 | `0x195e8f642b07...` | Will the Democrats win the Tex vs Will the | $0.050 | $+0.005 | $+0.103 | +21.53 |
| 15 | `0x284bd4583b40...` | Will the Democrats win the Ore vs Will the | $0.010 | $+0.004 | $+0.000 | +0.00 |
| 16 | `0xac17bb3e2188...` | Will the Democrats win the New vs Will the | $0.030 | $+0.003 | $+0.000 | +0.00 |
| 17 | `0xdc4bd1724b69...` | Will the Republicans win the 2 vs Will the | $0.005 | $+0.000 | $+0.000 | +0.00 |
| 18 | `0x07311e10dac6...` | Will the Democrats win the Ala vs Will the | $0.005 | $+0.000 | $+0.000 | +0.00 |

## Compared to prior versions

| Version | Method | Annualized | Issue |
|---|---|---:|---|
| v1 (mid-touch) | mid touch as fill proxy | $15,546 | mid touching != fill |
| v2 size-uncapped | sum of all SELL Yes | $918 | income computed at $100/fill regardless of trade size |
| v3 size-capped, taker fee | size cap added | -$263 naive / +$117 cherry-pick | maker fee wrongly = taker fee; no OOS check |
| **v4 this run** | size cap + maker_fee=zero + IS/OOS | $+65 OOS naive / $+218 OOS top-18 | fee per docs; cherry-pick now measured out-of-sample |

## Caveats (still standing)

- Queue priority: assumes we are first in line at our maker price level.
- Per-leg fills assumed independent within a day.
- Maker fee = 0 ignores `rebateRate` (20-25% of pool taker fees redistributed to makers). Real maker income could be modestly HIGHER. Conservative direction.
- Builder fees are not modeled. The maker-fee-zero assumption is for direct Polymarket platform fees; orders routed through a builder with `builder_maker_fee_bps` could pay a separate builder fee.
- 14 days is a short window; the in-sample / OOS split is *one* random partition, not k-fold. Repeat with different splits to test stability.
- Today's bestAsk/bestBid used to compute maker target — historical spread may have differed.

---
*Snapshot: 2026-05-15T04:04:02.459101+00:00*
