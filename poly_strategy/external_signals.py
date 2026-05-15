import json
import hashlib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener, urlopen

from poly_strategy.oddpool import reserve_oddpool_quota


def ingest_external_signals(
    out_path: Path,
    source: str,
    input_path: Optional[Path] = None,
    url=None,
    timeout: float = 10.0,
    proxy: Optional[str] = None,
    headers: Optional[dict] = None,
    oddpool_quota_state_path: Optional[Path] = None,
    oddpool_monthly_quota: int = 1000,
    oddpool_min_interval_seconds: float = 1.0,
) -> int:
    if not source:
        raise ValueError("source is required")
    urls = _url_values(url)
    if bool(input_path) == bool(urls):
        raise ValueError("provide exactly one of input_path or url")

    if input_path:
        payloads = _payloads_from_path(input_path)
    else:
        payloads = []
        for item_url in urls:
            if source == "oddpool" and oddpool_quota_state_path is not None:
                reserve_oddpool_quota(
                    oddpool_quota_state_path,
                    item_url,
                    monthly_limit=oddpool_monthly_quota,
                    min_interval_seconds=oddpool_min_interval_seconds,
                )
            payloads.extend(_payloads_from_url(item_url, timeout, proxy, headers or {}))
    rows = [row for row in (_normalize_signal(payload, source) for payload in payloads) if row is not None]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    return len(rows)


def external_signal_report(path: Path) -> dict:
    rows = list(_read_external_signals(path))
    by_source = Counter(row.get("source") or "unknown" for row in rows)
    by_kind = Counter(row.get("kind") or "unknown" for row in rows)
    by_venue_pair = Counter(_venue_pair(row) for row in rows)
    return {
        "type": "external_signal_report",
        "path": str(path),
        "signal_count": len(rows),
        "by_source": _counter_rows(by_source, "source"),
        "by_kind": _counter_rows(by_kind, "kind"),
        "by_venue_pair": _counter_rows(by_venue_pair, "venue_pair"),
        "top": sorted(rows, key=_signal_sort_key)[:10],
    }


def polymarket_market_ids_from_external_signals(path: Path, limit: Optional[int] = None) -> list:
    if limit is not None and limit < 1:
        raise ValueError("limit must be at least 1")
    market_ids = []
    seen = set()
    rows = list(_read_external_signals(path))
    iterable = reversed(rows) if limit is not None else rows
    for row in iterable:
        for leg in row.get("legs", []):
            if str(leg.get("venue") or "").lower() != "polymarket":
                continue
            market_id = str(leg.get("market_id") or "").strip()
            if not market_id or market_id in seen:
                continue
            seen.add(market_id)
            market_ids.append(market_id)
            if limit is not None and len(market_ids) >= limit:
                return market_ids
    return market_ids


def _payloads_from_path(path: Path) -> list:
    text = path.read_text().strip()
    if not text:
        return []
    if text[0] in "[{":
        loaded = json.loads(text)
        return _payloads_from_loaded_json(loaded)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _payloads_from_url(url: str, timeout: float, proxy: Optional[str], headers: dict) -> list:
    request_headers = {"accept": "application/json", "user-agent": "poly-strategy/0.1"}
    request_headers.update(headers)
    request = Request(url, headers=request_headers)
    try:
        if proxy:
            proxy_url = _normalize_proxy(proxy)
            opener = build_opener(ProxyHandler({"http": proxy_url, "https": proxy_url}))
            response_context = opener.open(request, timeout=timeout)
        else:
            response_context = urlopen(request, timeout=timeout)
        with response_context as response:
            loaded = json.loads(response.read().decode("utf-8"))
    except URLError:
        raise
    return _payloads_from_loaded_json(loaded)


def _payloads_from_loaded_json(loaded) -> list:
    if isinstance(loaded, list):
        return loaded
    if isinstance(loaded, dict):
        for key in ["signals", "arbitrages", "arbs", "data", "results", "items", "opportunities"]:
            value = loaded.get(key)
            if isinstance(value, list):
                return value
        return [loaded]
    raise ValueError("external signal payload must be a JSON object or list")


