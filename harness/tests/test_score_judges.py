"""The judge scorer's bootstrap intervals. No model, no network."""

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "pipeline" / "score_judges.py"
spec = importlib.util.spec_from_file_location("score_judges", SCRIPT)
sj = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sj)


def pairs(tp, tn, fp, fn):
    return (
        [("fail", "fail")] * tp + [("pass", "pass")] * tn
        + [("pass", "fail")] * fp + [("fail", "pass")] * fn
    )


class BootstrapTest(unittest.TestCase):
    def test_interval_brackets_the_point_estimate(self):
        p = pairs(tp=87, tn=5, fp=3, fn=2)
        point = sj.score(p)
        interval = sj.bootstrap(p, draws=500, seed=1)
        for metric in sj.INTERVAL_METRICS:
            self.assertLessEqual(interval[f"{metric}_lo"], point[metric])
            self.assertGreaterEqual(interval[f"{metric}_hi"], point[metric])

    def test_a_small_pass_class_gives_a_wide_interval(self):
        interval = sj.bootstrap(pairs(tp=87, tn=5, fp=3, fn=2), draws=500, seed=1)
        self.assertGreater(interval["macro_f1_hi"] - interval["macro_f1_lo"], 0.2)

    def test_the_always_fail_baseline_has_a_narrow_interval(self):
        p = [(h, "fail") for h in ["fail"] * 92 + ["pass"] * 8]
        interval = sj.bootstrap(p, draws=500, seed=1)
        self.assertLess(interval["macro_f1_hi"] - interval["macro_f1_lo"], 0.05)
        self.assertEqual(interval["balanced_accuracy_lo"], 0.5)
        self.assertEqual(interval["balanced_accuracy_hi"], 0.5)

    def test_the_same_seed_gives_the_same_interval(self):
        p = pairs(tp=85, tn=6, fp=2, fn=7)
        self.assertEqual(sj.bootstrap(p, 300, seed=7), sj.bootstrap(p, 300, seed=7))

    def test_zero_draws_gives_no_interval(self):
        self.assertEqual(sj.bootstrap(pairs(1, 1, 0, 0), 0, seed=0), {})


class OverlapTest(unittest.TestCase):
    def test_overlapping_and_separated_intervals(self):
        a = {"macro_f1_lo": 0.63, "macro_f1_hi": 0.95}
        b = {"macro_f1_lo": 0.60, "macro_f1_hi": 0.89}
        c = {"macro_f1_lo": 0.40, "macro_f1_hi": 0.50}
        self.assertTrue(sj.intervals_overlap(a, b))
        self.assertFalse(sj.intervals_overlap(a, c))


if __name__ == "__main__":
    unittest.main()
