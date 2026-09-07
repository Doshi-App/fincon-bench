"""Re-judge the rows of a run that failed for reasons unrelated to the judge.

A run's transcript is written once, so a burst of HTTP 429s or a billing hiccup
leaves `verdict: error` rows that say nothing about the judge. This re-runs only
those rows, with the same judge and dataset, and splices the new records into
`transcript.jsonl`. Rows where the judge answered but its answer did not parse
are left alone: that is judge behaviour and the scorer counts it.

Under a two-judge run (`judge2` and `tiebreak` in `run.json`) the panel is
rebuilt and every seat is checked for the error, on the row and on each pass.

Usage (repo root, under `op run` so the keys resolve):
    python3 harness/pipeline/rejudge_errors.py submissions/judges/judge-<slug> [--concurrency 2] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))

from fincon_runner.dataset import load_items  # noqa: E402
from fincon_runner.figures import FigureBook  # noqa: E402
from fincon_runner.judge import build_panel  # noqa: E402
from fincon_runner.providers import build_provider  # noqa: E402
from fincon_runner.rules import RuleBook  # noqa: E402
from fincon_runner.runner import RunConfig, grade_items  # noqa: E402
from fincon_runner.transcript import now_stamp  # noqa: E402

TRANSPORT = re.compile(
    r"HTTP (429|5\d\d)|Error code: (429|5\d\d)|no credits|Too many requests|hrottl|"
    r"timed out|timeout|Connection|Remote end closed|Retry also failed",
    re.IGNORECASE,
)


def _judge_seats(record: dict):
    """Every judge answer a row holds: the row's own seats and each pass's.
    Under a two-judge panel that is `judge`, `judge2` and `tiebreak`."""
    for holder in [record, *(record.get("repeats") or [])]:
        for key in ("judge", "judge2", "tiebreak"):
            seat = holder.get(key)
            if seat:
                yield seat


def transport_error(record: dict) -> bool:
    return any(
        seat.get("verdict") == "error" and TRANSPORT.search(seat.get("reasoning") or "")
        for seat in _judge_seats(record)
    )


def any_error(record: dict) -> bool:
    return any(seat.get("verdict") == "error" for seat in _judge_seats(record))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--include-judge-output", action="store_true",
        help="Also re-run rows where the judge answered but the answer could not be read. "
             "Use after a harness fix to the parser or the provider lane, not to give a judge a second try.",
    )
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    transcript_path = run_dir / "transcript.jsonl"
    lines = transcript_path.read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines if line.strip()]

    select = any_error if args.include_judge_output else transport_error
    wanted = {r["item"]["item_id"] for r in records if select(r)}
    kind = "failed" if args.include_judge_output else "failed on transport"
    print(f"{run['run_id']}: {len(wanted)} of {len(records)} rows {kind}")
    if not wanted:
        return 0
    if args.dry_run:
        print(sorted(wanted))
        return 0

    dataset = (HARNESS / run["dataset"]).resolve()
    if not dataset.exists():
        # Older run records carry a path from another checkout layout.
        dataset = (HARNESS.parent / "datasets" / Path(run["dataset"]).name).resolve()
    rules_dir = (HARNESS / run["rules_dir"]).resolve()
    items = [i for i in load_items(dataset) if i.item_id in wanted]
    rule_book = RuleBook.load(rules_dir / "grading")
    figures_dir = rules_dir.parent / "sourcebooks" / "statutory_figures"
    figure_book = FigureBook.load(figures_dir) if figures_dir.is_dir() else None
    provider = build_provider(run["provider"], None)
    judge = build_panel(run["judge"], run.get("judge2", ""), run.get("tiebreak", ""))
    config = RunConfig(
        assistant=run["assistant"],
        run_id=run["run_id"],
        permissions_override="" if run.get("permissions") == "from the dataset" else run.get("permissions", ""),
        confirm_gate_fails=run.get("confirm_gate_fails", False),
        include_examples=run.get("include_examples", False),
        concurrency=args.concurrency,
        repeats=run.get("repeats", 1),
    )
    graded = grade_items(items, config, provider, judge, rule_book, figure_book)
    fresh = {g.item.item_id: g.as_finding_record() for g in graded}

    still = 0
    out = []
    for record in records:
        item_id = record["item"]["item_id"]
        if item_id in fresh:
            record = fresh[item_id]
            if select(record):
                still += 1
        out.append(record)
    transcript_path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out), encoding="utf-8"
    )
    run.setdefault("rejudged", []).append(
        {"at": now_stamp(), "items": sorted(wanted), "still_failing": still}
    )
    (run_dir / "run.json").write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"re-judged {len(wanted)} rows; {still} still failing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
