import json
import tempfile
import unittest
from pathlib import Path

from poly_strategy.watchlist import build_polymarket_watchlist, write_watchlist


class WatchlistTests(unittest.TestCase):
    def test_build_polymarket_watchlist_expands_neg_risk_group_tokens(self):
        gamma_rows = [
            _gamma_row("a", "group-1", ["a-yes", "a-no"], "0", liquidity=10),
            _gamma_row("b", "group-1", ["b-yes", "b-no"], "1", liquidity=10),
            _gamma_row("unused", "group-2", ["unused-yes", "unused-no"], "0", liquidity=10),
        ]
        rules = {"mutually_exclusive": [{"first": "a", "second": "a"}]}

        with tempfile.TemporaryDirectory() as tmp:
            gamma_path = Path(tmp) / "gamma.ndjson"
            rules_path = Path(tmp) / "rules.json"
            out = Path(tmp) / "watchlist.json"
            gamma_path.write_text("\n".join(json.dumps(row) for row in gamma_rows) + "\n")
            rules_path.write_text(json.dumps(rules))

            rows = build_polymarket_watchlist(gamma_path, rules_path)
            count = write_watchlist(rows, out)
            written = json.loads(out.read_text())

        self.assertEqual(count, 2)
        self.assertEqual([row["market_id"] for row in rows], ["a", "b"])
        self.assertEqual(rows[0]["yes_token_id"], "a-yes")
        self.assertEqual(rows[0]["fee_rate"], 0.03)
        self.assertIn("rule", rows[0]["priority_reasons"])
        self.assertEqual(written["type"], "polymarket_watchlist")
        self.assertEqual(len(written["markets"]), 2)

    def test_build_polymarket_watchlist_can_add_top_liquid_and_neg_risk_markets(self):
        gamma_rows = [
            _gamma_row("rule", "", ["rule-yes", "rule-no"], "", liquidity=1, volume24hr=1),
            _gamma_row("top", "", ["top-yes", "top-no"], "", liquidity=100, volume24hr=50),
            _gamma_row("group-a", "group", ["ga-yes", "ga-no"], "1", liquidity=30, volume24hr=20),
            _gamma_row("group-b", "group", ["gb-yes", "gb-no"], "2", liquidity=30, volume24hr=20),
            _gamma_row("low", "", ["low-yes", "low-no"], "", liquidity=0, volume24hr=0),
        ]
        rules = {"mutually_exclusive": [{"first": "rule", "second": "rule"}]}

        with tempfile.TemporaryDirectory() as tmp:
            gamma_path = Path(tmp) / "gamma.ndjson"
            rules_path = Path(tmp) / "rules.json"
            gamma_path.write_text("\n".join(json.dumps(row) for row in gamma_rows) + "\n")
            rules_path.write_text(json.dumps(rules))

            rows = build_polymarket_watchlist(
                gamma_path,
                rules_path,
                include_top_markets=1,
                include_top_neg_risk_groups=1,
                min_liquidity=1,
                max_markets=4,
            )

        market_ids = {row["market_id"] for row in rows}
        self.assertEqual(market_ids, {"rule", "top", "group-a", "group-b"})
        top = next(row for row in rows if row["market_id"] == "top")
        self.assertIn("top_liquidity", top["priority_reasons"])

    def test_build_polymarket_watchlist_accepts_two_non_yes_no_outcomes(self):
        gamma_rows = [
            _gamma_row("up-down", "", ["up-token", "down-token"], "", liquidity=100, volume24hr=50, outcomes=["Up", "Down"])
        ]
        rules = {"mutually_exclusive": []}

        with tempfile.TemporaryDirectory() as tmp:
            gamma_path = Path(tmp) / "gamma.ndjson"
            rules_path = Path(tmp) / "rules.json"
            gamma_path.write_text("\n".join(json.dumps(row) for row in gamma_rows) + "\n")
            rules_path.write_text(json.dumps(rules))

            rows = build_polymarket_watchlist(gamma_path, rules_path, include_top_markets=1)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["market_id"], "up-down")
        self.assertEqual(rows[0]["yes_token_id"], "up-token")
        self.assertEqual(rows[0]["no_token_id"], "down-token")

    def test_build_polymarket_watchlist_keeps_neg_risk_groups_atomic_under_cap(self):
        gamma_rows = [
            _gamma_row("group-a", "group", ["ga-yes", "ga-no"], "1", liquidity=1, volume24hr=1),
            _gamma_row("group-b", "group", ["gb-yes", "gb-no"], "2", liquidity=1, volume24hr=1),
            _gamma_row("solo", "", ["solo-yes", "solo-no"], "", liquidity=500, volume24hr=100),
        ]
        rules = {"mutually_exclusive": [{"first": "group-a", "second": "group-a"}]}

        with tempfile.TemporaryDirectory() as tmp:
            gamma_path = Path(tmp) / "gamma.ndjson"
            rules_path = Path(tmp) / "rules.json"
            gamma_path.write_text("\n".join(json.dumps(row) for row in gamma_rows) + "\n")
            rules_path.write_text(json.dumps(rules))

            rows = build_polymarket_watchlist(
                gamma_path,
                rules_path,
                include_top_markets=1,
                max_markets=2,
            )

        self.assertEqual({row["market_id"] for row in rows}, {"group-a", "group-b"})

    def test_build_polymarket_watchlist_boosts_external_signal_markets(self):
        gamma_rows = [
            _gamma_row("signal", "", ["signal-yes", "signal-no"], "", liquidity=0, volume24hr=0),
            _gamma_row("ignored", "", ["ignored-yes", "ignored-no"], "", liquidity=0, volume24hr=0),
        ]
        rules = {"mutually_exclusive": []}

        with tempfile.TemporaryDirectory() as tmp:
            gamma_path = Path(tmp) / "gamma.ndjson"
            rules_path = Path(tmp) / "rules.json"
            signals_path = Path(tmp) / "signals.ndjson"
            gamma_path.write_text("\n".join(json.dumps(row) for row in gamma_rows) + "\n")
            rules_path.write_text(json.dumps(rules))
            signals_path.write_text(
                json.dumps(
                    {
                        "type": "external_signal",
                        "quoted_edge": 0.05,
                        "legs": [{"venue": "polymarket", "market_id": "signal"}],
                    }
                )
                + "\n"
            )

            rows = build_polymarket_watchlist(gamma_path, rules_path, external_signals_path=signals_path)

        self.assertEqual([row["market_id"] for row in rows], ["signal"])
        self.assertIn("external_signal", rows[0]["priority_reasons"])

    def test_build_polymarket_watchlist_maps_external_condition_id_to_gamma_id(self):
        gamma_rows = [
            _gamma_row(
                "numeric-signal",
                "",
                ["signal-yes", "signal-no"],
                "",
                condition_id="0xsignal",
            ),
        ]
        rules = {"mutually_exclusive": []}

        with tempfile.TemporaryDirectory() as tmp:
            gamma_path = Path(tmp) / "gamma.ndjson"
            rules_path = Path(tmp) / "rules.json"
            signals_path = Path(tmp) / "signals.ndjson"
            gamma_path.write_text("\n".join(json.dumps(row) for row in gamma_rows) + "\n")
            rules_path.write_text(json.dumps(rules))
            signals_path.write_text(
                json.dumps(
                    {
                        "type": "external_signal",
                        "quoted_edge": 0.05,
                        "legs": [{"venue": "polymarket", "market_id": "0xsignal"}],
                    }
                )
                + "\n"
            )

            rows = build_polymarket_watchlist(gamma_path, rules_path, external_signals_path=signals_path)

        self.assertEqual([row["market_id"] for row in rows], ["numeric-signal"])
        self.assertIn("external_signal", rows[0]["priority_reasons"])

    def test_build_polymarket_watchlist_keeps_external_signals_under_cap(self):
        gamma_rows = [
            _gamma_row("group-a", "group", ["ga-yes", "ga-no"], "1", liquidity=1000, volume24hr=1000),
            _gamma_row("group-b", "group", ["gb-yes", "gb-no"], "2", liquidity=1000, volume24hr=1000),
            _gamma_row("signal", "", ["signal-yes", "signal-no"], "", liquidity=0, volume24hr=0),
        ]
        rules = {"mutually_exclusive": [{"first": "group-a", "second": "group-a"}]}

        with tempfile.TemporaryDirectory() as tmp:
            gamma_path = Path(tmp) / "gamma.ndjson"
            rules_path = Path(tmp) / "rules.json"
            signals_path = Path(tmp) / "signals.ndjson"
            gamma_path.write_text("\n".join(json.dumps(row) for row in gamma_rows) + "\n")
            rules_path.write_text(json.dumps(rules))
            signals_path.write_text(
                json.dumps(
                    {
                        "type": "external_signal",
                        "legs": [{"venue": "polymarket", "market_id": "signal"}],
                    }
                )
                + "\n"
            )

            rows = build_polymarket_watchlist(
                gamma_path,
                rules_path,
                external_signals_path=signals_path,
                max_markets=2,
            )

        self.assertIn("signal", {row["market_id"] for row in rows})
        signal = next(row for row in rows if row["market_id"] == "signal")
        self.assertIn("external_signal", signal["priority_reasons"])

    def test_build_polymarket_watchlist_cap_prefers_latest_external_signal(self):
        gamma_rows = [
            _gamma_row("old-signal", "", ["old-yes", "old-no"], "", liquidity=0, volume24hr=0),
            _gamma_row("new-signal", "", ["new-yes", "new-no"], "", liquidity=0, volume24hr=0),
            _gamma_row("top", "", ["top-yes", "top-no"], "", liquidity=1000, volume24hr=1000),
        ]
        rules = {"mutually_exclusive": []}
        old_signal = {
            "type": "external_signal",
            "legs": [{"venue": "polymarket", "market_id": "old-signal"}],
        }
        new_signal = {
            "type": "external_signal",
            "legs": [{"venue": "polymarket", "market_id": "new-signal"}],
        }

        with tempfile.TemporaryDirectory() as tmp:
            gamma_path = Path(tmp) / "gamma.ndjson"
            rules_path = Path(tmp) / "rules.json"
            signals_path = Path(tmp) / "signals.ndjson"
            gamma_path.write_text("\n".join(json.dumps(row) for row in gamma_rows) + "\n")
            rules_path.write_text(json.dumps(rules))
            signals_path.write_text("\n".join(json.dumps(row) for row in [old_signal, old_signal, old_signal, new_signal]) + "\n")

            rows = build_polymarket_watchlist(
                gamma_path,
                rules_path,
                external_signals_path=signals_path,
                include_top_markets=1,
                max_markets=1,
            )

        self.assertIn("new-signal", {row["market_id"] for row in rows})
        self.assertNotIn("old-signal", {row["market_id"] for row in rows})

    def test_build_polymarket_watchlist_keeps_external_signal_neg_risk_group_atomic(self):
        gamma_rows = [
            _gamma_row("group-a", "group", ["ga-yes", "ga-no"], "1", liquidity=100, volume24hr=10),
            _gamma_row("group-b", "group", ["gb-yes", "gb-no"], "2", liquidity=100, volume24hr=10),
            _gamma_row("solo", "", ["solo-yes", "solo-no"], "", liquidity=1000, volume24hr=1000),
        ]
        rules = {"mutually_exclusive": []}

        with tempfile.TemporaryDirectory() as tmp:
            gamma_path = Path(tmp) / "gamma.ndjson"
            rules_path = Path(tmp) / "rules.json"
            signals_path = Path(tmp) / "signals.ndjson"
            gamma_path.write_text("\n".join(json.dumps(row) for row in gamma_rows) + "\n")
            rules_path.write_text(json.dumps(rules))
            signals_path.write_text(
                json.dumps(
                    {
                        "type": "external_signal",
                        "legs": [{"venue": "polymarket", "market_id": "group-a"}],
                    }
                )
                + "\n"
            )

            rows = build_polymarket_watchlist(
                gamma_path,
                rules_path,
                external_signals_path=signals_path,
                max_markets=2,
            )

        self.assertEqual({row["market_id"] for row in rows}, {"group-a", "group-b"})
        group_a = next(row for row in rows if row["market_id"] == "group-a")
        self.assertIn("external_signal", group_a["priority_reasons"])


def _gamma_row(
    market_id: str,
    group_id: str,
    token_ids: list,
    threshold: str,
    liquidity: float = 0.0,
    volume24hr: float = 0.0,
    condition_id: str = "",
    outcomes: list = None,
):
    return {
        "type": "raw_polymarket_gamma_market",
        "market_id": market_id,
        "raw": {
            "id": market_id,
            "conditionId": condition_id or None,
            "question": f"{market_id} wins?",
            "active": True,
            "closed": False,
            "acceptingOrders": True,
            "enableOrderBook": True,
            "outcomes": json.dumps(outcomes or ["Yes", "No"]),
            "negRisk": bool(group_id),
            "negRiskMarketID": group_id or None,
            "groupItemTitle": market_id.upper(),
            "groupItemThreshold": threshold,
            "clobTokenIds": json.dumps(token_ids),
            "feesEnabled": True,
            "feeSchedule": {"rate": 0.03},
            "liquidityNum": liquidity,
            "volume24hr": volume24hr,
        },
    }


if __name__ == "__main__":
    unittest.main()
