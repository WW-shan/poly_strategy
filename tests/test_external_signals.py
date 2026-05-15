import json
import tempfile
import unittest
from pathlib import Path

from poly_strategy.external_signals import (
    external_signal_report,
    ingest_external_signals,
    polymarket_market_ids_from_external_signals,
)
from poly_strategy.oddpool import OddpoolQuotaError, reserve_oddpool_quota


class ExternalSignalTests(unittest.TestCase):
    def test_ingest_external_signals_normalizes_json_payloads(self):
        payload = {
            "signals": [
                {
                    "id": "sig-1",
                    "strategy": "cross_platform",
                    "event": "Fed decision",
                    "edge": 0.05,
                    "roi": 0.08,
                    "legs": [
                        {"platform": "Polymarket", "marketId": "poly-1", "outcome": "YES", "ask": 0.45, "depth": 100},
                        {"platform": "Kalshi", "ticker": "kalshi-1", "outcome": "NO", "ask": 0.50, "depth": 90},
                    ],
                }
            ]
        }

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "signals.json"
            out = Path(tmp) / "external.ndjson"
            source.write_text(json.dumps(payload))

            count = ingest_external_signals(out, "oddpool", input_path=source)
            row = json.loads(out.read_text().splitlines()[0])

        self.assertEqual(count, 1)
        self.assertEqual(row["type"], "external_signal")
        self.assertEqual(row["source"], "oddpool")
        self.assertEqual(row["source_id"], "sig-1")
        self.assertEqual(row["kind"], "cross_platform")
        self.assertEqual(row["quoted_edge"], 0.05)
        self.assertEqual(row["legs"][0]["venue"], "polymarket")
        self.assertEqual(row["legs"][1]["market_id"], "kalshi-1")


    def test_ingest_external_signals_supports_oddpool_current_shape(self):
        payload = {
            "arbitrages": [
                {
                    "id": "arb-1",
                    "net_cents": 1.25,
                    "roi": 0.04,
                    "depth": 200,
                    "platforms": [
                        {"platform": "Polymarket", "market_id": "poly-1", "outcome": "YES", "best_ask": 0.48},
                        {"platform": "Kalshi", "ticker": "KXTEST", "outcome": "NO", "best_ask": 0.50},
                    ],
                }
            ]
        }

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "oddpool.json"
            out = Path(tmp) / "external.ndjson"
            source.write_text(json.dumps(payload))

            count = ingest_external_signals(out, "oddpool", input_path=source)
            row = json.loads(out.read_text().splitlines()[0])

        self.assertEqual(count, 1)
        self.assertEqual(row["source"], "oddpool")
        self.assertEqual(row["source_id"], "arb-1")
        self.assertEqual(row["quoted_edge"], 0.0125)
        self.assertEqual(row["quoted_depth"], 200)
        self.assertEqual([leg["venue"] for leg in row["legs"]], ["polymarket", "kalshi"])

    def test_ingest_external_signals_supports_oddpool_free_search_market_shape(self):
        payload = [
            {
                "exchange": "polymarket",
                "market_id": "pm-1",
                "question": "Will the Fed cut rates in June?",
                "event_title": "Fed decision",
                "liquidity": 123.45,
                "last_yes_price": 0.42,
            }
        ]

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "oddpool-search.json"
            out = Path(tmp) / "external.ndjson"
            source.write_text(json.dumps(payload))

            count = ingest_external_signals(out, "oddpool", input_path=source)
            row = json.loads(out.read_text().splitlines()[0])

        self.assertEqual(count, 1)
        self.assertEqual(row["source_id"], "pm-1")
        self.assertEqual(row["kind"], "oddpool_search_market")
        self.assertEqual(row["event_title"], "Fed decision")
        self.assertEqual(row["quoted_depth"], 123.45)
        self.assertEqual(row["legs"][0]["venue"], "polymarket")
        self.assertEqual(row["legs"][0]["market_id"], "pm-1")
        self.assertEqual(row["legs"][0]["side"], "watch")

    def test_ingest_external_signals_supports_oddpool_free_search_event_shape(self):
        payload = {
            "data": [
                {
                    "exchange": "kalshi",
                    "event_id": "evt-1",
                    "title": "Fed decision",
                    "volume": 500,
                }
            ]
        }

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "oddpool-events.json"
            out = Path(tmp) / "external.ndjson"
            source.write_text(json.dumps(payload))

            count = ingest_external_signals(out, "oddpool", input_path=source)
            row = json.loads(out.read_text().splitlines()[0])

        self.assertEqual(count, 1)
        self.assertEqual(row["source_id"], "evt-1")
        self.assertEqual(row["kind"], "oddpool_search_event")
        self.assertEqual(row["legs"][0]["venue"], "kalshi")
        self.assertEqual(row["legs"][0]["market_id"], "evt-1")

    def test_oddpool_quota_ledger_tracks_monthly_limit(self):
        from datetime import datetime, timezone

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "quota.json"
            first = reserve_oddpool_quota(
                state,
                "https://api.oddpool.com/search/recent/markets?limit=1",
                monthly_limit=1,
                min_interval_seconds=0,
                now=datetime(2026, 5, 9, 0, 0, tzinfo=timezone.utc),
                sleep_for_rate_limit=False,
            )

            with self.assertRaises(OddpoolQuotaError):
                reserve_oddpool_quota(
                    state,
                    "https://api.oddpool.com/search/recent/markets?limit=1",
                    monthly_limit=1,
                    min_interval_seconds=0,
                    now=datetime(2026, 5, 9, 0, 1, tzinfo=timezone.utc),
                    sleep_for_rate_limit=False,
                )

        self.assertEqual(first["used"], 1)
        self.assertEqual(first["remaining"], 0)

    def test_external_signal_report_summarizes_sources_and_venues(self):
        rows = [
            {
                "type": "external_signal",
                "source": "oddpool",
                "source_id": "a",
                "kind": "cross_platform",
                "quoted_edge": 0.04,
                "quoted_roi": 0.05,
                "legs": [{"venue": "polymarket"}, {"venue": "kalshi"}],
            },
            {
                "type": "external_signal",
                "source": "custom",
                "source_id": "b",
                "kind": "basket",
                "quoted_edge": 0.10,
                "legs": [{"venue": "polymarket"}],
            },
        ]

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "external.ndjson"
            path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

            report = external_signal_report(path)

        self.assertEqual(report["signal_count"], 2)
        self.assertEqual(report["by_source"][0]["source"], "custom")
        self.assertEqual(report["top"][0]["source_id"], "b")
        self.assertIn({"venue_pair": "kalshi+polymarket", "count": 1}, report["by_venue_pair"])

    def test_polymarket_market_ids_from_external_signals_dedupes_in_order(self):
        rows = [
            {
                "type": "external_signal",
                "legs": [
                    {"venue": "polymarket", "market_id": "pm-1"},
                    {"venue": "kalshi", "market_id": "kx-1"},
                ],
            },
            {"type": "external_signal", "legs": [{"venue": "polymarket", "market_id": "pm-1"}]},
            {"type": "external_signal", "legs": [{"venue": "Polymarket", "market_id": "pm-2"}]},
        ]

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "external.ndjson"
            path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

            market_ids = polymarket_market_ids_from_external_signals(path)

        self.assertEqual(market_ids, ["pm-1", "pm-2"])

    def test_polymarket_market_ids_from_external_signals_limit_prefers_latest_unique_ids(self):
        rows = [
            {"type": "external_signal", "legs": [{"venue": "polymarket", "market_id": "old-1"}]},
            {"type": "external_signal", "legs": [{"venue": "polymarket", "market_id": "old-2"}]},
            {"type": "external_signal", "legs": [{"venue": "polymarket", "market_id": "new-1"}]},
            {"type": "external_signal", "legs": [{"venue": "polymarket", "market_id": "old-1"}]},
            {"type": "external_signal", "legs": [{"venue": "polymarket", "market_id": "new-2"}]},
        ]

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "external.ndjson"
            path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

            market_ids = polymarket_market_ids_from_external_signals(path, limit=3)

        self.assertEqual(market_ids, ["new-2", "old-1", "new-1"])


if __name__ == "__main__":
    unittest.main()
