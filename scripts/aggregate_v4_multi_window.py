#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Aggregate v4 multi-window results.

Reads the JSON output from N separate v4 runs (each on a different 14-day
window) and produces a stability report. Answers: is the +$190/yr verdict
consistent across windows, or does it bounce around so much that any single
verdict is meaningless?

Inputs:
  - Glob pattern matching v4 JSON files (defaults to today's experiments dir).

Outputs:
  - reports/maker-simulation-v4-multi-window-<date>.md
  - data/experiments/<date>/maker-simulation-v4-multi-window.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--results-glob",
        default=None,
        help="Glob for v4 JSON files. Defaults to data/experiments/<today>/maker-simulation-v4-results-*.json",
    )
    ap.add_argument(
        "--top-n",
        type=int,
        default=18,
        help="Cherry-pick depth used in v4 runs (for reference).",
    )
    ap.add_argument(
        "--report-tag",
        type=str,
        default=None,
        help="Suffix for output report/json filenames so multiple multi-window runs don't overwrite each other.",
    )
    args = ap.parse_args()

    now = datetime.now(tz=timezone.utc)
    date_tag = now.strftime("%Y-%m-%d")
    if args.results_glob is None:
        default_glob = REPO_ROOT / "data" / "experiments" / date_tag
        json_files = sorted(default_glob.glob("maker-simulation-v4-results-*.json"))
    else:
        json_files = sorted(Path().glob(args.results_glob))

    if not json_files:
        print(f"ERROR: no v4 JSON files found", file=sys.stderr)
        return 2
    print(f"Aggregating {len(json_files)} v4 runs:")
    for p in json_files:
        print(f"  {p.name}")

    runs: list[dict] = []
    for p in json_files:
        with open(p, "r", encoding="utf-8") as f:
            runs.append(json.load(f))

    # Sort by window_end_iso ascending
    runs.sort(key=lambda r: r.get("window_end_iso", ""))

    # Per-window summary
    per_window = []
    for r in runs:
        per_window.append({
            "tag": r.get("window_tag", "?"),
            "window_start": r.get("window_start_iso", "?")[:10],
            "window_end": r.get("window_end_iso", "?")[:10],
            "in_sample_days": r.get("in_sample_days"),
            "oos_days": r.get("window_days") - r.get("in_sample_days"),
            "naive_is_daily": r.get("naive_in_sample_daily", 0.0),
            "naive_oos_daily": r.get("naive_oos_daily", 0.0),
            "cherry_is_daily": r.get("cherry_in_sample_daily", 0.0),
            "cherry_oos_daily": r.get("cherry_oos_daily", 0.0),
            "naive_is_ann": r.get("naive_in_sample_daily", 0.0) * 365,
            "naive_oos_ann": r.get("naive_oos_daily", 0.0) * 365,
            "cherry_is_ann": r.get("cherry_in_sample_daily", 0.0) * 365,
            "cherry_oos_ann": r.get("cherry_oos_daily", 0.0) * 365,
        })

    # Stability stats across windows
    def stats(values: list[float]) -> dict:
        if not values:
            return {"n": 0, "mean": 0.0, "median": 0.0, "min": 0.0, "max": 0.0, "sd": 0.0}
        return {
            "n": len(values),
            "mean": statistics.mean(values),
            "median": statistics.median(values),
            "min": min(values),
            "max": max(values),
            "sd": statistics.stdev(values) if len(values) > 1 else 0.0,
        }

    stab_naive_oos = stats([w["naive_oos_ann"] for w in per_window])
    stab_cherry_oos = stats([w["cherry_oos_ann"] for w in per_window])
    stab_naive_is = stats([w["naive_is_ann"] for w in per_window])
    stab_cherry_is = stats([w["cherry_is_ann"] for w in per_window])

    # Per-group cross-window analysis (the persistence test).
    # For each group, count how many windows it had positive OOS daily $.
    group_oos_signs: dict[str, list[float]] = defaultdict(list)
    group_questions: dict[str, str] = {}
    for r in runs:
        for s in r.get("summaries", []):
            gid = s["gid"]
            group_oos_signs[gid].append(s["oos_daily"] * 365)
            group_questions[gid] = s.get("question_short", "?")

    # Restrict to groups that appeared in ALL windows
    all_window_groups = [
        gid for gid, vals in group_oos_signs.items()
        if len(vals) == len(runs)
    ]
    print(f"\nGroups present in ALL {len(runs)} windows: {len(all_window_groups)} (of total {len(group_oos_signs)})")

    persistent_winners = []
    for gid in all_window_groups:
        vals = group_oos_signs[gid]
        n_positive = sum(1 for v in vals if v > 0)
        persistent_winners.append({
            "gid": gid,
            "question": group_questions[gid],
            "n_positive_windows": n_positive,
            "n_total_windows": len(runs),
            "ann_values": vals,
            "mean_ann": statistics.mean(vals),
            "median_ann": statistics.median(vals),
        })

    persistent_winners.sort(key=lambda x: (x["n_positive_windows"], x["mean_ann"]), reverse=True)

    # Define "persistent" = positive in ≥3/4 windows AND mean across windows > 0
    persistent_strict = [w for w in persistent_winners if w["n_positive_windows"] >= 3 and w["mean_ann"] > 0]

    persistent_sum_mean = sum(w["mean_ann"] for w in persistent_strict)

    # ---- Report ----
    iso = now.isoformat()
    lines = [
        f"# Maker Simulation v4 — Multi-Window Stability ({iso})",
        "",
        f"**Method**: ran v4 (maker_fee=zero, 10 IS / 4 OOS) on {len(runs)} non-overlapping "
        f"14-day windows. Total span: {per_window[0]['window_start']} -> {per_window[-1]['window_end']} "
        f"({(datetime.strptime(per_window[-1]['window_end'], '%Y-%m-%d') - datetime.strptime(per_window[0]['window_start'], '%Y-%m-%d')).days} days).",
        "",
        "**Why this matters**: a single 14-day window's verdict can be window-luck. "
        "If the thesis is real, all 4 windows should give roughly consistent signs and magnitudes. "
        "If they bounce sign or order of magnitude, the single-window verdict was a coincidence.",
        "",
        "## Per-window numbers",
        "",
        "| Window | IS days | OOS days | Naive IS / yr | Naive OOS / yr | Cherry IS / yr | Cherry OOS / yr |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for w in per_window:
        lines.append(
            f"| {w['window_start']} → {w['window_end']} | {w['in_sample_days']} | {w['oos_days']} "
            f"| ${w['naive_is_ann']:+,.0f} | ${w['naive_oos_ann']:+,.0f} "
            f"| ${w['cherry_is_ann']:+,.0f} | ${w['cherry_oos_ann']:+,.0f} |"
        )

    lines += [
        "",
        "## Cross-window stability",
        "",
        "| Metric | mean | median | min | max | SD | SD/mean |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for label, s in [
        ("Naive IS / yr", stab_naive_is),
        ("Naive OOS / yr", stab_naive_oos),
        ("Cherry IS / yr", stab_cherry_is),
        ("Cherry OOS / yr", stab_cherry_oos),
    ]:
        sd_over_mean = (s["sd"] / abs(s["mean"])) if s["mean"] else float("inf")
        sd_over_mean_str = f"{sd_over_mean:.2f}" if sd_over_mean != float("inf") else "inf"
        lines.append(
            f"| {label} | ${s['mean']:+,.0f} | ${s['median']:+,.0f} "
            f"| ${s['min']:+,.0f} | ${s['max']:+,.0f} | ${s['sd']:,.0f} | {sd_over_mean_str} |"
        )

    lines += [
        "",
        "**Read this**: if SD/mean > 1.0, your point estimate is mostly noise. "
        "If sign of OOS is consistent across windows but magnitude varies 2-3x, you have a real but noisy signal.",
        "",
        "## Persistent winners (positive OOS in ≥3 of 4 windows)",
        "",
        f"Found {len(persistent_strict)} groups (of {len(all_window_groups)} present in all windows). "
        f"Sum of their mean OOS = **${persistent_sum_mean:+,.0f}/yr**.",
        "",
        "| Rank | Group | Q | +OOS windows | Mean OOS / yr | Median OOS / yr | Values per window |",
        "|---:|---|---|:-:|---:|---:|---|",
    ]
    for i, w in enumerate(persistent_strict[:30], 1):
        vals_str = ", ".join(f"${v:+,.0f}" for v in w["ann_values"])
        lines.append(
            f"| {i} | `{w['gid'][:14]}...` | {w['question'][:40]} | "
            f"{w['n_positive_windows']}/{w['n_total_windows']} "
            f"| ${w['mean_ann']:+,.0f} | ${w['median_ann']:+,.0f} | {vals_str} |"
        )

    lines += [
        "",
        "## Interpretation",
        "",
        "- The single-window verdict from any one run alone is statistically weak.",
        "- The honest verdict is the mean OOS across all windows.",
        "- The set of **persistent winners** (+OOS in ≥3/4 windows) gives the most defensible cherry-pick.",
        "- If `naive_oos` flips sign across windows, the thesis applies only to a subset of groups, not to a naive deploy.",
        "",
        f"---\n*Snapshot: {iso}*",
    ]

    tag_suffix = f"-{args.report_tag}" if args.report_tag else ""
    report_path = REPO_ROOT / "reports" / f"maker-simulation-v4-multi-window-{date_tag}{tag_suffix}.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")

    data_dir = REPO_ROOT / "data" / "experiments" / date_tag
    data_dir.mkdir(parents=True, exist_ok=True)
    out_json = data_dir / f"maker-simulation-v4-multi-window{tag_suffix}.json"
    with out_json.open("w", encoding="utf-8") as f:
        json.dump({
            "snapshot_ts": iso,
            "n_windows": len(runs),
            "per_window": per_window,
            "stability": {
                "naive_is_ann": stab_naive_is,
                "naive_oos_ann": stab_naive_oos,
                "cherry_is_ann": stab_cherry_is,
                "cherry_oos_ann": stab_cherry_oos,
            },
            "n_groups_in_all_windows": len(all_window_groups),
            "n_persistent_winners": len(persistent_strict),
            "persistent_sum_mean_ann": persistent_sum_mean,
            "persistent_winners": persistent_strict,
        }, f, indent=2, ensure_ascii=False)

    print(f"\nreport: {report_path}")
    print(f"json:   {out_json}")
    print()
    print(f"=== Multi-window stability summary ({len(runs)} windows) ===")
    print(f"Naive OOS / yr:   mean ${stab_naive_oos['mean']:+,.0f}, range [${stab_naive_oos['min']:+,.0f}, ${stab_naive_oos['max']:+,.0f}]")
    print(f"Cherry OOS / yr:  mean ${stab_cherry_oos['mean']:+,.0f}, range [${stab_cherry_oos['min']:+,.0f}, ${stab_cherry_oos['max']:+,.0f}]")
    print(f"Persistent winners (+OOS in >=3/4 windows): {len(persistent_strict)} groups")
    print(f"Sum of their mean OOS: ${persistent_sum_mean:+,.0f}/yr")
    return 0


if __name__ == "__main__":
    sys.exit(main())
