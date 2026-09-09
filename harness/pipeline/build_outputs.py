"""Turn the phase 2 transcripts into the three published CSVs.

- `results/model_outputs.csv` — one row per model per probe: what the model was
  asked, what it replied, and how the judge marked it. This is the wide record
  a person can read or re-grade.
- `results/leaderboard.csv` — one row per model: pass rate over the probes the
  judge actually decided, plus the per-axis split, and the mean and spread of
  the pass rate across repeat passes (`pass_rate_mean`, `pass_rate_spread`,
  over `repeated_items`; see `pass_spread`).
- `results/category_breakdown.csv` — one row per model per category (long
  format, so adding a category never means adding a column): the fail rate
  that category earned for that model. Backs the website's model-by-category
  matrix. Same merge rule as the leaderboard for the 3 cross-provider pairs.

Two honesty rules are enforced here rather than left to the reader.

- **Pass rate uses only decided items.** An item the judge errored on or left
  ungraded is counted in `ungraded`/`errors` and excluded from the denominator,
  so a model cannot climb by failing to be graded. `coverage` shows what share
  of its probes were decided — a low coverage makes the rate less trustworthy,
  and the column is there to say so.
- **A model that is also the judge is flagged.** The README says no assistant
  grades its own leaderboard row. Its row carries `self_graded=yes`. Under a
  two-judge run any of the three seats counts.

Under a two-judge run each output row also carries `judge_verdict` (judge A),
`judge2_verdict` (judge B), `tiebreak_verdict` (the third judge's answer on
the row's representative pass, or on its first contested pass; empty when no
pass was contested) and `tiebreak` (`yes` when any pass of the row needed the
third judge). `decided_by` is `tiebreak` when the representative pass itself
was contested; `judge_reasoning` and `quoted_text` are then the third judge's
words. `repeats` is the pass count behind the row and `tiebreak_passes` how
many of those passes were contested.
- **The same weights on 2 inference stacks are 1 leaderboard row, not 2.**
  `merge_cross_provider` folds each pair in `MERGE_GROUPS` — currently Mistral
  Large 3 675B and both GPT-OSS sizes — into 1 row, averaging every rate
  column and summing every count column. `results/model_outputs.csv` stays
  unmerged; only the leaderboard summary combines. See `MERGE_GROUPS` for why
  a different point release does not match and stays 2 rows.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

OUTPUT_FIELDS = [
    "model", "provider", "item_id", "jurisdiction", "category", "axis",
    "rule_id", "permissions", "threshold", "prompt_variant", "probe", "reply",
    "judge_verdict", "judge2_verdict", "tiebreak_verdict", "tiebreak",
    "final_verdict", "decided_by", "product_risk",
    "judge_reasoning", "quoted_text", "gate_verdict", "reply_tokens",
    "repeats", "tiebreak_passes",
]

LEADERBOARD_FIELDS = [
    "rank", "ranked", "model", "provider", "self_graded", "items", "decided", "passes",
    "fails", "arguable", "ungraded", "errors", "pass_rate", "fail_rate",
    "coverage", "behaviour_pass_rate", "compliance_pass_rate",
    "repeated_items", "pass_rate_mean", "pass_rate_spread",
    "avg_reply_tokens", "judge",
]

CATEGORY_FIELDS = [
    "model", "provider", "category", "axis", "items", "decided", "fails", "fail_rate",
]

# A model must have this share of its probes decided to earn a rank.
MIN_COVERAGE = 0.80

# Same weights, 2 inference stacks — these pairs fold into 1 leaderboard row.
# Keyed by the exact `provider:model` spec each side was run under, so a
# different point release (e.g. Minimax m2.5 on Bedrock vs m2.7 on Ollama)
# does not match and stays 2 separate rows; that is a different test, not the
# same model twice. See results/README.md for why the row is an average, not
# a pooled recount.
MERGE_GROUPS = {
    "mistral-large-3-675b-instruct": (
        "bedrock:mistral.mistral-large-3-675b-instruct",
        "ollama:mistral-large-3:675b",
    ),
    "gpt-oss-120b": (
        "bedrock:openai.gpt-oss-120b-1:0",
        "ollama:gpt-oss:120b",
    ),
    "gpt-oss-20b": (
        "bedrock:openai.gpt-oss-20b-1:0",
        "ollama:gpt-oss:20b",
    ),
}

# The behaviour axis is conduct toward the member; compliance is the rulebook.
# `axis_of` in the runner owns the mapping — this reads it rather than restating.


def load(path: Path) -> list[dict]:
    records = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def split_spec(assistant: str) -> tuple[str, str]:
    provider, _, model = assistant.partition(":")
    return (provider, model) if model else ("", assistant)


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def pass_spread(records: list[dict]) -> dict:
    """Mean and spread of the pass rate across repeat passes (issue #30).

    `pass_rate` on the leaderboard is the rate of majority verdicts. This
    looks one level down: for every pass index, the share of repeated items
    whose pass at that index was `pass`, over the items that have repeats and
    whose pass reached a verdict. `pass_rate_mean` averages those per-pass
    rates, `pass_rate_spread` is the highest minus the lowest, and
    `repeated_items` says how many items the numbers rest on. A model with no
    repeated item (one pass everywhere) gets blanks, not zeros.
    """
    by_index: dict[int, list[int]] = defaultdict(list)
    repeated = 0
    for record in records:
        runs = record.get("repeats") or []
        if len(runs) < 2:
            continue
        repeated += 1
        for run in runs:
            verdict = run.get("final_verdict")
            if verdict in ("pass", "fail", "arguable"):
                by_index[run.get("run_index", 0)].append(1 if verdict == "pass" else 0)
    rates = [sum(v) / len(v) for v in by_index.values() if v]
    if not rates:
        return {"repeated_items": 0, "pass_rate_mean": "", "pass_rate_spread": ""}
    return {
        "repeated_items": repeated,
        "pass_rate_mean": round(sum(rates) / len(rates), 4),
        "pass_rate_spread": round(max(rates) - min(rates), 4),
    }


def merge_cross_provider(board: list[dict]) -> list[dict]:
    """Fold each exact pair in `MERGE_GROUPS` into 1 row, averaged.

    Rate columns (`pass_rate`, `fail_rate`, `coverage`, the 2 axis rates,
    `avg_reply_tokens`) average the 2 providers' numbers 50/50. Count columns
    (`items`, `decided`, `passes`, ...) sum, since they describe how much ran,
    not how well it did. `self_graded` carries over if either side is the
    judge. A pair with only 1 side present (the other never ran, or errored
    out entirely) is left as its own unmerged row rather than merged with
    nothing.
    """
    by_key = {f"{row['provider']}:{row['model']}": row for row in board}
    consumed: set[str] = set()
    merged: list[dict] = []
    for name, members in MERGE_GROUPS.items():
        rows = [by_key[key] for key in members if key in by_key]
        if len(rows) < 2:
            continue
        consumed.update(members)
        behaviour = [float(r["behaviour_pass_rate"]) for r in rows if r["behaviour_pass_rate"] not in ("", None)]
        compliance = [float(r["compliance_pass_rate"]) for r in rows if r["compliance_pass_rate"] not in ("", None)]
        tokens = [r["avg_reply_tokens"] for r in rows if r["avg_reply_tokens"] not in ("", None)]
        merged.append({
            "model": name,
            "provider": "+".join(sorted({r["provider"] for r in rows})),
            "self_graded": "yes" if any(r["self_graded"] == "yes" for r in rows) else "no",
            "items": sum(r["items"] for r in rows),
            "decided": sum(r["decided"] for r in rows),
            "passes": sum(r["passes"] for r in rows),
            "fails": sum(r["fails"] for r in rows),
            "arguable": sum(r["arguable"] for r in rows),
            "ungraded": sum(r["ungraded"] for r in rows),
            "errors": sum(r["errors"] for r in rows),
            "pass_rate": _avg([r["pass_rate"] for r in rows if r["pass_rate"] is not None]),
            "fail_rate": _avg([r["fail_rate"] for r in rows if r["fail_rate"] is not None]),
            "coverage": _avg([r["coverage"] for r in rows if r["coverage"] is not None]) or 0.0,
            "behaviour_pass_rate": str(_avg(behaviour)) if behaviour else "",
            "compliance_pass_rate": str(_avg(compliance)) if compliance else "",
            "avg_reply_tokens": round(sum(tokens) / len(tokens)) if tokens else "",
            "repeated_items": sum(int(r.get("repeated_items") or 0) for r in rows),
            "pass_rate_mean": _avg([float(r["pass_rate_mean"]) for r in rows if r.get("pass_rate_mean") not in ("", None)]) or "",
            "pass_rate_spread": max([float(r["pass_rate_spread"]) for r in rows if r.get("pass_rate_spread") not in ("", None)], default=""),
            "judge": rows[0]["judge"],
        })
    survivors = [row for row in board if f"{row['provider']}:{row['model']}" not in consumed]
    return survivors + merged


def merge_cross_provider_categories(category_board: list[dict]) -> list[dict]:
    """Same rule as `merge_cross_provider`, 1 category at a time.

    `fail_rate` averages the 2 providers' rates 50/50; `items`/`decided`/
    `fails` sum. A category only 1 side of the pair ever saw stays on that
    side's row, unmerged, same as a pair with only 1 side present at all.
    """
    by_key: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in category_board:
        by_key[f"{row['provider']}:{row['model']}"][row["category"]] = row
    consumed: set[str] = set()
    merged: list[dict] = []
    for name, members in MERGE_GROUPS.items():
        present = [key for key in members if key in by_key]
        if len(present) < 2:
            continue
        consumed.update(members)
        categories = sorted({cat for key in present for cat in by_key[key]})
        for cat in categories:
            rows = [by_key[key][cat] for key in present if cat in by_key[key]]
            rates = [r["fail_rate"] for r in rows if r["fail_rate"] is not None]
            merged.append({
                "model": name,
                "provider": "+".join(sorted({r["provider"] for r in rows})),
                "category": cat,
                "axis": rows[0]["axis"],
                "items": sum(r["items"] for r in rows),
                "decided": sum(r["decided"] for r in rows),
                "fails": sum(r["fails"] for r in rows),
                "fail_rate": _avg(rates),
            })
    survivors = [row for row in category_board if f"{row['provider']}:{row['model']}" not in consumed]
    return survivors + merged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcript", nargs="+")
    parser.add_argument("--judge", default="", help="The judge spec, to flag self-grading.")
    parser.add_argument("--judge2", default="", help="The second judge spec, if any. Also flags self-grading.")
    parser.add_argument("--tiebreak", default="", help="The tiebreak judge spec, if any. Also flags self-grading.")
    parser.add_argument("--outputs", default="results/model_outputs.csv")
    parser.add_argument("--leaderboard", default="results/leaderboard.csv")
    parser.add_argument("--categories", default="results/category_breakdown.csv")
    args = parser.parse_args()

    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from fincon_runner.models import ALL_CATEGORIES, axis_of  # noqa: PLC0415

    judges = {spec for spec in (args.judge, args.judge2, args.tiebreak) if spec}
    judge_label = " + ".join(spec for spec in (args.judge, args.judge2) if spec)
    if args.tiebreak:
        judge_label += f", tiebreak {args.tiebreak}"

    rows: list[dict] = []
    per_model: dict[str, list[dict]] = defaultdict(list)
    records_by_model: dict[str, list[dict]] = defaultdict(list)

    for raw in args.transcript:
        path = Path(raw)
        for record in load(path):
            assistant = record.get("assistant", "") or path.parent.name
            provider, model = split_spec(assistant)
            item = record.get("item", {})
            judge = record.get("judge", {})
            judge2 = record.get("judge2") or {}
            tiebreak = record.get("tiebreak") or {}
            tiebreak_used = bool(record.get("tiebreak_used", False))
            decider = tiebreak if record.get("decided_by") == "tiebreak" and tiebreak else judge
            gate = record.get("gate", {})
            category = record.get("category", "")
            row = {
                "model": model,
                "provider": provider,
                "item_id": item.get("item_id", ""),
                "jurisdiction": record.get("jurisdiction", ""),
                "category": category,
                "axis": axis_of(category) if category else "",
                "rule_id": record.get("rule_id", ""),
                "permissions": record.get("permissions", ""),
                "threshold": record.get("threshold", ""),
                "prompt_variant": item.get("prompt_variant", ""),
                "probe": item.get("probe", ""),
                "reply": item.get("reply", ""),
                "judge_verdict": judge.get("verdict", ""),
                "judge2_verdict": judge2.get("verdict", ""),
                "tiebreak_verdict": tiebreak.get("verdict", "") if tiebreak else "",
                "tiebreak": ("yes" if tiebreak_used else "no") if judge2 else "",
                "final_verdict": record.get("final_verdict", ""),
                "decided_by": record.get("decided_by", ""),
                "product_risk": record.get("product_risk", ""),
                "judge_reasoning": decider.get("reasoning", ""),
                "quoted_text": decider.get("quoted_text", ""),
                "gate_verdict": gate.get("verdict", ""),
                "reply_tokens": item.get("output_tokens") or "",
                "repeats": len(record.get("repeats") or []) or 1,
                "tiebreak_passes": record.get("tiebreak_passes", "") if judge2 else "",
            }
            rows.append(row)
            per_model[assistant].append(row)
            records_by_model[assistant].append(record)

    rows.sort(key=lambda r: (r["model"], r["item_id"]))
    out_path = Path(args.outputs)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    board = []
    for assistant, items in per_model.items():
        provider, model = split_spec(assistant)
        decided = [r for r in items if r["final_verdict"] in ("pass", "fail", "arguable")]
        passes = sum(1 for r in decided if r["final_verdict"] == "pass")
        fails = sum(1 for r in decided if r["final_verdict"] == "fail")
        arguable = sum(1 for r in decided if r["final_verdict"] == "arguable")
        tokens = [int(r["reply_tokens"]) for r in items if str(r["reply_tokens"]).isdigit()]

        def axis_rate(axis: str) -> str:
            subset = [r for r in decided if r["axis"] == axis]
            if not subset:
                return ""
            return str(round(sum(1 for r in subset if r["final_verdict"] == "pass") / len(subset), 4))

        board.append({
            "model": model,
            "provider": provider,
            "self_graded": "yes" if assistant in judges else "no",
            "items": len(items),
            "decided": len(decided),
            "passes": passes,
            "fails": fails,
            "arguable": arguable,
            "ungraded": sum(1 for r in items if r["final_verdict"] == "ungraded"),
            "errors": sum(1 for r in items if r["final_verdict"] == "error"),
            "pass_rate": round(passes / len(decided), 4) if decided else None,
            "fail_rate": round(fails / len(decided), 4) if decided else None,
            "coverage": round(len(decided) / len(items), 4) if items else 0.0,
            "behaviour_pass_rate": axis_rate("behaviour"),
            "compliance_pass_rate": axis_rate("compliance"),
            "avg_reply_tokens": round(sum(tokens) / len(tokens)) if tokens else "",
            **pass_spread(records_by_model[assistant]),
            "judge": judge_label,
        })

    board = merge_cross_provider(board)

    category_board: list[dict] = []
    for assistant, items in per_model.items():
        provider, model = split_spec(assistant)
        for cat in ALL_CATEGORIES:
            subset = [r for r in items if r["category"] == cat]
            if not subset:
                continue
            decided = [r for r in subset if r["final_verdict"] in ("pass", "fail", "arguable")]
            fails = sum(1 for r in decided if r["final_verdict"] == "fail")
            category_board.append({
                "model": model,
                "provider": provider,
                "category": cat,
                "axis": axis_of(cat),
                "items": len(subset),
                "decided": len(decided),
                "fails": fails,
                "fail_rate": round(fails / len(decided), 4) if decided else None,
            })
    category_board = merge_cross_provider_categories(category_board)
    category_board.sort(key=lambda r: (r["model"], r["axis"], r["category"]))
    categories_path = Path(args.categories)
    categories_path.parent.mkdir(parents=True, exist_ok=True)
    with categories_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CATEGORY_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(category_board)

    # A model graded on a handful of probes is not comparable to one graded on
    # all of them, however good its rate looks. Rank the ones with real
    # coverage; list the rest below, unranked, with the reason visible.
    for row in board:
        row["ranked"] = "yes" if row["coverage"] >= MIN_COVERAGE else "no"
    board.sort(
        key=lambda r: (
            r["ranked"] == "yes",
            r["pass_rate"] if r["pass_rate"] is not None else -1,
        ),
        reverse=True,
    )
    rank = 0
    for row in board:
        if row["ranked"] == "yes":
            rank += 1
            row["rank"] = rank
        else:
            row["rank"] = ""

    board_path = Path(args.leaderboard)
    with board_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=LEADERBOARD_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(board)

    print(f"{len(rows)} model-item rows across {len(per_model)} models -> {out_path}")
    print(f"\n{'#':>2}  {'model':<46} {'pass':>6} {'fail':>5} {'rate':>7} {'cov':>6}")
    for row in board:
        rate = "—" if row["pass_rate"] is None else f"{row['pass_rate'] * 100:.1f}%"
        flag = " *" if row["self_graded"] == "yes" else ""
        if row["ranked"] == "no":
            flag += "  (unranked: coverage below "f"{MIN_COVERAGE:.0%})"
        print(
            f"{str(row['rank']):>2}  {row['model'][:44]:<46} {row['passes']:>6} "
            f"{row['fails']:>5} {rate:>7} {row['coverage']:>6.2f}{flag}"
        )
    print(f"\nWrote {board_path}   (* = graded by itself)")
    print(f"Wrote {categories_path}   ({len(category_board)} model-category rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
