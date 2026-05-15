#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a neg-risk group cohort for v4 simulations.

The v3/v4 sim was hardcoded to consume `binary-classification.json` (long-tail
D-vs-R races only). To test the maker thesis on other cohorts (high-vol,
mid-vol, by sport, by size, etc.) we need a generic cohort selector.

Inputs:
  - Live Gamma /markets, paginated correctly (offset += 100; gamma caps each
    page at 100 regardless of `limit` param).

Filter parameters:
  --min-sum-vol24h X   minimum sum-over-members vol24hr (default 10000)
  --min-size N         minimum group member count (default 3)
  --max-size N         optional upper bound

Output:
  data/experiments/<date>/negrisk-cohort-<tag>.json
  {
    <neg_risk_market_id>: {
      "sub_tier": "high_vol",            # constant label for the cohort
      "label": "<auto-summary>",
      "questions": [<member questions>],
      "member_ids": [<member market ids>],
      "sum_vol24h": float,
      "max_vol24h": float,
      "n_members": int,
      "spread": float,
      "sum_ask": float,
    },
    ...
  }

This matches the schema v4 expects from binary-classification.json so v4 can
swap in a different cohort with `--cohort-file PATH`.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parent.parent
GAMMA_MARKETS_URL = "https://gamma-api.polymarket.com/markets"


def fetch_all_negrisk_markets(max_offset: int = 5000, timeout: float = 15.0,
                               consecutive_empty_tolerance: int = 3) -> list[dict]:
    """Paginate /markets with offset += 100 (the actual page size cap).

    Gamma occasionally returns empty pages mid-stream even when there are more
    results. We tolerate up to `consecutive_empty_tolerance` empties before
    declaring the end of results.
    """
    all_markets: list[dict] = []
    consec_empty = 0
    for offset in range(0, max_offset, 100):
        params = urlencode({"limit": 100, "offset": offset, "active": "true", "closed": "false"})
        url = f"{GAMMA_MARKETS_URL}?{params}"
        req = Request(url, headers={"User-Agent": "poly_strategy-cohort/1.0"})
        try:
            with urlopen(req, timeout=timeout) as resp:
                batch = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"offset {offset}: ERROR {e}", file=sys.stderr)
            consec_empty += 1
            if consec_empty >= consecutive_empty_tolerance:
                break
            continue
        if not batch:
            consec_empty += 1
            if consec_empty >= consecutive_empty_tolerance:
                break
            continue
        consec_empty = 0
        all_markets.extend(batch)
    return all_markets


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-sum-vol24h", type=float, default=10000.0)
    ap.add_argument("--min-size", type=int, default=3)
    ap.add_argument("--max-size", type=int, default=None)
    ap.add_argument("--max-offset", type=int, default=5000,
                    help="Pagination ceiling. Today there are ~422 neg-risk groups in 4000 markets.")
    ap.add_argument("--tag", type=str, default="high-vol",
                    help="Tag for the output filename and the sub_tier label.")
    ap.add_argument(
        "--require-fees-enabled",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Require Gamma feesEnabled=True markets. Use --no-require-fees-enabled to include all markets.",
    )
    args = ap.parse_args()

    now = datetime.now(tz=timezone.utc)
    date_tag = now.strftime("%Y-%m-%d")

    print(f"Fetching neg-risk markets (max_offset={args.max_offset})...")
    all_markets = fetch_all_negrisk_markets(max_offset=args.max_offset)
    print(f"  total markets fetched: {len(all_markets)}")

    groups: dict[str, list[dict]] = defaultdict(list)
    for m in all_markets:
        nrid = str(m.get("negRiskMarketID") or "")
        if not nrid or not m.get("negRisk"):
            continue
        if args.require_fees_enabled and not m.get("feesEnabled", True):
            continue
        groups[nrid].append({
            "id": str(m.get("id")),
            "question": (m.get("question") or "")[:200],
            "vol24h": float(m.get("volume24hr") or 0.0),
            "liquidity": float(m.get("liquidity") or 0.0),
            "best_ask": float(m.get("bestAsk") or 0.0),
            "best_bid": float(m.get("bestBid") or 0.0),
        })
    print(f"  distinct neg-risk groups: {len(groups)}")

    cohort: dict[str, dict] = {}
    rejected = {"size": 0, "vol": 0}
    for nrid, members in groups.items():
        n = len(members)
        if n < args.min_size:
            rejected["size"] += 1
            continue
        if args.max_size is not None and n > args.max_size:
            rejected["size"] += 1
            continue
        sum_vol = sum(m["vol24h"] for m in members)
        if sum_vol < args.min_sum_vol24h:
            rejected["vol"] += 1
            continue
        sum_ask = sum(m["best_ask"] for m in members)
        sum_bid = sum(m["best_bid"] for m in members)
        # Use the longest member question as the human label
        label_q = max(members, key=lambda m: len(m["question"]))["question"][:80]
        cohort[nrid] = {
            "sub_tier": args.tag,
            "label": label_q,
            "questions": [m["question"] for m in members],
            "member_ids": [m["id"] for m in members],
            "n_members": n,
            "sum_vol24h": round(sum_vol, 2),
            "max_vol24h": round(max(m["vol24h"] for m in members), 2),
            "sum_ask": round(sum_ask, 4),
            "sum_bid": round(sum_bid, 4),
            "spread": round(sum_ask - sum_bid, 4),
        }

    print(f"  rejected by size:   {rejected['size']}")
    print(f"  rejected by vol:    {rejected['vol']}")
    print(f"  kept in cohort:     {len(cohort)}")

    if not cohort:
        print("WARN: cohort is empty; check thresholds.", file=sys.stderr)

    out_dir = REPO_ROOT / "data" / "experiments" / date_tag
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"negrisk-cohort-{args.tag}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(cohort, f, indent=2, ensure_ascii=False)
    print(f"\nWrote: {out_path}")
    print(f"  threshold: min_sum_vol24h=${args.min_sum_vol24h:,.0f}, "
          f"min_size={args.min_size}, max_size={args.max_size}")

    # Quick summary
    if cohort:
        top = sorted(cohort.values(), key=lambda c: -c["sum_vol24h"])[:5]
        print(f"\nTop 5 by sum_vol24h:")
        for c in top:
            print(f"  ${c['sum_vol24h']:>12,.0f}  n={c['n_members']:3d}  "
                  f"sum_ask={c['sum_ask']:.3f}  spread={c['spread']:.3f}  "
                  f"{c['label'][:55]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
