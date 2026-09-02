"""Draw pass candidates for hand labelling from the published run.

The judge-selection set is 92 fail to 8 pass. A judge cannot be measured on
the pass side with 8 rows, and the pass side is the one a compliance gate
cares about. This script builds a queue of replies for two people to label.

Where the candidates come from, and why:

- `results/model_outputs.csv`, the replies real models wrote in pass 2. They
  have the length and style the judge will meet in production. Hand-written
  or model-written replies made for the meta-eval set do not (see ERRATA, the
  120 GLM rows).
- Only replies the judge marked `pass` on its own. A row the deterministic
  gate decided is the same for every candidate judge, so it measures nothing.
- No reply written by a model on the candidate-judge list in
  `select_judge.sh`, or by the same weights served elsewhere. A judge must
  not be scored on its own prose.
- One reply per (category, jurisdiction) cell, so no category supplies most
  of the pass class. The run used `permissions=none` throughout, so the
  draw cannot stratify on permissions.
- A share of judged-fail decoys, shuffled in, so a labeller cannot assume
  that every row in the queue is a pass.

The judge's verdict is a sampling hint, never a label. It goes into a
separate hints file that labellers must not open. The candidates file holds
no verdict and no model name.

Usage:
    python3 harness/pipeline/draw_pass_candidates.py
    python3 harness/pipeline/draw_pass_candidates.py --passes 60 --decoys 15 --seed 0
    # a second batch that skips the first and numbers on from it
    python3 harness/pipeline/draw_pass_candidates.py --passes 60 --decoys 0 --seed 1 \
        --exclude-hints harness/pipeline/pass-candidates-hints.csv \
        --out harness/pipeline/pass-candidates-2.csv --hints harness/pipeline/pass-candidates-hints-2.csv

Then label with:
    python3 harness/pipeline/label_rows.py --labeller <you> \
        --dataset harness/pipeline/pass-candidates.csv
"""

from __future__ import annotations

import argparse
import csv
import random
import re
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUTPUTS = REPO / "results" / "model_outputs.csv"
META_EVAL = REPO / "datasets" / "meta-eval.csv"
SELECT_JUDGE = REPO / "harness" / "pipeline" / "select_judge.sh"
CANDIDATES_OUT = REPO / "harness" / "pipeline" / "pass-candidates.csv"
HINTS_OUT = REPO / "harness" / "pipeline" / "pass-candidates-hints.csv"

META_FIELDS = [
    "item_id", "jurisdiction", "category", "rule_id", "system_prompt",
    "permissions", "prompt_variant", "probe", "reply", "notes",
]
HINT_FIELDS = ["item_id", "source_item_id", "source_model", "source_provider", "judge_verdict"]

# The same weights as a candidate judge, served through another provider.
# `select_judge.sh` names the Bedrock route; the run also holds the Ollama one.
SAME_WEIGHTS = {"mistral-large-3:675b"}

NOTE = (
    "Candidate for hand labelling, drawn from results/model_outputs.csv by "
    "draw_pass_candidates.py. Label blind: the judge's verdict is not a label."
)


def candidate_judges(script: Path) -> set[str]:
    """Model names on the candidate list, without the provider prefix."""
    names = set()
    for match in re.finditer(r'^\s*"(bedrock|ollama):([^"]+)"', script.read_text(), re.M):
        names.add(match.group(2))
    return names | SAME_WEIGHTS


def eligible(rows: list[dict], excluded_models: set[str], verdict: str) -> list[dict]:
    """Rows the draw may use: judge-decided, non-empty, not by an excluded model."""
    return [
        r for r in rows
        if r["final_verdict"] == verdict
        and r["decided_by"] == "judge"
        and r["reply"].strip()
        and r["model"] not in excluded_models
    ]


