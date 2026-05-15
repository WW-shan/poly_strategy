# Maker Simulation v4 — Corrected fee + train/test split (2026-05-15T07:19:16.547712+00:00)

**Method**: v3 plumbing + two fixes:
  (A) maker fee mode = `zero` (v3 used taker_rate, which was wrong; Polymarket docs: "makers never pay fees")
  (B) 10-day in-sample / 4-day OOS split. Top 18 groups picked by IN-SAMPLE daily $; their OOS sum reported separately.

**Window**: 14 days (2026-05-01 -> 2026-05-15)
**Basket size cap**: $100
**Trades fetched**: 1022715 raw -> 104389 qualifying
**Days with trade activity**: in-sample 11, OOS 4
> Note: this report was generated before the simulator default window end was normalized to UTC midnight, so it includes a partial UTC boundary day. Future no-`--end-date` runs use the intended clean 10 / 4 split.
**takerOnly distribution across our markets**: {True: 738}
**Maker-quote skips**: 240/250 group-markup pairs (96.0%) skipped as `spread_too_narrow_for_maker`

## Headline (with maker fee = 0)

| Verdict | Daily $ | Annualized |
|---|---:|---:|
| Naive (all 50 groups), in-sample | $+0.00 | $+0 |
| Naive (all 50 groups), OOS | $+0.00 | $+0 |
| Whole window (no split) | $+0.00 | $+0 |
| **Top 18 by in-sample, in-sample** | $+0.00 | $+0 |
| **Top 18 by in-sample, OOS** ← honest verdict | $+0.00 | $+0 |

If top-N OOS << top-N in-sample, the top-N looks like overfitting.
OOS / in-sample ratio for top-18: 0.00

## Top 18 groups — in-sample picked, OOS measured

| Rank | Group | Q | Best markup | IS daily $ | OOS daily $ | OOS/IS |
|---:|---|---|---:|---:|---:|---:|
| 1 | `0x7faa974ff857...` | Will the Carolina Hurricanes w vs Will the | $0.005 | $+0.000 | $+0.000 | +0.00 |
| 2 | `0x11e9a09023ac...` | Will the Oklahoma City Thunder vs Will the | $0.005 | $+0.000 | $+0.000 | +0.00 |
| 3 | `0xb5c32a9acd39...` | Will Spain win the 2026 FIFA W vs Will Eng | $0.005 | $+0.000 | $+0.000 | +0.00 |
| 4 | `0x2c3d7e0eee6f...` | Will Gavin Newsom win the 2028 vs Will Ale | $0.005 | $+0.000 | $+0.000 | +0.00 |
| 5 | `0xb9aa4595bbe8...` | Will JD Vance win the 2028 US  vs Will Gav | $0.005 | $+0.000 | $+0.000 | +0.00 |
| 6 | `0xc7d902c4f18f...` | Will Donald Trump win the 2028 vs Will J.D | $0.005 | $+0.000 | $+0.000 | +0.00 |
| 7 | `0x0aa99409c83e...` | Will Ken Paxton win the 2026 T vs Will Joh | $0.005 | $+0.000 | $+0.000 | +0.00 |
| 8 | `0x7b95a46fc059...` | 2026 Balance of Power: D Senat vs 2026 Bal | $0.005 | $+0.000 | $+0.000 | +0.00 |
| 9 | `0x51a3b9f29275...` | Will Nikola Jokic win the 2025 vs Will Sha | $0.005 | $+0.000 | $+0.000 | +0.00 |
| 10 | `0x8a612f242b38...` | Will the Oklahoma City Thunder vs Will the | $0.005 | $+0.000 | $+0.000 | +0.00 |
| 11 | `0xc8f80ae8e6e9...` | Will PSG win the 2025–26 Champ vs Will Ars | $0.005 | $+0.000 | $+0.000 | +0.00 |
| 12 | `0x9250593bd8a2...` | Will Vicky Dávila win the 1st  vs Will Lui | $0.005 | $+0.000 | $+0.000 | +0.00 |
| 13 | `0x3e140cadcdda...` | Will Vicky Dávila win the 2026 vs Will Lui | $0.005 | $+0.000 | $+0.000 | +0.00 |
| 14 | `0xf5df3e53ea40...` | Will Mallory McMorrow win the  vs Will Hal | $0.005 | $+0.000 | $+0.000 | +0.00 |
| 15 | `0x966a3221e05d...` | Will Tarcisio de Freitas win t vs Will Lui | $0.005 | $+0.000 | $+0.000 | +0.00 |
| 16 | `0xda59e733de4f...` | Will Kylian Mbappe be the 2025 vs Will Ous | $0.005 | $+0.000 | $+0.000 | +0.00 |
| 17 | `0xcd778cf07b7b...` | Will Anthropic’s market cap be vs Will Ant | $0.005 | $+0.000 | $+0.000 | +0.00 |
| 18 | `0x178e5d521fe4...` | Will Kylian Mbappé win the 202 vs Will Erl | $0.005 | $+0.000 | $+0.000 | +0.00 |

## Compared to prior versions

| Version | Method | Annualized | Issue |
|---|---|---:|---|
| v1 (mid-touch) | mid touch as fill proxy | $15,546 | mid touching != fill |
| v2 size-uncapped | sum of all SELL Yes | $918 | income computed at $100/fill regardless of trade size |
| v3 size-capped, taker fee | size cap added | -$263 naive / +$117 cherry-pick | maker fee wrongly = taker fee; no OOS check |
| **v4 this run** | size cap + maker_fee=zero + IS/OOS | $+0 OOS naive / $+0 OOS top-18 | fee per docs; cherry-pick now measured out-of-sample |

## Caveats (still standing)

- Queue priority: assumes we are first in line at our maker price level.
- Per-leg fills assumed independent within a day.
- Maker fee = 0 ignores `rebateRate` (20-25% of pool taker fees redistributed to makers). Real maker income could be modestly HIGHER. Conservative direction.
- Builder fees are not modeled. The maker-fee-zero assumption is for direct Polymarket platform fees; orders routed through a builder with `builder_maker_fee_bps` could pay a separate builder fee.
- 14 days is a short window; the in-sample / OOS split is *one* random partition, not k-fold. Repeat with different splits to test stability.
- Today's bestAsk/bestBid used to compute maker target — historical spread may have differed.

---
*Snapshot: 2026-05-15T07:19:16.547712+00:00*
