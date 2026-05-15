#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cross-platform Polymarket ↔ Kalshi probe — feasibility test.

Question being tested: do same-event markets on Polymarket and Kalshi price
themselves consistently, or are there persistent edges retail couldn't
arbitrage away?

This is RESEARCH ONLY. The user is based in China; Kalshi is US-only for
trading. We test whether the thesis HAS alpha, not whether we can execute it.

Method:
  1. Manual mapping of 5-15 known equivalent-event pairs (Fed rate, BTC,
     election outcomes, sports, etc.). Manual seed = avoid relying on
     the title-Jaccard pipeline for a first feasibility pass.
  2. For each pair: fetch both venues' orderbooks (Polymarket /book by
     token_id, Kalshi /markets/{ticker}/orderbook).
  3. Compute cross-platform arb edge:
       Option A: buy Poly_YES (taker) + buy Kalshi_NO (taker) — pays $1
       Option B: buy Poly_NO + buy Kalshi_YES — pays $1
       Edge = $1 - cost(A or B) - total_fees
       Fees: Poly_taker = rate * px * (1-px) [rate from feeSchedule]
             Kalshi_taker = 0.07 * px * (1-px)
  4. Output: pair-level edge today, plus optional repeat-snapshot persistence.

Output:
  data/experiments/<date>/cross-platform-probe-<run_tag>.json
  reports/cross-platform-probe-<date>-<run_tag>.md
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parent.parent
POLY_GAMMA = "https://gamma-api.polymarket.com/markets"
POLY_CLOB_BOOK = "https://clob.polymarket.com/book"
KALSHI_BASE = "https://external-api.kalshi.com/trade-api/v2"
KALSHI_TAKER_FEE = 0.07

# Manual mapping of known equivalent events. Each entry pairs ONE Polymarket
# market_id (Gamma `id`) with ONE Kalshi market ticker. We mark which side
# is the "YES" outcome on each venue (sometimes they're flipped).
#
# This list is the seed for the first probe. We can grow it later via the
# automatic Jaccard matcher in poly_strategy/cross_platform.py.
#
# NOTE: Polymarket Gamma ids and Kalshi tickers may go stale. The probe
# skips pairs that fail to fetch on either side and reports them.
MANUAL_PAIRS = [
    # Format:
    # {"label": "human-readable", "poly_id": "GAMMA_ID", "poly_outcome": "Yes" or "No",
    #  "kalshi_ticker": "KALSHI_TICKER", "kalshi_outcome": "yes" or "no"}
    # Filled in by the bootstrap step below from live data.
]


def _fetch_json(url: str, timeout: float = 15.0, retries: int = 2) -> tuple[int, dict]:
    for i in range(retries):
        try:
            req = Request(url, headers={"User-Agent": "poly_strategy-cprobe/1.0"})
            with urlopen(req, timeout=timeout) as resp:
                return resp.getcode(), json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            if i == retries - 1:
                return 0, {"error": str(e)[:200]}
            time.sleep(2 + i)
    return 0, {"error": "unreachable"}


def fetch_poly_market(market_id: str) -> Optional[dict]:
    code, d = _fetch_json(f"{POLY_GAMMA}/{market_id}")
    if code != 200 or not isinstance(d, dict) or "id" not in d:
        return None
    return d


def fetch_poly_book(token_id: str) -> Optional[dict]:
    """Fetch Polymarket CLOB book for a YES or NO token id."""
    code, d = _fetch_json(f"{POLY_CLOB_BOOK}?token_id={token_id}")
    if code != 200 or not isinstance(d, dict):
        return None
    return d


def fetch_kalshi_orderbook(ticker: str) -> Optional[dict]:
    code, d = _fetch_json(f"{KALSHI_BASE}/markets/{ticker}/orderbook")
    if code != 200 or not isinstance(d, dict):
        return None
    return d


def fetch_kalshi_market(ticker: str) -> Optional[dict]:
    code, d = _fetch_json(f"{KALSHI_BASE}/markets/{ticker}")
    if code != 200 or not isinstance(d, dict):
        return None
    return d.get("market")