def _normalize_signal(payload: dict, default_source: str) -> Optional[dict]:
    if not isinstance(payload, dict):
        return None
    payload = _normalize_oddpool_payload(payload) if default_source == "oddpool" else payload
    legs = _normalize_legs(payload)
    if not legs:
        return None

    source = str(payload.get("source") or default_source).strip()
    source_id = str(payload.get("source_id") or payload.get("id") or payload.get("signal_id") or _synthetic_source_id(payload))
    return {
        "type": "external_signal",
        "schema_version": 1,
        "ingested_at": _utc_now(),
        "source": source,
        "source_id": source_id,
        "ts": str(payload.get("ts") or payload.get("timestamp") or "").strip() or None,
        "kind": str(payload.get("kind") or payload.get("strategy") or payload.get("type") or "unknown"),
        "event_title": str(payload.get("event_title") or payload.get("event") or payload.get("title") or "").strip(),
        "quoted_edge": _optional_float(payload.get("quoted_edge") or payload.get("edge")),
        "quoted_roi": _optional_float(payload.get("quoted_roi") or payload.get("roi")),
        "quoted_depth": _optional_float(payload.get("quoted_depth") or payload.get("depth") or payload.get("size")),
        "legs": legs,
        "raw": payload,
    }


def _normalize_legs(payload: dict) -> list:
    raw_legs = payload.get("legs")
    if raw_legs is None:
        raw_legs = payload.get("markets")
    if raw_legs is None:
        raw_legs = payload.get("platforms")
    if not isinstance(raw_legs, list):
        raw_legs = _legs_from_flat_payload(payload)

    legs = []
    for index, leg in enumerate(raw_legs):
        if not isinstance(leg, dict):
            continue
        venue = str(leg.get("venue") or leg.get("platform") or "").strip().lower()
        market_id = str(leg.get("market_id") or leg.get("marketId") or leg.get("market") or leg.get("ticker") or "").strip()
        token = str(leg.get("token") or leg.get("outcome") or leg.get("side_token") or "").strip().upper()
        side = str(leg.get("side") or leg.get("action") or "buy").strip().lower()
        if not venue or not market_id:
            continue
        legs.append(
            {
                "venue": venue,
                "market_id": market_id,
                "token": token or None,
                "side": side,
                "price": _optional_float(leg.get("price") or leg.get("ask") or leg.get("best_ask")),
                "size": _optional_float(leg.get("size") or leg.get("depth") or leg.get("quantity")),
                "leg_index": index,
            }
        )
    return legs


def _legs_from_flat_payload(payload: dict) -> list:
    first_market = payload.get("market_a_id") or payload.get("polymarket_market_id")
    second_market = payload.get("market_b_id") or payload.get("kalshi_market_id")
    first_venue = payload.get("venue_a") or ("polymarket" if payload.get("polymarket_market_id") else None)
    second_venue = payload.get("venue_b") or ("kalshi" if payload.get("kalshi_market_id") else None)
    legs = []
    if first_market:
        legs.append({"venue": first_venue, "market_id": first_market, "token": payload.get("token_a"), "side": "buy"})
    if second_market:
        legs.append({"venue": second_venue, "market_id": second_market, "token": payload.get("token_b"), "side": "buy"})
    return legs


def _normalize_oddpool_payload(payload: dict) -> dict:
    normalized = dict(payload)
    if _is_oddpool_search_market(payload):
        return _normalize_oddpool_search_market(payload, normalized)
    if _is_oddpool_search_event(payload):
        return _normalize_oddpool_search_event(payload, normalized)
    if "quoted_edge" not in normalized:
        for key in ["net_cents", "net_edge_cents", "profit_cents", "edge_cents"]:
            if key in payload:
                normalized["quoted_edge"] = _cents_to_dollars(payload.get(key))
                break
    if "quoted_depth" not in normalized:
        normalized["quoted_depth"] = payload.get("depth") or payload.get("available_size") or payload.get("max_size")
    if "legs" not in normalized:
        for key in ["legs", "markets", "platforms", "orders"]:
            value = payload.get(key)
            if isinstance(value, list):
                normalized["legs"] = value
                break
    if "legs" not in normalized:
        legs = _legs_from_oddpool_nested_arbitrage(payload)
        if legs:
            normalized["legs"] = legs
    return normalized