def draw(rows: list[dict], count: int, rng: random.Random) -> list[dict]:
    """One row per (category, jurisdiction) cell, cells in random order.

    Models rotate: a cell prefers a model the draw has used least, so no one
    model supplies most of the queue. When `count` exceeds the number of cells
    the draw goes round the cells again with different rows.
    """
    cells: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        cells[(r["category"], r["jurisdiction"])].append(r)
    keys = sorted(cells)
    rng.shuffle(keys)

    used_models: dict[str, int] = defaultdict(int)
    taken: set[tuple[str, str]] = set()
    picked: list[dict] = []
    while len(picked) < count and keys:
        progressed = False
        for key in keys:
            if len(picked) >= count:
                break
            pool = [r for r in cells[key] if (r["model"], r["item_id"]) not in taken]
            if not pool:
                continue
            rng.shuffle(pool)
            pool.sort(key=lambda r: used_models[r["model"]])
            row = pool[0]
            picked.append(row)
            taken.add((row["model"], row["item_id"]))
            used_models[row["model"]] += 1
            progressed = True
        if not progressed:
            break
    return picked


def to_meta_row(row: dict, item_id: int, meta: dict[str, dict]) -> dict:
    """Shape a run row like a meta-eval row, taking the recorded prompt from the dataset."""
    source = meta[row["item_id"]]
    return {
        "item_id": f"{item_id:03d}",
        "jurisdiction": row["jurisdiction"],
        "category": row["category"],
        "rule_id": row["rule_id"] or source["rule_id"],
        "system_prompt": source["system_prompt"],
        # The run graded every reply under a `--permissions none` override, but the
        # model saw the source row's system prompt. The row records what the model
        # saw, so the permissions column agrees with the prompt (tests enforce it).
        "permissions": source["permissions"],
        "prompt_variant": source["prompt_variant"],
        "probe": row["probe"],
        "reply": row["reply"],
        "notes": NOTE,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--passes", type=int, default=60, help="Judged-pass rows to draw. Default 60, one per cell.")
    parser.add_argument("--decoys", type=int, default=15, help="Judged-fail rows to mix in. Default 15.")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--outputs", default=str(OUTPUTS))
    parser.add_argument("--meta-eval", default=str(META_EVAL))
    parser.add_argument("--out", default=str(CANDIDATES_OUT))
    parser.add_argument("--hints", default=str(HINTS_OUT))
    parser.add_argument(
        "--exclude-hints", action="append", default=[],
        help="Hints file from an earlier draw. Its rows are skipped and item_ids continue after its last.",
    )
    args = parser.parse_args()

    rng = random.Random(args.seed)
    with open(args.outputs, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    with open(args.meta_eval, newline="", encoding="utf-8") as fh:
        meta_rows = list(csv.DictReader(fh))
    meta = {r["item_id"]: r for r in meta_rows}
    next_id = max(int(r["item_id"]) for r in meta_rows) + 1

    excluded = candidate_judges(SELECT_JUDGE)
    drawn_before: set[tuple[str, str]] = set()
    for path in args.exclude_hints:
        with open(path, newline="", encoding="utf-8") as fh:
            for h in csv.DictReader(fh):
                drawn_before.add((h["source_model"], h["source_item_id"]))
                next_id = max(next_id, int(h["item_id"]) + 1)
    rows = [r for r in rows if (r["model"], r["item_id"]) not in drawn_before]
    passes = draw(eligible(rows, excluded, "pass"), args.passes, rng)
    decoys = draw(eligible(rows, excluded, "fail"), args.decoys, rng)

    queue = passes + decoys
    rng.shuffle(queue)

    out_rows, hint_rows = [], []
    for offset, row in enumerate(queue):
        item_id = next_id + offset
        out_rows.append(to_meta_row(row, item_id, meta))
        hint_rows.append({
            "item_id": f"{item_id:03d}",
            "source_item_id": row["item_id"],
            "source_model": row["model"],
            "source_provider": row["provider"],
            "judge_verdict": row["final_verdict"],
        })

    for path, fields, data in ((args.out, META_FIELDS, out_rows), (args.hints, HINT_FIELDS, hint_rows)):
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(data)

    cells = {(r["category"], r["jurisdiction"]) for r in passes}
    models = {r["model"] for r in queue}
    print(f"{len(passes)} judged-pass rows over {len(cells)} (category, jurisdiction) cells, "
          f"{len(decoys)} judged-fail decoys, {len(models)} source models.")
    print(f"Excluded {len(excluded)} candidate-judge models.")
    print(f"Queue: {args.out}  (item_id {next_id:03d}-{next_id + len(queue) - 1:03d})")
    print(f"Hints: {args.hints}  (do not open while labelling)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
