#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Maker-strategy basket simulator v4 — corrected fee + train/test split.

v3 (simulate_maker_basket_v2.py at d222906) had two methodological gaps WW's
review did not catch:

  (A) Maker fee was set equal to taker fee (fee_rate * price * (1-price))
      every leg. Polymarket Gamma `feeSchedule.takerOnly` is True for every
      market we sampled (100/100 on a random survey, 6/6 on our actual D/R
      cohort). Per docs.polymarket.com/trading/fees:
        "Makers are never charged fees."
        "Only takers pay fees."
      So the correct maker fee in this simulation is 0.

  (B) The 14-day window was used 100% in-sample. The "cherry-pick" verdict
      (top 18 groups @ +$117/yr) had no out-of-sample check, so it cannot
      distinguish a real persistent edge from a hindsight-mined artifact.

v4 fixes both:

  - `--maker-fee-mode` flag with choices: zero (default, per docs), taker_rate
    (the buggy v3 assumption, kept for ablation comparison), custom (provide
    `--maker-fee-rate`).
  - Splits the window into in-sample (first `--in-sample-days`) and OOS
    (remainder). Reports both halves separately and computes:
      * naive (all-72-groups) total annualized in-sample and OOS
      * top-N-by-in-sample groups' OOS performance (the honest cherry-pick)

The simulator otherwise reuses v3's plumbing (Gamma metadata, trade-tape
filter, target clamping, size-capped fills).

Inputs (built dynamically):
  - Today's Gamma /markets for member condition_ids + feeSchedule
  - 14 days of /trades per leg

Output:
  reports/maker-simulation-v4-<date>.md
  data/experiments/<date>/maker-simulation-v4-results.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parent.parent
GAMMA_MARKETS_URL = "https://gamma-api.polymarket.com/markets"
TRADES_URL = "https://data-api.polymarket.com/trades"


