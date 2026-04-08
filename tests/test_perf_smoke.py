import os
import sys
import unittest
from pathlib import Path

# Ensure project root on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.perf_smoke import run_smoke


class PerfSmokeTest(unittest.TestCase):
    def test_smoke_returns_stats(self):
        """Verify perf_smoke returns structured stats without raising."""
        result = run_smoke(samples=2)  # small to keep fast on weak CPU
        self.assertIn("stats", result)
        self.assertGreaterEqual(len(result["stats"]), 1)
        for item in result["stats"]:
            self.assertIn("name", item)
            self.assertIn("count", item)
        self.assertIn("cache_stats", result)


if __name__ == "__main__":
    unittest.main()
