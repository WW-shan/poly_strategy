import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Optional

from poly_strategy.collectors import (
    canonical_market_id,
    expand_market_ids_with_neg_risk_groups,
    market_fee_rate,
    market_id_alias_map,
    market_ids_from_rule_file,
    raw_gamma_markets_from_ndjson,
)


def build_polymarket_watchlist(
    gamma_path: Path,
    rules_path: Path,
    expand_neg_risk_groups: bool = True,
    include_top_markets: int = 0,
    include_top_neg_risk_groups: int = 0,
    min_liquidity: float = 0.0,
    min_volume_24h: float = 0.0,
    max_markets: Optional[int] = None,
    external_signals_path: Optional[Path] = None,
) -> list:
    markets = raw_gamma_markets_from_ndjson(gamma_path)
    alias_to_market_id = market_id_alias_map(markets)
    market_ids = _canonicalize_market_ids(market_ids_from_rule_file(rules_path), alias_to_market_id)
    priority = Counter()
    reasons = defaultdict(set)
    for market_id in market_ids:
        priority[str(market_id)] += 1_000_000.0
        reasons[str(market_id)].add("rule")

    if expand_neg_risk_groups:
        market_ids = expand_market_ids_with_neg_risk_groups(markets, market_ids)
        for market_id in market_ids:
            reasons[str(market_id)].add("rule_neg_risk_expand")

    for market_id, score, reason in _top_liquid_market_ids(
        markets,
        include_top_markets,
        min_liquidity=min_liquidity,
        min_volume_24h=min_volume_24h,
    ):
        market_ids.add(market_id)
        priority[market_id] += score
        reasons[market_id].add(reason)

    for market_id, score, reason in _top_neg_risk_group_market_ids(
        markets,
        include_top_neg_risk_groups,
        min_liquidity=min_liquidity,
        min_volume_24h=min_volume_24h,
    ):
        market_ids.add(market_id)
        priority[market_id] += score
        reasons[market_id].add(reason)

    external_signal_market_ids = set()
    for market_id, score in _external_signal_market_scores(external_signals_path, alias_to_market_id).items():
        market_ids.add(market_id)
        external_signal_market_ids.add(market_id)
        priority[market_id] += score
        reasons[market_id].add("external_signal")

    if expand_neg_risk_groups and external_signal_market_ids:
        expanded_external_signal_market_ids = expand_market_ids_with_neg_risk_groups(markets, external_signal_market_ids)
        for market_id in expanded_external_signal_market_ids - market_ids:
            market_ids.add(market_id)
            reasons[market_id].add("external_signal_neg_risk_expand")

    rows = _watchlist_rows(markets, market_ids, priority=priority, reasons=reasons)
    if max_markets is not None:
        if max_markets < 1:
            raise ValueError("max_markets must be at least 1")
        rows = _cap_watchlist_rows(rows, max_markets)
        rows.sort(key=lambda row: (row.get("neg_risk_market_id") or "", _threshold_key(row), row["market_id"]))
    return rows


def write_watchlist(rows: Iterable[dict], path: Path) -> int:
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "polymarket_watchlist", "markets": rows}, indent=2, sort_keys=True) + "\n")
    return len(rows)


def _watchlist_rows(
    markets: Iterable[dict],
    market_ids: Iterable[str],
    priority: Optional[Counter] = None,
    reasons: Optional[dict] = None,
) -> list:
    wanted = {str(market_id) for market_id in market_ids if market_id}
    rows = []
    seen = set()
    priority = priority or Counter()
    reasons = reasons or {}
    for market in markets:
        market_id = canonical_market_id(market)
        if not market_id or market_id not in wanted or market_id in seen:
            continue
        seen.add(market_id)
        token_ids = _loads_json_list(market.get("clobTokenIds"))
        rows.append(
            {
                "venue": "polymarket",
                "market_id": market_id,
                "question": market.get("question"),
                "fee_rate": market_fee_rate(market),
                "neg_risk": bool(market.get("negRisk")),
                "neg_risk_market_id": str(market.get("negRiskMarketID") or "").strip() or None,
                "group_item_title": str(market.get("groupItemTitle") or "").strip() or None,
                "group_item_threshold": str(market.get("groupItemThreshold") or "").strip() or None,
                "yes_token_id": str(token_ids[0]) if len(token_ids) >= 1 else None,
                "no_token_id": str(token_ids[1]) if len(token_ids) >= 2 else None,
                "priority_score": float(priority.get(market_id, _market_priority_score(market))),
                "priority_reasons": sorted(reasons.get(market_id, [])) or ["selected"],
            }
        )
    rows.sort(key=lambda row: (row.get("neg_risk_market_id") or "", _threshold_key(row), row["market_id"]))
    return rows