def poly_best_ask(book: dict) -> Optional[float]:
    """Return the lowest ask price from a Poly book, or None if empty.

    Polymarket /book returns:
      {"market": "...", "asks": [{"price":"0.45","size":"10.0"}, ...],
                       "bids": [{"price":"0.44","size":"5.0"}, ...]}
    Asks are sorted ascending (best = lowest). For maker-style sim we'd want
    bids; here we want taker ask.
    """
    asks = book.get("asks") or []
    if not asks:
        return None
    # Find min price
    try:
        return min(float(a.get("price")) for a in asks if a.get("price"))
    except (TypeError, ValueError):
        return None


def kalshi_top_ask(orderbook: dict, side: str) -> Optional[float]:
    """Return the synthetic lowest ask on Kalshi for YES or NO side.

    Kalshi /orderbook returns:
      {"orderbook_fp": {"yes_dollars": [[price_str, size_str], ...],
                        "no_dollars":  [[price_str, size_str], ...]}}

    Each `_dollars` array is bids, not asks. In a binary market, a NO bid at
    p implies a YES ask at 1-p, and vice versa.
    """
    book = orderbook.get("orderbook_fp") or {}
    opposite_key = "no_dollars" if side.lower() == "yes" else "yes_dollars"
    levels = book.get(opposite_key) or []
    if not levels:
        return None
    try:
        best_opposite_bid = max(float(level[0]) for level in levels)
    except (TypeError, ValueError, IndexError):
        return None
    return round(1.0 - best_opposite_bid, 6)