def _is_oddpool_search_market(payload: dict) -> bool:
    return bool(payload.get("market_id") or payload.get("marketId") or payload.get("ticker")) and bool(
        payload.get("exchange") or payload.get("platform")
    )


def _is_oddpool_search_event(payload: dict) -> bool:
    return bool(payload.get("event_id") or payload.get("eventId")) and bool(payload.get("exchange") or payload.get("platform"))


def _normalize_oddpool_search_market(payload: dict, normalized: dict) -> dict:
    market_id = str(payload.get("market_id") or payload.get("marketId") or payload.get("ticker") or "").strip()
    venue = str(payload.get("exchange") or payload.get("platform") or "").strip().lower()
    normalized.setdefault("source_id", market_id)
    normalized.setdefault("kind", "oddpool_search_market")
    normalized.setdefault("event_title", payload.get("event_title") or payload.get("event") or payload.get("question") or payload.get("title"))
    normalized.setdefault("quoted_depth", payload.get("liquidity") or payload.get("volume") or payload.get("volume_24h"))
    normalized["legs"] = [
        {
            "venue": venue,
            "market_id": market_id,
            "token": payload.get("outcome") or payload.get("side_token"),
            "side": "watch",
            "price": payload.get("last_yes_price") or payload.get("yes_price") or payload.get("price"),
            "size": payload.get("liquidity") or payload.get("volume"),
        }
    ]
    return normalized


def _normalize_oddpool_search_event(payload: dict, normalized: dict) -> dict:
    event_id = str(payload.get("event_id") or payload.get("eventId") or "").strip()
    venue = str(payload.get("exchange") or payload.get("platform") or "").strip().lower()
    normalized.setdefault("source_id", event_id)
    normalized.setdefault("kind", "oddpool_search_event")
    normalized.setdefault("event_title", payload.get("event_title") or payload.get("title") or payload.get("name"))
    normalized.setdefault("quoted_depth", payload.get("liquidity") or payload.get("volume") or payload.get("volume_24h"))
    normalized["legs"] = [
        {
            "venue": venue,
            "market_id": event_id,
            "token": None,
            "side": "watch",
            "price": None,
            "size": payload.get("liquidity") or payload.get("volume"),
        }
    ]
    return normalized


def _legs_from_oddpool_nested_arbitrage(payload: dict) -> list:
    legs = []
    for venue in ["polymarket", "kalshi"]:
        raw = payload.get(venue)
        if not isinstance(raw, dict):
            continue
        market_id = raw.get("market_id") or raw.get("marketId") or raw.get("ticker")
        if not market_id:
            continue
        token = raw.get("outcome") or raw.get("side_token") or raw.get("side")
        price = raw.get("price") or raw.get("ask") or raw.get("best_ask") or raw.get("yes_ask") or raw.get("no_ask")
        legs.append(
            {
                "venue": venue,
                "market_id": market_id,
                "token": token,
                "side": raw.get("action") or "buy",
                "price": price,
                "size": raw.get("size") or raw.get("depth") or raw.get("quantity"),
            }
        )
    return legs


def _cents_to_dollars(value) -> Optional[float]:
    parsed = _optional_float(value)
    if parsed is None:
        return None
    return parsed / 100.0


def _read_external_signals(path: Path) -> Iterable[dict]:
    with path.open() as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("type") == "external_signal":
                yield row


def _venue_pair(row: dict) -> str:
    venues = sorted({str(leg.get("venue") or "unknown") for leg in row.get("legs", [])})
    return "+".join(venues) if venues else "unknown"


def _signal_sort_key(row: dict) -> tuple:
    return (
        -float(row.get("quoted_edge") or 0.0),
        -float(row.get("quoted_roi") or 0.0),
        row.get("source") or "",
        row.get("source_id") or "",
    )


def _counter_rows(counter: Counter, key: str) -> list:
    return [{key: name, "count": count} for name, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))]


def _synthetic_source_id(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _optional_float(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_proxy(proxy: str) -> str:
    if "://" in proxy:
        return proxy
    return f"http://{proxy}"


def _url_values(url) -> list:
    if url is None or url == "":
        return []
    if isinstance(url, (list, tuple)):
        return [str(item).strip() for item in url if str(item).strip()]
    return [str(url).strip()]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
