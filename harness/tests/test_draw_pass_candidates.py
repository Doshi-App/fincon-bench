"""The pass-candidate draw. No model, no network."""

import importlib.util
import random
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "pipeline" / "draw_pass_candidates.py"
spec = importlib.util.spec_from_file_location("draw_pass_candidates", SCRIPT)
draw_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(draw_mod)


def row(model, item_id, category, jurisdiction, verdict="pass", decided_by="judge", reply="A reply."):
    return {
        "model": model,
        "provider": "test",
        "item_id": item_id,
        "category": category,
        "jurisdiction": jurisdiction,
        "final_verdict": verdict,
        "decided_by": decided_by,
        "reply": reply,
    }


class EligibleTest(unittest.TestCase):
    def test_excludes_candidate_judges_gate_rows_and_empty_replies(self):
        rows = [
            row("good-model", "001", "missing_caveat", "uk"),
            row("zai.glm-5", "001", "missing_caveat", "uk"),
            row("good-model", "002", "expired_figure", "uk", decided_by="gate"),
            row("good-model", "003", "missing_caveat", "eu", reply="   "),
            row("good-model", "004", "missing_caveat", "us", verdict="fail"),
        ]
        picked = draw_mod.eligible(rows, {"zai.glm-5"}, "pass")
        self.assertEqual([(r["model"], r["item_id"]) for r in picked], [("good-model", "001")])


class DrawTest(unittest.TestCase):
    def test_one_row_per_cell_and_models_rotate(self):
        rows = []
        for jurisdiction in ("uk", "eu", "us", "au"):
            for category in ("missing_caveat", "outcome_promise"):
                for model in ("m1", "m2", "m3"):
                    rows.append(row(model, f"{jurisdiction}-{category}", category, jurisdiction))
        picked = draw_mod.draw(rows, 8, random.Random(0))
        self.assertEqual(len(picked), 8)
        cells = {(r["category"], r["jurisdiction"]) for r in picked}
        self.assertEqual(len(cells), 8)
        per_model = {m: sum(1 for r in picked if r["model"] == m) for m in ("m1", "m2", "m3")}
        self.assertLessEqual(max(per_model.values()) - min(per_model.values()), 1)

    def test_stops_when_the_pool_runs_out(self):
        rows = [row("m1", "001", "missing_caveat", "uk"), row("m1", "002", "missing_caveat", "eu")]
        self.assertEqual(len(draw_mod.draw(rows, 10, random.Random(0))), 2)


class CandidateJudgesTest(unittest.TestCase):
    def test_reads_the_selection_script_and_adds_same_weights(self):
        names = draw_mod.candidate_judges(draw_mod.SELECT_JUDGE)
        self.assertIn("mistral.mistral-large-3-675b-instruct", names)
        self.assertIn("glm-5.2", names)
        self.assertIn("mistral-large-3:675b", names)


if __name__ == "__main__":
    unittest.main()
