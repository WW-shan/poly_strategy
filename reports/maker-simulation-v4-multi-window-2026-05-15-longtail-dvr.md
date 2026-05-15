# Maker Simulation v4 — Multi-Window Stability (2026-05-15T07:26:38.997558+00:00)

**Method**: ran v4 (maker_fee=zero, 10 IS / 4 OOS) on 4 non-overlapping 14-day windows. Total span: 2026-03-20 -> 2026-05-15 (56 days).

**Why this matters**: a single 14-day window's verdict can be window-luck. If the thesis is real, all 4 windows should give roughly consistent signs and magnitudes. If they bounce sign or order of magnitude, the single-window verdict was a coincidence.

## Per-window numbers

| Window | IS days | OOS days | Naive IS / yr | Naive OOS / yr | Cherry IS / yr | Cherry OOS / yr |
|---|---:|---:|---:|---:|---:|---:|
| 2026-03-20 → 2026-04-03 | 10 | 4 | $+132 | $-1,117 | $+132 | $+147 |
| 2026-04-03 → 2026-04-17 | 10 | 4 | $+806 | $+239 | $+879 | $+482 |
| 2026-04-17 → 2026-05-01 | 10 | 4 | $+228 | $+83 | $+631 | $+155 |
| 2026-05-01 → 2026-05-15 | 10 | 4 | $+164 | $+65 | $+205 | $+218 |

## Cross-window stability

| Metric | mean | median | min | max | SD | SD/mean |
|---|---:|---:|---:|---:|---:|---:|
| Naive IS / yr | $+333 | $+196 | $+132 | $+806 | $318 | 0.96 |
| Naive OOS / yr | $-183 | $+74 | $-1,117 | $+239 | $628 | 3.44 |
| Cherry IS / yr | $+462 | $+418 | $+132 | $+879 | $355 | 0.77 |
| Cherry OOS / yr | $+251 | $+187 | $+147 | $+482 | $157 | 0.63 |

**Read this**: if SD/mean > 1.0, your point estimate is mostly noise. If sign of OOS is consistent across windows but magnitude varies 2-3x, you have a real but noisy signal.

## Persistent winners (positive OOS in ≥3 of 4 windows)

Found 0 groups (of 64 present in all windows). Sum of their mean OOS = **$+0/yr**.

| Rank | Group | Q | +OOS windows | Mean OOS / yr | Median OOS / yr | Values per window |
|---:|---|---|:-:|---:|---:|---|

## Interpretation

- The single-window verdict from any one run alone is statistically weak.
- The honest verdict is the mean OOS across all windows.
- The set of **persistent winners** (+OOS in ≥3/4 windows) gives the most defensible cherry-pick.
- If `naive_oos` flips sign across windows, the thesis applies only to a subset of groups, not to a naive deploy.

---
*Snapshot: 2026-05-15T07:26:38.997558+00:00*