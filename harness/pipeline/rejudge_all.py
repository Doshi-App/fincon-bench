"""Re-judge every row of a run under a new judge (or judge panel), keeping
the stored replies.

Resumable. Each finished row is written to `transcript.rejudge.jsonl` in the
run directory as it completes; a restart skips the rows already there. When
every row is done the sidecar is spliced into `transcript.jsonl`, `run.json`
takes the new judge fields and a `rejudged_all` entry, and `report.md` is
rebuilt. Pass `--finalize` to splice a finished sidecar by hand.

Usage (repo root, under `op run` so the keys resolve):
    python3 harness/pipeline/rejudge_all.py submissions/runs/run-<slug> \\
        --judge ollama:deepseek-v4-pro --judge2 ollama:glm-5.3-flash \\
        --tiebreak anthropic:claude-opus-5 [--concurrency 2] [--limit N] [--dry-run]

The two Ollama judges share one subscription: keep --concurrency low and do
not run this alongside Ollama contestants.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1]
REPO = HARNESS.parent
sys.path.insert(0, str(HARNESS))

from fincon_runner.dataset import load_items  # noqa: E402
from fincon_runner.judge import build_panel  # noqa: E402
from fincon_runner.leaderboard import leaderboard  # noqa: E402
from fincon_runner.rejudge import rejudge_record  # noqa: E402
from fincon_runner.rules import RuleBook  # noqa: E402
from fincon_runner.runner import RunConfig  # noqa: E402
from fincon_runner.transcript import load_graded, load_records, now_stamp, render_report  # noqa: E402

SIDECAR = "transcript.rejudge.jsonl"


def finalize(run_dir: Path, run: dict, args) -> int:
    transcript_path = run_dir / "transcript.jsonl"
    sidecar_path = run_dir / SIDECAR
    records = load_records(transcript_path)
    fresh = {r["item"]["item_id"]: r for r in load_records(sidecar_path)}
    missing = [r["item"]["item_id"] for r in records if r["item"]["item_id"] not in fresh]
    if missing:
        print(f"{run['run_id']}: {len(missing)} row(s) not re-judged yet; not finalizing. Re-run to continue.")
        return 1
    out = [fresh[r["item"]["item_id"]] for r in records]
    transcript_path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out), encoding="utf-8"
    )
    tiebreak_passes = sum(int(r.get("tiebreak_passes", 0) or 0) for r in out)
    errors = sum(1 for r in out if r.get("final_verdict") == "error")
    run["judge"] = args.judge
    if args.judge2:
        run["judge2"] = args.judge2
        run["tiebreak"] = args.tiebreak
        run["judge_scheme"] = "two judges, tiebreak on disagreement"
    else:
        run.pop("judge2", None); run.pop("tiebreak", None); run.pop("judge_scheme", None)
    run["permissions"] = "from the dataset"
    run["dataset"] = args.dataset
    run["rejudged_all"] = {
        "at": now_stamp(),
        "judge": args.judge,
        "judge2": args.judge2 or "",
        "tiebreak": args.tiebreak or "",
        "rows": len(out),
        "tiebreak_passes": tiebreak_passes,
        "errors": errors,
        "previous_judge": run.get("rejudged_all", {}).get("judge") or run.get("previous_judge") or "",
    }
    graded = load_graded(transcript_path)
    run["written_at"] = now_stamp()
    run["leaderboard"] = leaderboard(graded)
    (run_dir / "run.json").write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (run_dir / "report.md").write_text(render_report(graded, run), encoding="utf-8")
    sidecar_path.unlink()
    print(f"{run['run_id']}: re-judged {len(out)} rows; {tiebreak_passes} pass(es) needed the tiebreak; {errors} row(s) in error")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir")
    parser.add_argument("--judge", required=True)
    parser.add_argument("--judge2", default="")
    parser.add_argument("--tiebreak", default="")
    parser.add_argument("--dataset", default="datasets/benchmark-open.csv", help="Repo-relative. Supplies each row's permissions.")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--limit", type=int, help="Re-judge at most N rows this invocation (for a trial).")
    parser.add_argument("--dry-run", action="store_true", help="Count the work and stop. No call is made.")
    parser.add_argument("--finalize", action="store_true", help="Splice a finished sidecar and stop.")
    parser.add_argument(
        "--all-rows", action="store_true",
        help="Also re-judge rows that already carry a two-judge record (`judge2`). By default such rows "
             "were judged under the target scheme already and are carried over unchanged.",
    )
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    # `run.json`'s judge field follows the latest append, so the judge the old
    # rows were marked by is read off the rows themselves.
    previous_judge = run.get("judge", "")
    for record in load_records(run_dir / "transcript.jsonl"):
        if record.get("judge2") is None and (record.get("judge") or {}).get("model"):
            previous_judge = record["judge"]["model"]
            break
    if args.finalize:
        return finalize(run_dir, run, args)

    records = load_records(run_dir / "transcript.jsonl")
    sidecar_path = run_dir / SIDECAR
    done = {r["item"]["item_id"] for r in load_records(sidecar_path)} if sidecar_path.exists() else set()
    todo = [r for r in records if r["item"]["item_id"] not in done]
    carried = []
    if not args.all_rows:
        carried = [r for r in todo if r.get("judge2") is not None]
        todo = [r for r in todo if r.get("judge2") is None]
    passes = sum(max(1, len(r.get("repeats") or [])) for r in todo)
    judged = sum(
        sum(1 for p in (r.get("repeats") or [r]) if p.get("reply") or (p is r and r.get("item", {}).get("reply")))
        for r in todo
    )
    print(
        f"{run['run_id']}: {len(records)} rows, {len(done)} already re-judged, {len(carried)} already under "
        f"the two-judge scheme (carried over), {len(todo)} to do "
        f"({passes} passes, about {2 * judged} judge calls plus tiebreaks); previous judge `{previous_judge}`"
    )
    if args.dry_run:
        return 0
    if carried:
        with sidecar_path.open("a", encoding="utf-8") as handle:
            for record in carried:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    if not todo:
        return finalize(run_dir, run, args)
    if args.limit:
        todo = todo[: args.limit]

    dataset = {item.item_id: item for item in load_items(REPO / args.dataset)}
    rule_book = RuleBook.load(REPO / "rules")
    judge = build_panel(args.judge, args.judge2, args.tiebreak)
    config = RunConfig(
        assistant=run["assistant"],
        run_id=run["run_id"],
        permissions_override="",
        confirm_gate_fails=run.get("confirm_gate_fails", False),
        include_examples=run.get("include_examples", False),
        concurrency=args.concurrency,
        repeats=run.get("repeats", 1),
    )

    lock = threading.Lock()
    counter = {"done": 0, "tiebreaks": 0, "errors": 0}

    def work(record: dict) -> None:
        graded = rejudge_record(record, dataset.get(record["item"]["item_id"]), config, judge, rule_book)
        line = json.dumps(graded.as_finding_record(), ensure_ascii=False) + "\n"
        with lock:
            with sidecar_path.open("a", encoding="utf-8") as handle:
                handle.write(line)
            counter["done"] += 1
            counter["tiebreaks"] += graded.tiebreak_passes
            counter["errors"] += graded.final_verdict == "error"
            if sys.stderr.isatty():
                print(f"\r  re-judged {counter['done']}/{len(todo)}", end="", file=sys.stderr, flush=True)

    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        list(pool.map(work, todo))
    if sys.stderr.isatty():
        print("", file=sys.stderr)
    print(f"this invocation: {counter['done']} rows, {counter['tiebreaks']} tiebreak pass(es), {counter['errors']} row(s) in error")

    remaining = len(records) - len(done) - len(carried) - counter["done"]
    if remaining:
        print(f"{remaining} row(s) remain; re-run to continue. Sidecar: {sidecar_path}")
        return 0
    run["previous_judge"] = previous_judge
    return finalize(run_dir, run, args)


if __name__ == "__main__":
    raise SystemExit(main())