def cross_platform_edge(poly_market: dict, poly_outcome: str,
                         kalshi_outcome: str, poly_book: dict, kalshi_book: dict) -> dict:
    """Compute one direction's arb edge: buy Poly + buy Kalshi opposite side.

    Returns dict with cost components and net edge.
    """
    # Poly side
    poly_outcomes = poly_market.get("outcomes")
    if isinstance(poly_outcomes, str):
        try:
            poly_outcomes = json.loads(poly_outcomes)
        except json.JSONDecodeError:
            poly_outcomes = []
    poly_tokens_raw = poly_market.get("clobTokenIds")
    if isinstance(poly_tokens_raw, str):
        try:
            poly_tokens = json.loads(poly_tokens_raw)
        except json.JSONDecodeError:
            poly_tokens = []
    else:
        poly_tokens = poly_tokens_raw or []

    # Index by outcome name (e.g., "Yes"/"No")
    poly_token_id = None
    if poly_outcomes and poly_tokens and len(poly_outcomes) == len(poly_tokens):
        for i, oc in enumerate(poly_outcomes):
            if str(oc).strip().lower() == poly_outcome.strip().lower():
                poly_token_id = poly_tokens[i]
                break

    poly_ask_price = poly_best_ask(poly_book)
    kalshi_ask_price = kalshi_top_ask(kalshi_book, kalshi_outcome)

    fee_rate = (poly_market.get("feeSchedule") or {}).get("rate") or 0.0
    if not poly_market.get("feesEnabled", True):
        fee_rate = 0.0
    fee_rate = float(fee_rate)

    poly_fee = fee_rate * poly_ask_price * (1 - poly_ask_price) if poly_ask_price else None
    kalshi_fee = KALSHI_TAKER_FEE * kalshi_ask_price * (1 - kalshi_ask_price) if kalshi_ask_price else None

    if poly_ask_price is None or kalshi_ask_price is None:
        return {
            "poly_ask": poly_ask_price,
            "kalshi_ask": kalshi_ask_price,
            "feasible": False,
            "reason": "missing-quote",
        }

    cost = poly_ask_price + kalshi_ask_price
    fees = (poly_fee or 0.0) + (kalshi_fee or 0.0)
    edge_per_share = 1.0 - cost - fees
    return {
        "poly_token_id": str(poly_token_id) if poly_token_id else None,
        "poly_ask": poly_ask_price,
        "kalshi_ask": kalshi_ask_price,
        "poly_fee_rate": fee_rate,
        "poly_fee_per_share": poly_fee,
        "kalshi_fee_per_share": kalshi_fee,
        "total_cost": cost,
        "total_fees": fees,
        "edge_per_share": edge_per_share,
        "feasible": True,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--pairs-file",
        type=str,
        default=None,
        help="JSON file with manual market pair mappings. See MANUAL_PAIRS in this script for schema.",
    )
    ap.add_argument(
        "--snapshots",
        type=int,
        default=1,
        help="Number of snapshots to take. With >1 + --snapshot-interval, "
             "we measure persistence of edges over time.",
    )
    ap.add_argument(
        "--snapshot-interval",
        type=float,
        default=300.0,
        help="Seconds between snapshots (default 5 min). Ignored if --snapshots=1.",
    )
    ap.add_argument("--run-tag", type=str, default="probe")
    args = ap.parse_args()

    if args.pairs_file:
        pairs = json.loads(Path(args.pairs_file).read_text(encoding="utf-8"))
    else:
        pairs = MANUAL_PAIRS
    if not pairs:
        print("ERROR: no pairs to probe. Provide --pairs-file or fill in MANUAL_PAIRS.", file=sys.stderr)
        return 2

    snapshots = []
    for snap_idx in range(args.snapshots):
        ts = datetime.now(tz=timezone.utc).isoformat()
        print(f"\n=== Snapshot {snap_idx+1}/{args.snapshots} @ {ts} ===")
        rows = []
        for pair in pairs:
            label = pair.get("label", "?")
            poly_id = pair["poly_id"]
            kalshi_ticker = pair["kalshi_ticker"]
            poly_outcome = pair["poly_outcome"]
            kalshi_outcome = pair["kalshi_outcome"]

            poly_market = fetch_poly_market(poly_id)
            kalshi_book = fetch_kalshi_orderbook(kalshi_ticker)
            if poly_market is None or kalshi_book is None:
                row = {
                    "label": label, "poly_id": poly_id, "kalshi_ticker": kalshi_ticker,
                    "feasible": False, "reason": "fetch_failed",
                    "poly_ok": poly_market is not None,
                    "kalshi_ok": kalshi_book is not None,
                }
                print(f"  {label[:45]:46}  FETCH FAIL  poly={row['poly_ok']} kalshi={row['kalshi_ok']}")
                rows.append(row)
                continue
            # Fetch poly book for the matched outcome's token id
            poly_outcomes = poly_market.get("outcomes")
            if isinstance(poly_outcomes, str):
                try:
                    poly_outcomes = json.loads(poly_outcomes)
                except json.JSONDecodeError:
                    poly_outcomes = []
            poly_tokens_raw = poly_market.get("clobTokenIds")
            if isinstance(poly_tokens_raw, str):
                try:
                    poly_tokens = json.loads(poly_tokens_raw)
                except json.JSONDecodeError:
                    poly_tokens = []
            else:
                poly_tokens = poly_tokens_raw or []
            poly_token_id = None
            for i, oc in enumerate(poly_outcomes or []):
                if str(oc).strip().lower() == poly_outcome.strip().lower() and i < len(poly_tokens):
                    poly_token_id = poly_tokens[i]
                    break
            poly_book = fetch_poly_book(poly_token_id) if poly_token_id else None
            if poly_book is None:
                row = {
                    "label": label, "poly_id": poly_id, "kalshi_ticker": kalshi_ticker,
                    "feasible": False, "reason": "poly_book_missing",
                }
                print(f"  {label[:45]:46}  POLY BOOK MISSING")
                rows.append(row)
                continue

            edge_info = cross_platform_edge(poly_market, poly_outcome, kalshi_outcome, poly_book, kalshi_book)
            edge_info.update({
                "label": label, "poly_id": poly_id, "kalshi_ticker": kalshi_ticker,
                "poly_outcome": poly_outcome, "kalshi_outcome": kalshi_outcome,
                "poly_question": (poly_market.get("question") or "")[:80],
            })
            rows.append(edge_info)
            if edge_info.get("feasible"):
                ed = edge_info["edge_per_share"]
                sign = "+" if ed > 0 else " "
                mark = "  ARB!" if ed > 0 else ""
                print(f"  {label[:45]:46}  poly_ask={edge_info['poly_ask']:.4f}  "
                      f"kalshi_ask={edge_info['kalshi_ask']:.4f}  "
                      f"cost={edge_info['total_cost']:.4f}  fees={edge_info['total_fees']:.4f}  "
                      f"edge={sign}{ed:.4f}{mark}")

        snapshots.append({"snapshot_ts": ts, "rows": rows})
        if snap_idx + 1 < args.snapshots:
            time.sleep(args.snapshot_interval)

    # ---- Aggregate ----
    now = datetime.now(tz=timezone.utc)
    iso = now.isoformat()
    date_tag = now.strftime("%Y-%m-%d")

    feasible_snapshots = [s for s in snapshots]
    # Pair-level summary across snapshots
    pair_keys = set()
    for s in snapshots:
        for r in s["rows"]:
            pair_keys.add((r["label"], r.get("poly_id", "?"), r.get("kalshi_ticker", "?")))
    pair_summary = []
    for key in pair_keys:
        label, poly_id, kalshi_ticker = key
        edges = []
        n_arb = 0
        n_feasible = 0
        for s in snapshots:
            for r in s["rows"]:
                if (r["label"], r.get("poly_id", "?"), r.get("kalshi_ticker", "?")) != key:
                    continue
                if r.get("feasible"):
                    n_feasible += 1
                    edges.append(r["edge_per_share"])
                    if r["edge_per_share"] > 0:
                        n_arb += 1
        if not edges:
            continue
        pair_summary.append({
            "label": label, "poly_id": poly_id, "kalshi_ticker": kalshi_ticker,
            "n_snapshots": len(snapshots),
            "n_feasible": n_feasible,
            "n_with_positive_arb": n_arb,
            "mean_edge": statistics.mean(edges),
            "median_edge": statistics.median(edges),
            "min_edge": min(edges),
            "max_edge": max(edges),
        })
    pair_summary.sort(key=lambda x: -x["mean_edge"])

    # ---- Report ----
    lines = [
        f"# Cross-platform Polymarket-Kalshi probe ({iso})",
        "",
        f"**Pairs probed**: {len(pair_keys)}",
        f"**Snapshots**: {len(snapshots)} at {args.snapshot_interval:.0f}s interval",
        f"**Maker fee (Poly)**: per-market `feeSchedule.rate` (taker rate, since this models taker arb)",
        f"**Kalshi taker fee**: {KALSHI_TAKER_FEE*100:.1f}% (`rate * price * (1-price)`)",
        "",
        "## Per-pair summary",
        "",
        "| Label | n feasible / n snaps | n with +arb | Mean edge | Median edge | Min edge | Max edge |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for p in pair_summary:
        lines.append(
            f"| {p['label'][:48]} | {p['n_feasible']}/{p['n_snapshots']} | {p['n_with_positive_arb']} "
            f"| {p['mean_edge']:+.4f} | {p['median_edge']:+.4f} | {p['min_edge']:+.4f} | {p['max_edge']:+.4f} |"
        )

    # Honest verdict block
    if pair_summary:
        total_mean = sum(p["mean_edge"] for p in pair_summary)
        n_positive_pairs = sum(1 for p in pair_summary if p["mean_edge"] > 0)
        n_persistent_positive = sum(1 for p in pair_summary if p["n_with_positive_arb"] == p["n_snapshots"])
        lines += [
            "",
            "## Verdict signals",
            "",
            f"- Pairs with mean edge > 0 across snapshots: **{n_positive_pairs} / {len(pair_summary)}**",
            f"- Pairs with edge > 0 in ALL {len(snapshots)} snapshots (persistent): **{n_persistent_positive}**",
            f"- Sum of mean edges (signed) across all pairs: **{total_mean:+.4f}** per $1-share basket",
            "",
            "**Read**: an edge of +0.005 = 0.5% per $1 of paired notional. If a pair shows persistent +edge "
            "across many snapshots, that's the strongest signal (rules out 'just bad snapshot timing'). "
            "Single-snapshot positive edges can be momentary book imbalance from one liquidity event.",
        ]

    lines += [
        "",
        f"---\n*Snapshot: {iso}*",
    ]

    report_path = REPO_ROOT / "reports" / f"cross-platform-probe-{date_tag}-{args.run_tag}.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    data_dir = REPO_ROOT / "data" / "experiments" / date_tag
    data_dir.mkdir(parents=True, exist_ok=True)
    json_path = data_dir / f"cross-platform-probe-{args.run_tag}.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump({"snapshots": snapshots, "pair_summary": pair_summary, "run_tag": args.run_tag}, f, indent=2, ensure_ascii=False)

    print(f"\nreport: {report_path}")
    print(f"json:   {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