def _cap_watchlist_rows(rows: list, max_markets: int) -> list:
    if len(rows) <= max_markets:
        return list(rows)

    items = _atomic_watchlist_items(rows)
    for item in items:
        item["selected"] = False

    selected = []
    max_external_signal_rows = max(1, max_markets // 2) if any(item["external_signal"] for item in items) else 0
    external_signal_used = 0
    external_signal_items = [item for item in items if item["external_signal"]]
    external_signal_items.sort(key=lambda item: (-float(item["external_score"]), -float(item["score"]), item["key"]))
    for item in external_signal_items:
        if item["size"] > max_markets:
            continue
        if external_signal_used + item["size"] > max_external_signal_rows:
            continue
        selected.extend(item["rows"])
        item["selected"] = True
        external_signal_used += item["size"]
        if len(selected) >= max_markets:
            return selected

    remaining_items = [item for item in items if not item["selected"]]
    remaining_items.sort(key=lambda item: (-float(item["score"]), item["key"]))
    for item in remaining_items:
        if len(selected) + item["size"] > max_markets:
            continue
        selected.extend(item["rows"])
        item["selected"] = True
        if len(selected) >= max_markets:
            break
    return selected


def _atomic_watchlist_items(rows: list) -> list:
    grouped = defaultdict(list)
    singles = []
    for row in rows:
        group_id = str(row.get("neg_risk_market_id") or "").strip()
        if group_id:
            grouped[group_id].append(row)
        else:
            singles.append(row)

    items = []
    for group_id, group_rows in grouped.items():
        group_rows = sorted(group_rows, key=_priority_sort_key)
        external_rows = [row for row in group_rows if "external_signal" in (row.get("priority_reasons") or [])]
        items.append(
            {
                "kind": "group",
                "key": group_id,
                "rows": group_rows,
                "score": sum(float(row.get("priority_score") or 0.0) for row in group_rows),
                "external_score": sum(float(row.get("priority_score") or 0.0) for row in external_rows),
                "external_signal": bool(external_rows),
                "size": len(group_rows),
            }
        )
    for row in singles:
        has_external_signal = "external_signal" in (row.get("priority_reasons") or [])
        score = float(row.get("priority_score") or 0.0)
        items.append(
            {
                "kind": "single",
                "key": row["market_id"],
                "rows": [row],
                "score": score,
                "external_score": score if has_external_signal else 0.0,
                "external_signal": has_external_signal,
                "size": 1,
            }
        )
    return items


def _top_liquid_market_ids(
    markets: Iterable[dict],
    limit: int,
    min_liquidity: float = 0.0,
    min_volume_24h: float = 0.0,
) -> list:
    if limit < 0:
        raise ValueError("include_top_markets must be non-negative")
    if limit == 0:
        return []
    candidates = []
    for market in markets:
        if not _is_tradeable_binary_market(market):
            continue
        market_id = canonical_market_id(market)
        liquidity = _float_field(market, "liquidityNum", "liquidityClob", "liquidity")
        volume_24h = _float_field(market, "volume24hrClob", "volume24hr")
        if liquidity < min_liquidity or volume_24h < min_volume_24h:
            continue
        candidates.append((market_id, _market_priority_score(market), "top_liquidity"))
    candidates.sort(key=lambda row: (-row[1], row[0]))
    return candidates[:limit]


def _top_neg_risk_group_market_ids(
    markets: Iterable[dict],
    group_limit: int,
    min_liquidity: float = 0.0,
    min_volume_24h: float = 0.0,
) -> list:
    if group_limit < 0:
        raise ValueError("include_top_neg_risk_groups must be non-negative")
    if group_limit == 0:
        return []
    groups = defaultdict(list)
    for market in markets:
        if not _is_tradeable_binary_market(market):
            continue
        group_id = str(market.get("negRiskMarketID") or "").strip()
        if not group_id:
            continue
        groups[group_id].append(market)

    ranked_groups = []
    for group_id, group_markets in groups.items():
        group_liquidity = sum(_float_field(market, "liquidityNum", "liquidityClob", "liquidity") for market in group_markets)
        group_volume_24h = sum(_float_field(market, "volume24hrClob", "volume24hr") for market in group_markets)
        if group_liquidity < min_liquidity or group_volume_24h < min_volume_24h:
            continue
        ranked_groups.append((group_id, sum(_market_priority_score(market) for market in group_markets), group_markets))
    ranked_groups.sort(key=lambda row: (-row[1], row[0]))

    selected = []
    for _, group_score, group_markets in ranked_groups[:group_limit]:
        for market in group_markets:
            market_id = canonical_market_id(market)
            if market_id:
                selected.append((market_id, group_score + _market_priority_score(market), "top_neg_risk_group"))
    return selected


def _external_signal_market_scores(path: Optional[Path], alias_to_market_id: Optional[dict] = None) -> Counter:
    scores = {}
    if not path or not path.exists():
        return Counter()
    alias_to_market_id = alias_to_market_id or {}
    rows = []
    with path.open() as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    for index, row in enumerate(rows):
        signal_score = 100_000.0 + 10_000.0 * float(row.get("quoted_edge") or 0.0) + float(index)
        if row.get("type") != "external_signal":
            continue
        for leg in row.get("legs", []):
            if str(leg.get("venue") or "").lower() != "polymarket":
                continue
            raw_market_id = str(leg.get("market_id") or "").strip()
            market_id = alias_to_market_id.get(raw_market_id, raw_market_id)
            if market_id:
                current = scores.get(market_id)
                if current is None or signal_score > current:
                    scores[market_id] = signal_score
    return Counter(scores)


def _canonicalize_market_ids(market_ids: Iterable[str], alias_to_market_id: dict) -> set:
    return {alias_to_market_id.get(str(market_id).strip(), str(market_id).strip()) for market_id in market_ids if market_id}


def _market_priority_score(market: dict) -> float:
    liquidity = _float_field(market, "liquidityNum", "liquidityClob", "liquidity")
    volume_24h = _float_field(market, "volume24hrClob", "volume24hr")
    volume_1wk = _float_field(market, "volume1wkClob", "volume1wk")
    volume_total = _float_field(market, "volumeNum", "volumeClob", "volume")
    spread_penalty = max(0.0, _float_field(market, "spread")) * 1_000.0
    return liquidity + (2.0 * volume_24h) + (0.20 * volume_1wk) + (0.01 * volume_total) - spread_penalty


def _is_tradeable_binary_market(market: dict) -> bool:
    if market.get("closed") is True:
        return False
    if market.get("active") is False:
        return False
    if market.get("enableOrderBook") is False:
        return False
    if market.get("acceptingOrders") is False:
        return False
    outcomes = _loads_json_list(market.get("outcomes"))
    if outcomes and len(outcomes) != 2:
        return False
    return len(_loads_json_list(market.get("clobTokenIds"))) == 2


def _float_field(row: dict, *keys: str) -> float:
    for key in keys:
        value = row.get(key)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def _priority_sort_key(row: dict) -> tuple:
    return (-float(row.get("priority_score") or 0.0), row.get("market_id") or "")


def _loads_json_list(value) -> list:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        loaded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(loaded, list):
        return []
    return loaded


def _threshold_key(row: dict) -> tuple:
    value = row.get("group_item_threshold")
    try:
        return (0, float(value))
    except (TypeError, ValueError):
        return (1, str(value or ""))