def fetch_market_by_id(market_id: str, timeout: float = 15.0) -> dict | None:
    """Fetch a single Gamma market by its numeric `id`.

    We use this instead of paginating /markets because (a) Gamma caps each
    page at 100 entries regardless of the `limit` param, and (b) iterating
    pages doesn't guarantee our specific D/R cohort appears (it depends on
    today's ordering). Direct fetch is deterministic and reproducible.
    """
    url = f"{GAMMA_MARKETS_URL}/{market_id}"
    req = Request(url, headers={"User-Agent": "poly_strategy-sim4/1.0"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def fetch_trades_paginated(
    condition_id: str,
    cutoff_ts: int,
    page_size: int = 500,
    max_pages: int = 200,
    timeout: float = 30.0,
) -> list[dict]:
    all_trades: list[dict] = []
    offset = 0
    for _ in range(max_pages):
        params = urlencode({"market": condition_id, "limit": str(page_size), "offset": str(offset)})
        url = f"{TRADES_URL}?{params}"
        req = Request(url, headers={"User-Agent": "poly_strategy-sim4/1.0"})
        try:
            with urlopen(req, timeout=timeout) as resp:
                page = json.loads(resp.read().decode("utf-8"))
        except Exception:
            break
        if not page:
            break
        all_trades.extend(page)
        oldest_ts = min(t["timestamp"] for t in page)
        if oldest_ts < cutoff_ts:
            break
        offset += page_size
    return all_trades


def day_of_ts(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def window_date_label(cutoff_ts: int, window_end_dt: datetime) -> str:
    start = datetime.fromtimestamp(cutoff_ts, tz=timezone.utc).strftime("%Y-%m-%d")
    end = window_end_dt.strftime("%Y-%m-%d")
    return f"{start} -> {end}"


def default_window_end(now_dt: datetime) -> datetime:
    return datetime(now_dt.year, now_dt.month, now_dt.day, tzinfo=timezone.utc)


def compute_maker_fee_per_share(price: float, mode: str, custom_rate: float, taker_rate: float) -> float:
    """Per-share maker fee for the simulation.

    mode = "zero": Polymarket official — makers never pay fees.
    mode = "taker_rate": ablation — assume maker fee equals taker fee
                        (the buggy v3 assumption, kept so we can quote both).
    mode = "custom":   user supplies `--maker-fee-rate R`.
    """
    if mode == "zero":
        return 0.0
    if mode == "taker_rate":
        return taker_rate * price * (1 - price)
    if mode == "custom":
        return custom_rate * price * (1 - price)
    raise ValueError(f"unknown maker_fee_mode {mode!r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--markups", default="0.005,0.01,0.02,0.03,0.05")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--basket-size", type=float, default=100)
    ap.add_argument("--min-trade-size", type=float, default=0.0)
    ap.add_argument(
        "--maker-fee-mode",
        choices=["zero", "taker_rate", "custom"],
        default="zero",
        help="zero = official Polymarket (default). taker_rate = v3 bug, for ablation. custom requires --maker-fee-rate.",
    )
    ap.add_argument("--maker-fee-rate", type=float, default=0.0, help="Only used when --maker-fee-mode=custom.")
    ap.add_argument(
        "--in-sample-days",
        type=int,
        default=10,
        help="First N days of window are in-sample; remainder is out-of-sample. 14-day window -> 10 IS / 4 OOS.",
    )
    ap.add_argument(
        "--top-n-cherry-pick",
        type=int,
        default=18,
        help="For OOS analysis: pick top N groups by in-sample daily $, then report their OOS sum.",
    )
    ap.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="UTC end date YYYY-MM-DD. Window is [end_date - days, end_date]. Defaults to today.",
    )
    ap.add_argument(
        "--window-tag",
        type=str,
        default=None,
        help="Optional suffix for report/json filenames so multi-window runs don't overwrite each other.",
    )
    ap.add_argument(
        "--cohort-file",
        type=str,
        default=None,
        help="Path to a cohort JSON (same schema as binary-classification.json: "
             "{gid: {sub_tier, member_ids, questions}}). Defaults to the long-tail D-vs-R cohort.",
    )
    ap.add_argument(
        "--cohort-tier",
        type=str,
        default="dvr",
        help="sub_tier value to filter on within the cohort file. Default 'dvr' for backward compat.",
    )
    args = ap.parse_args()
    markups = [float(x) for x in args.markups.split(",")]
    if args.in_sample_days < 1 or args.in_sample_days >= args.days:
        print(f"ERROR: in-sample-days must be in [1, {args.days - 1}]", file=sys.stderr)
        return 2

    now_dt = datetime.now(tz=timezone.utc)
    if args.end_date:
        try:
            window_end_dt = datetime.strptime(args.end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            print(f"ERROR: --end-date must be YYYY-MM-DD, got {args.end_date!r}", file=sys.stderr)
            return 2
    else:
        window_end_dt = default_window_end(now_dt)
    cutoff_ts = int((window_end_dt - timedelta(days=args.days)).timestamp())
    end_ts = int(window_end_dt.timestamp())
    in_sample_end_ts = cutoff_ts + args.in_sample_days * 86400
    print(f"Window: {datetime.fromtimestamp(cutoff_ts, tz=timezone.utc).isoformat()}  ->  {window_end_dt.isoformat()}")
    print(f"  (report timestamp is real now: {now_dt.isoformat()})")
    print(f"  in-sample:  days 0..{args.in_sample_days - 1} ({args.in_sample_days} days)")
    print(f"  OOS:        days {args.in_sample_days}..{args.days - 1} ({args.days - args.in_sample_days} days)")
    print(f"  maker fee mode: {args.maker_fee_mode}")

    # 1. Load cohort. Default = the long-tail D-vs-R cohort (back-compat with v3).
    if args.cohort_file:
        cls_path = Path(args.cohort_file)
    else:
        cls_path = REPO_ROOT / "data" / "experiments" / "2026-05-13" / "binary-classification.json"
        if not cls_path.exists():
            cls_path = REPO_ROOT / "data" / "experiments" / "2026-05-12" / "binary-classification.json"
    if not cls_path.exists():
        print(f"ERROR: cohort file {cls_path} not found", file=sys.stderr)
        return 2
    cls = json.loads(cls_path.read_text(encoding="utf-8"))
    print(f"  cohort file: {cls_path}")
    print(f"  cohort tier filter: {args.cohort_tier}")
    target_gids = {gid for gid, c in cls.items() if c.get("sub_tier") == args.cohort_tier}
    member_ids_to_fetch: list[str] = []
    member_ids_by_gid: dict[str, list[str]] = {}
    for gid, c in cls.items():
        if c.get("sub_tier") != args.cohort_tier:
            continue
        mids = c.get("member_ids") or []
        if not mids:
            continue
        member_ids_by_gid[gid] = mids
        member_ids_to_fetch.extend(mids)
    # Include the explicit_other special-case used by v3 (Aaron Taylor-Johnson), DVR cohort only
    if args.cohort_tier == "dvr":
        for gid, c in cls.items():
            if gid.startswith("0xb23e25438839") and c.get("member_ids"):
                member_ids_by_gid[gid] = c["member_ids"]
                member_ids_to_fetch.extend(c["member_ids"])
    print(f"  classification: {len(cls)} entries, {len(member_ids_by_gid)} target groups, "
          f"{len(member_ids_to_fetch)} member markets to fetch")

    # 2. Fetch each target market directly by id (deterministic, no pagination bugs)
    print(f"\n[1/4] Fetching {len(member_ids_to_fetch)} Gamma markets by id (workers={args.workers})...")
    metas: dict[str, dict] = {}
    fetch_failures: list[str] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        future_to_id = {pool.submit(fetch_market_by_id, mid): mid for mid in member_ids_to_fetch}
        done = 0
        for fut in as_completed(future_to_id):
            mid = future_to_id[fut]
            done += 1
            m = fut.result()
            if m is None:
                fetch_failures.append(mid)
                continue
            nrid = str(m.get("negRiskMarketID") or "")
            cond_id = m.get("conditionId")
            if not nrid or not cond_id:
                fetch_failures.append(f"{mid}:no-nrid-or-cond")
                continue
            raw = m.get("clobTokenIds")
            try:
                tokens = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, json.JSONDecodeError):
                fetch_failures.append(f"{mid}:bad-tokens")
                continue
            if not tokens:
                fetch_failures.append(f"{mid}:no-tokens")
                continue
            fee_schedule = m.get("feeSchedule") or {}
            fee_rate = float((fee_schedule.get("rate") or 0.015))
            if not m.get("feesEnabled", True):
                fee_rate = 0.0
            metas[str(m.get("id"))] = {
                "market_id": str(m.get("id")),
                "condition_id": str(cond_id),
                "neg_risk_market_id": nrid,
                "yes_token_id": str(tokens[0]),
                "question": (m.get("question") or "")[:200],
                "fee_rate": fee_rate,
                "taker_only": fee_schedule.get("takerOnly"),
                "rebate_rate": fee_schedule.get("rebateRate"),
                "best_ask": float(m.get("bestAsk") or 0.0),
                "best_bid": float(m.get("bestBid") or 0.0),
            }
            if done % 30 == 0 or done == len(future_to_id):
                print(f"  fetched {done}/{len(future_to_id)} (kept {len(metas)}, failed {len(fetch_failures)})")
    if fetch_failures:
        print(f"  fetch failures: {len(fetch_failures)} (sample: {fetch_failures[:3]})")
    print(f"  total markets in metas: {len(metas)}")

    # Sanity check: every market we use should have takerOnly=True.
    # If not, the "maker fee = 0" assumption is wrong for that market.
    taker_only_check = defaultdict(int)
    for m in metas.values():
        taker_only_check[m["taker_only"]] += 1
    print(f"  takerOnly distribution: {dict(taker_only_check)}")
    if args.maker_fee_mode == "zero" and any(v is False for v in taker_only_check):
        print(
            "  WARN: some markets have takerOnly=False but maker-fee-mode=zero. "
            "Inspect feeSchedule before trusting results.",
            file=sys.stderr,
        )

    # 3. Build target_groups directly from member_ids_by_gid (rather than negRiskMarketID).
    # This is more robust than grouping by today's negRiskMarketID, since a few markets
    # in the cohort might have had their negRiskMarketID reassigned.
    by_group: dict[str, list[dict]] = defaultdict(list)
    for m in metas.values():
        by_group[m["neg_risk_market_id"]].append(m)
    target_groups: dict[str, list[dict]] = {}
    for gid, mids in member_ids_by_gid.items():
        members = [metas[mid] for mid in mids if mid in metas]
        if len(members) >= 2:
            target_groups[gid] = members
    n_target_recovered = sum(1 for gid in target_groups if gid in target_gids)
    print(
        f"  target groups: {len(target_groups)} "
        f"(of which {n_target_recovered}/{len(target_gids)} cohort IDs recovered)"
    )
    print(f"  legs total: {sum(len(ms) for ms in target_groups.values())}")

    # 3. Parallel-fetch trades
    print(f"\n[2/4] Fetching trade tape per leg (workers={args.workers})...")
    all_legs = [m for ms in target_groups.values() for m in ms]
    leg_trades: dict[str, list[dict]] = {}
    completed = 0
    failures: list[str] = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        future_to_leg = {pool.submit(fetch_trades_paginated, m["condition_id"], cutoff_ts): m for m in all_legs}
        for fut in as_completed(future_to_leg):
            m = future_to_leg[fut]
            completed += 1
            try:
                leg_trades[m["condition_id"]] = fut.result()
            except Exception as e:
                failures.append(f"{m['condition_id'][:16]}: {type(e).__name__}: {e}")
                leg_trades[m["condition_id"]] = []
            if completed % 30 == 0 or completed == len(future_to_leg):
                n_trades = sum(len(v) for v in leg_trades.values())
                print(f"  {completed}/{len(future_to_leg)} legs ({time.time()-t0:.0f}s, {n_trades} trades)")

    # Filter
    print(f"\n[3/4] Filtering to window, outcome=Yes, side=SELL...")
    filtered_trades: dict[str, list[dict]] = {}
    raw_total = 0
    kept_total = 0
    for cond_id, trades in leg_trades.items():
        raw_total += len(trades)
        kept = [
            t for t in trades
            if cutoff_ts <= t["timestamp"] <= end_ts
            and t.get("outcome") == "Yes"
            and t.get("side") == "SELL"
            and t.get("size", 0) >= args.min_trade_size
        ]
        filtered_trades[cond_id] = kept
        kept_total += len(kept)
    print(f"  {raw_total} raw trades -> {kept_total} qualified")

    # 4. Simulate
    print(f"\n[4/4] Simulating fills with maker_fee_mode={args.maker_fee_mode}...")
    all_days = sorted({day_of_ts(t["timestamp"]) for ts in filtered_trades.values() for t in ts})
    print(f"  {len(all_days)} distinct UTC days with qualifying trade activity")
    if not all_days:
        cur = datetime.fromtimestamp(cutoff_ts, tz=timezone.utc).strftime("%Y-%m-%d")
        end = window_end_dt.strftime("%Y-%m-%d")
        all_days = sorted({cur, end})

    leg_day_trades: dict[str, dict[str, list[tuple[float, float]]]] = {}
    for cond_id, trades in filtered_trades.items():
        per_day: dict[str, list[tuple[float, float]]] = defaultdict(list)
        for t in trades:
            d = day_of_ts(t["timestamp"])
            per_day[d].append((float(t["price"]), float(t["size"])))
        leg_day_trades[cond_id] = dict(per_day)

    def day_is_in_sample(d: str) -> bool:
        d_ts = int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
        return d_ts < in_sample_end_ts

    is_days_total = sum(1 for d in all_days if day_is_in_sample(d))
    oos_days_total = len(all_days) - is_days_total

    results: dict[str, dict] = {}
    skipped_narrow_spread = 0
    total_group_markup_pairs = len(target_groups) * len(markups)
    for gid, members in target_groups.items():
        markup_stats: dict[float, dict] = {}
        for markup in markups:
            targets: list[float] = []
            valid = True
            for m in members:
                t = m["best_ask"] - markup
                t = min(t, m["best_ask"] - 0.001)
                t = max(t, m["best_bid"] + 0.001)
                if t >= m["best_ask"] or t <= m["best_bid"]:
                    valid = False
                    break
                targets.append(t)
            if not valid:
                markup_stats[markup] = _empty_markup_stats(args, is_days_total, oos_days_total)
                skipped_narrow_spread += 1
                continue

            is_filled_days: list[dict] = []
            oos_filled_days: list[dict] = []
            for d in all_days:
                leg_qual_size: list[float] = []
                ok = True
                for m, target in zip(members, targets):
                    today = leg_day_trades.get(m["condition_id"], {}).get(d, [])
                    qual = sum(sz for (px, sz) in today if px <= target)
                    if qual <= 0:
                        ok = False
                        break
                    leg_qual_size.append(qual)
                if not ok:
                    continue
                min_leg = min(leg_qual_size)
                units = min(args.basket_size, min_leg)
                cost_pu = sum(targets)
                fee_pu = sum(
                    compute_maker_fee_per_share(t, args.maker_fee_mode, args.maker_fee_rate, m["fee_rate"])
                    for m, t in zip(members, targets)
                )
                edge_pu = 1.0 - cost_pu - fee_pu
                edge_dollars = edge_pu * units
                rec = {
                    "day": d,
                    "edge_per_unit": edge_pu,
                    "fee_per_unit": fee_pu,
                    "min_leg_qualified_size": min_leg,
                    "actual_basket_units": units,
                    "edge_dollars": edge_dollars,
                }
                if day_is_in_sample(d):
                    is_filled_days.append(rec)
                else:
                    oos_filled_days.append(rec)

            def half_stats(filled: list[dict], days_total: int) -> dict:
                if days_total <= 0:
                    return {"daily_dollars": 0.0, "n_filled": 0, "n_total": 0,
                            "fill_rate": 0.0, "avg_edge_pu": 0.0, "avg_units": 0.0,
                            "total_dollars": 0.0}
                total = sum(r["edge_dollars"] for r in filled)
                return {
                    "daily_dollars": total / days_total,
                    "n_filled": len(filled),
                    "n_total": days_total,
                    "fill_rate": len(filled) / days_total,
                    "avg_edge_pu": statistics.mean(r["edge_per_unit"] for r in filled) if filled else 0.0,
                    "avg_units": statistics.mean(r["actual_basket_units"] for r in filled) if filled else 0.0,
                    "total_dollars": total,
                }

            is_s = half_stats(is_filled_days, is_days_total)
            oos_s = half_stats(oos_filled_days, oos_days_total)

            markup_stats[markup] = {
                "targets": [round(t, 4) for t in targets],
                "in_sample": is_s,
                "oos": oos_s,
                # Whole-window (for legacy comparison to v3):
                "whole_window_daily_dollars": (is_s["total_dollars"] + oos_s["total_dollars"])
                    / max(1, is_s["n_total"] + oos_s["n_total"]),
            }

        q_short = " vs ".join([m["question"][:30] for m in members])
        results[gid] = {
            "neg_risk_market_id": gid,
            "members": [m["question"][:80] for m in members],
            "fee_rates_used": [m["fee_rate"] for m in members],
            "taker_only_flags": [m["taker_only"] for m in members],
            "rebate_rates": [m["rebate_rate"] for m in members],
            "question_short": q_short,
            "today_bestAsk_sum": sum(m["best_ask"] for m in members),
            "today_bestBid_sum": sum(m["best_bid"] for m in members),
            "markup_stats": markup_stats,
        }

    # ---- Aggregate ----
    def group_best_in_sample(r: dict) -> tuple[float, float, float, float]:
        """Return (best_in_sample_daily, oos_daily_at_same_markup, whole_daily, best_markup)."""
        if not r["markup_stats"]:
            return (0.0, 0.0, 0.0, 0.0)
        best_markup, best_s = max(
            r["markup_stats"].items(),
            key=lambda kv: kv[1]["in_sample"]["daily_dollars"],
        )
        return (
            best_s["in_sample"]["daily_dollars"],
            best_s["oos"]["daily_dollars"],
            best_s["whole_window_daily_dollars"],
            best_markup,
        )

    summaries = []
    for gid, r in results.items():
        is_d, oos_d, whole_d, best_m = group_best_in_sample(r)
        summaries.append({
            "gid": gid,
            "question_short": r["question_short"],
            "in_sample_daily": is_d,
            "oos_daily": oos_d,
            "whole_daily": whole_d,
            "best_markup": best_m,
        })
    summaries.sort(key=lambda x: x["in_sample_daily"], reverse=True)

    naive_in_sample_daily = sum(s["in_sample_daily"] for s in summaries)
    naive_oos_daily = sum(s["oos_daily"] for s in summaries)
    naive_whole_daily = sum(s["whole_daily"] for s in summaries)

    top_n = summaries[: args.top_n_cherry_pick]
    cherry_in_sample_daily = sum(s["in_sample_daily"] for s in top_n)
    cherry_oos_daily = sum(s["oos_daily"] for s in top_n)

    # ---- Report ----
    now = datetime.now(tz=timezone.utc)
    iso = now.isoformat()
    date_tag = now.strftime("%Y-%m-%d")

    lines = [
        f"# Maker Simulation v4 — Corrected fee + train/test split ({iso})",
        "",
        f"**Method**: v3 plumbing + two fixes:",
        f"  (A) maker fee mode = `{args.maker_fee_mode}` (v3 used taker_rate, which was wrong; "
        f"Polymarket docs: \"makers never pay fees\")",
        f"  (B) {args.in_sample_days}-day in-sample / {args.days - args.in_sample_days}-day OOS split. "
        f"Top {args.top_n_cherry_pick} groups picked by IN-SAMPLE daily $; their OOS sum reported separately.",
        "",
        f"**Window**: {args.days} days ({window_date_label(cutoff_ts, window_end_dt)})",
        f"**Basket size cap**: ${args.basket_size:.0f}",
        f"**Trades fetched**: {raw_total} raw -> {kept_total} qualifying",
        f"**Days with trade activity**: in-sample {is_days_total}, OOS {oos_days_total}",
        f"**takerOnly distribution across our markets**: {dict(taker_only_check)}",
        f"**Maker-quote skips**: {skipped_narrow_spread}/{total_group_markup_pairs} "
        f"group-markup pairs ({(skipped_narrow_spread / total_group_markup_pairs * 100) if total_group_markup_pairs else 0.0:.1f}%) "
        "skipped as `spread_too_narrow_for_maker`",
        "",
        "## Headline (with maker fee = 0)",
        "",
        f"| Verdict | Daily $ | Annualized |",
        f"|---|---:|---:|",
        f"| Naive (all {len(summaries)} groups), in-sample | ${naive_in_sample_daily:+.2f} | ${naive_in_sample_daily*365:+,.0f} |",
        f"| Naive (all {len(summaries)} groups), OOS | ${naive_oos_daily:+.2f} | ${naive_oos_daily*365:+,.0f} |",
        f"| Whole window (no split) | ${naive_whole_daily:+.2f} | ${naive_whole_daily*365:+,.0f} |",
        f"| **Top {args.top_n_cherry_pick} by in-sample, in-sample** | ${cherry_in_sample_daily:+.2f} | ${cherry_in_sample_daily*365:+,.0f} |",
        f"| **Top {args.top_n_cherry_pick} by in-sample, OOS** ← honest verdict | ${cherry_oos_daily:+.2f} | ${cherry_oos_daily*365:+,.0f} |",
        "",
        "If top-N OOS << top-N in-sample, the top-N looks like overfitting.",
        f"OOS / in-sample ratio for top-{args.top_n_cherry_pick}: "
        f"{(cherry_oos_daily / cherry_in_sample_daily) if cherry_in_sample_daily else 0.0:.2f}",
        "",
        f"## Top {args.top_n_cherry_pick} groups — in-sample picked, OOS measured",
        "",
        "| Rank | Group | Q | Best markup | IS daily $ | OOS daily $ | OOS/IS |",
        "|---:|---|---|---:|---:|---:|---:|",
    ]
    for i, s in enumerate(top_n, 1):
        ratio = (s["oos_daily"] / s["in_sample_daily"]) if s["in_sample_daily"] else 0.0
        lines.append(
            f"| {i} | `{s['gid'][:14]}...` | {s['question_short'][:42]} | ${s['best_markup']:.3f} | "
            f"${s['in_sample_daily']:+,.3f} | ${s['oos_daily']:+,.3f} | {ratio:+.2f} |"
        )

    lines += [
        "",
        "## Compared to prior versions",
        "",
        "| Version | Method | Annualized | Issue |",
        "|---|---|---:|---|",
        "| v1 (mid-touch) | mid touch as fill proxy | $15,546 | mid touching != fill |",
        "| v2 size-uncapped | sum of all SELL Yes | $918 | income computed at $100/fill regardless of trade size |",
        "| v3 size-capped, taker fee | size cap added | -$263 naive / +$117 cherry-pick | maker fee wrongly = taker fee; no OOS check |",
        f"| **v4 this run** | size cap + maker_fee={args.maker_fee_mode} + IS/OOS | "
        f"${naive_oos_daily*365:+,.0f} OOS naive / ${cherry_oos_daily*365:+,.0f} OOS top-{args.top_n_cherry_pick} | "
        "fee per docs; cherry-pick now measured out-of-sample |",
        "",
        "## Caveats (still standing)",
        "",
        "- Queue priority: assumes we are first in line at our maker price level.",
        "- Per-leg fills assumed independent within a day.",
        "- Maker fee = 0 ignores `rebateRate` (20-25% of pool taker fees redistributed to makers). Real maker income could be modestly HIGHER. Conservative direction.",
        "- Builder fees are not modeled. The maker-fee-zero assumption is for direct Polymarket platform fees; orders routed through a builder with `builder_maker_fee_bps` could pay a separate builder fee.",
        "- 14 days is a short window; the in-sample / OOS split is *one* random partition, not k-fold. Repeat with different splits to test stability.",
        "- Today's bestAsk/bestBid used to compute maker target — historical spread may have differed.",
        "",
        f"---\n*Snapshot: {iso}*",
    ]

    tag = f"-{args.window_tag}" if args.window_tag else ""
    report_path = REPO_ROOT / "reports" / f"maker-simulation-v4-{date_tag}{tag}.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")

    data_dir = REPO_ROOT / "data" / "experiments" / date_tag
    data_dir.mkdir(parents=True, exist_ok=True)
    json_path = data_dir / f"maker-simulation-v4-results{tag}.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump({
            "snapshot_ts": iso,
            "window_end_iso": window_end_dt.isoformat(),
            "window_start_iso": datetime.fromtimestamp(cutoff_ts, tz=timezone.utc).isoformat(),
            "window_tag": args.window_tag,
            "window_days": args.days,
            "in_sample_days": args.in_sample_days,
            "basket_size_usd": args.basket_size,
            "maker_fee_mode": args.maker_fee_mode,
            "maker_fee_rate_custom": args.maker_fee_rate,
            "top_n_cherry_pick": args.top_n_cherry_pick,
            "markups": markups,
            "n_groups": len(results),
            "n_raw_trades": raw_total,
            "n_qualifying_trades": kept_total,
            "n_failures": len(failures),
            "taker_only_distribution": dict(taker_only_check),
            "n_group_markup_pairs": total_group_markup_pairs,
            "n_skipped_narrow_spread": skipped_narrow_spread,
            "naive_in_sample_daily": naive_in_sample_daily,
            "naive_oos_daily": naive_oos_daily,
            "cherry_in_sample_daily": cherry_in_sample_daily,
            "cherry_oos_daily": cherry_oos_daily,
            "naive_whole_daily": naive_whole_daily,
            "summaries": summaries,
            "results": results,
        }, f, indent=2, ensure_ascii=False)

    print(f"\nreport: {report_path}")
    print(f"json:   {json_path}")
    print()
    print(f"=== v4 Summary (maker_fee_mode={args.maker_fee_mode}) ===")
    print(f"Naive in-sample annualized:                     ${naive_in_sample_daily*365:+,.0f}")
    print(f"Naive OOS annualized:                            ${naive_oos_daily*365:+,.0f}")
    print(f"Cherry-pick top-{args.top_n_cherry_pick} in-sample annualized: ${cherry_in_sample_daily*365:+,.0f}")
    print(f"Cherry-pick top-{args.top_n_cherry_pick} OOS annualized:        ${cherry_oos_daily*365:+,.0f}   <-- honest verdict")
    return 0


def _empty_markup_stats(args, is_days_total: int, oos_days_total: int) -> dict:
    return {
        "targets": [],
        "in_sample": {"daily_dollars": 0.0, "n_filled": 0, "n_total": is_days_total,
                      "fill_rate": 0.0, "avg_edge_pu": 0.0, "avg_units": 0.0, "total_dollars": 0.0},
        "oos": {"daily_dollars": 0.0, "n_filled": 0, "n_total": oos_days_total,
                "fill_rate": 0.0, "avg_edge_pu": 0.0, "avg_units": 0.0, "total_dollars": 0.0},
        "whole_window_daily_dollars": 0.0,
        "skipped": "spread_too_narrow_for_maker",
    }


if __name__ == "__main__":
    sys.exit(main())
