import unittest
from pathlib import Path


class BackgroundManagerScriptTests(unittest.TestCase):
    def test_external_signal_refresh_restarts_monitor_when_watchlist_changes(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "scripts" / "background_manager.sh").read_text()
        block = text.split('if [[ "$ENABLE_EXTERNAL_SIGNALS" == "1"')[1].split(
            'if [[ "$ENABLE_DISCOVERY_REFRESH" == "1"'
        )[0]

        self.assertIn('before_sig="$(file_sig "$WATCHLIST")"', block)
        self.assertIn('after_sig="$(file_sig "$WATCHLIST")"', block)
        self.assertIn('if [[ "$before_sig" != "$after_sig" ]]', block)
        self.assertIn("restart_monitor", block)


if __name__ == "__main__":
    unittest.main()
