# Maker Simulation v4 — Corrected fee + train/test split (2026-05-15T07:25:12.441018+00:00)

**Method**: v3 plumbing + two fixes:
  (A) maker fee mode = `zero` (v3 used taker_rate, which was wrong; Polymarket docs: "makers never pay fees")
  (B) 10-day in-sample / 4-day OOS split. Top 6 groups picked by IN-SAMPLE daily $; their OOS sum reported separately.

**Window**: 14 days (2026-04-03 -> 2026-04-17)
**Basket size cap**: $100
**Trades fetched**: 21732 raw -> 959 qualifying
**Days with trade activity**: in-sample 10, OOS 4
**takerOnly distribution across our markets**: {True: 12}

## Headline (with maker fee = 0)

| Verdict | Daily $ | Annualized |
|---|---:|---:|
| Naive (all 6 groups), in-sample | $-0.04 | $-15 |
| Naive (all 6 groups), OOS | $-0.09 | $-32 |
| Whole window (no split) | $-0.05 | $-20 |
| **Top 6 by in-sample, in-sample** | $-0.04 | $-15 |
| **Top 6 by in-sample, OOS** ← honest verdict | $-0.09 | $-32 |

If top-N OOS << top-N in-sample, the top-N looks like overfitting.
OOS / in-sample ratio for top-6: 2.16

## Top 6 groups — in-sample picked, OOS measured

| Rank | Group | Q | Best markup | IS daily $ | OOS daily $ | OOS/IS |
|---:|---|---|---:|---:|---:|---:|
| 1 | `0x22725f09e6a3...` | Will the Democratic Party cont vs Will the | $0.005 | $+0.000 | $+0.000 | +0.00 |
| 2 | `0xd4ec843b5228...` | Will the Democratic Party cont vs Will the | $0.005 | $+0.000 | $+0.000 | +0.00 |
| 3 | `0xdc4bd1724b69...` | Will the Republicans win the 2 vs Will the | $0.005 | $+0.000 | $+0.000 | +0.00 |
| 4 | `0x7e28615c2891...` | Will Arsenal win the 2025–26 E vs Will Man | $0.005 | $+0.000 | $+0.000 | +0.00 |
| 5 | `0xd898209c4efc...` | Will Jeff Merkley be the Democ vs Will Jac | $0.005 | $+0.000 | $+0.000 | +0.00 |
| 6 | `0xb37eb81b8e7c...` | Will Chelsea win the 2025-2026 vs Will Man | $0.010 | $-0.040 | $-0.087 | +2.16 |

## Compared to prior versions

| Version | Method | Annualized | Issue |
|---|---|---:|---|
| v1 (mid-touch) | mid touch as fill proxy | $15,546 | mid touching != fill |
| v2 size-uncapped | sum of all SELL Yes | $918 | income computed at $100/fill regardless of trade size |
| v3 size-capped, taker fee | size cap added | -$263 naive / +$117 cherry-pick | maker fee wrongly = taker fee; no OOS check |
| **v4 this run** | size cap + maker_fee=zero + IS/OOS | $-32 OOS naive / $-32 OOS top-6 | fee per docs; cherry-pick now measured out-of-sample |

## Caveats (still standing)

- Queue priority: assumes we are first in line at our maker price level.
- Per-leg fills assumed independent within a day.
- Maker fee = 0 ignores `rebateRate` (20-25% of pool taker fees redistributed to makers). Real maker income could be modestly HIGHER. Conservative direction.
- Builder fees are not modeled. The maker-fee-zero assumption is for direct Polymarket platform fees; orders routed through a builder with `builder_maker_fee_bps` could pay a separate builder fee.
- 14 days is a short window; the in-sample / OOS split is *one* random partition, not k-fold. Repeat with different splits to test stability.
- Today's bestAsk/bestBid used to compute maker target — historical spread may have differed.

---
*Snapshot: 2026-05-15T07:25:12.441018+00:00*
