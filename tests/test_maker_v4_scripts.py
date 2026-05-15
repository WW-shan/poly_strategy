import importlib.util
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


def _load_simulate_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "simulate_maker_basket_v4.py"
    spec = importlib.util.spec_from_file_location("simulate_maker_basket_v4", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_probe_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "probe_cross_platform.py"
    spec = importlib.util.spec_from_file_location("probe_cross_platform", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class MakerV4ScriptTests(unittest.TestCase):
    def test_window_date_label_uses_configured_end_date_not_real_now(self):
        module = _load_simulate_module()
        window_end = datetime(2026, 4, 3, tzinfo=timezone.utc)
        cutoff_ts = int(datetime(2026, 3, 20, tzinfo=timezone.utc).timestamp())

        self.assertEqual(module.window_date_label(cutoff_ts, window_end), "2026-03-20 -> 2026-04-03")

    def test_default_window_end_uses_utc_midnight(self):
        module = _load_simulate_module()
        now = datetime(2026, 5, 15, 6, 45, tzinfo=timezone.utc)

        self.assertEqual(module.default_window_end(now), datetime(2026, 5, 15, tzinfo=timezone.utc))

    def test_cohort_builder_fee_filter_can_be_disabled(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, str(root / "scripts" / "build_negrisk_cohort.py"), "--help"],
            capture_output=True,
            text=True,
            check=True,
        )

        self.assertIn("--no-require-fees-enabled", result.stdout)

    def test_kalshi_top_ask_uses_opposite_side_bid(self):
        module = _load_probe_module()
        orderbook = {
            "orderbook_fp": {
                "yes_dollars": [["0.20", "10"], ["0.26", "5"]],
                "no_dollars": [["0.40", "7"], ["0.57", "3"]],
            }
        }

        self.assertEqual(module.kalshi_top_ask(orderbook, "yes"), 0.43)
        self.assertEqual(module.kalshi_top_ask(orderbook, "no"), 0.74)


if __name__ == "__main__":
    unittest.main()
