"""The spread columns on the leaderboard (issue #30)."""

import importlib.util
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "build_outputs", Path(__file__).resolve().parents[1] / "pipeline" / "build_outputs.py"
)
build_outputs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_outputs)


def record(*verdicts):
    return {"repeats": [{"run_index": i, "final_verdict": v} for i, v in enumerate(verdicts)]}


class PassSpreadTest(unittest.TestCase):
    def test_mean_and_spread_across_pass_indices(self):
        # Pass 0: 2/2 pass. Pass 1: 1/2. Pass 2: 0/2. Mean 0.5, spread 1.0.
        rows = [record("pass", "pass", "fail"), record("pass", "fail", "fail")]
        out = build_outputs.pass_spread(rows)
        self.assertEqual(out["repeated_items"], 2)
        self.assertEqual(out["pass_rate_mean"], 0.5)
        self.assertEqual(out["pass_rate_spread"], 1.0)

    def test_repeated_items_that_all_errored_are_still_counted(self):
        out = build_outputs.pass_spread([record("error", "error"), record("error", "error")])
        self.assertEqual(out, {"repeated_items": 2, "pass_rate_mean": "", "pass_rate_spread": ""})

    def test_single_pass_rows_are_blank_not_zero(self):
        out = build_outputs.pass_spread([{"final_verdict": "pass"}, {"repeats": [{"run_index": 0, "final_verdict": "pass"}]}])
        self.assertEqual(out, {"repeated_items": 0, "pass_rate_mean": "", "pass_rate_spread": ""})

    def test_errors_and_ungraded_passes_do_not_count(self):
        rows = [record("pass", "error", "pass"), record("fail", "ungraded", "pass")]
        out = build_outputs.pass_spread(rows)
        # Pass 0: 1/2; pass 1: no verdicts, skipped; pass 2: 2/2.
        self.assertEqual(out["pass_rate_mean"], 0.75)
        self.assertEqual(out["pass_rate_spread"], 0.5)
