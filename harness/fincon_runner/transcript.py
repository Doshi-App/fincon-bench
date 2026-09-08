"""Write the transcript.

One run writes one directory under `submissions/`. The directory holds 3 files.

- `run.json` — what was run, against what, with what judge. No secrets.
- `transcript.jsonl` — one line per item, machine-readable. Every item is here,
  pass and fail alike, with the gate result, the judge verdict and the final
  verdict. This is the audit record.
- `report.md` — the same run in human words, findings first, highest product
  risk first.

The transcript holds the system prompt and the reply for every item, so a reader
can check the run without rerunning it.

`load_graded` reads a transcript back into `GradedItem`s, enough to rebuild the
leaderboard, the report and a re-judge. `append_transcript` adds newly graded
items to an existing run without touching the lines already there; `run.json`
records each append under `appended`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .leaderboard import leaderboard
from .models import (
    Authority,
    GateResult,
    GradedItem,
    Item,
    JudgeResult,
    RepeatRun,
    Rule,
    axis_of,
)

RISK_ORDER = {"high": 0, "medium": 1, "low": 2, "": 3}
VERDICT_ORDER = {"fail": 0, "arguable": 1, "error": 2, "ungraded": 3, "pass": 4}


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_id_for(assistant: str, stamp: str | None = None) -> str:
    """A run ID that sorts by date and names the assistant."""
    stamp = stamp or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in assistant.lower())
    return f"{stamp}-{safe}"


def write_transcript(
    out_dir: Path,
    graded: list[GradedItem],
    metadata: dict,
) -> dict[str, Path]:
    """Write the 3 transcript files and return their paths."""
    out_dir.mkdir(parents=True, exist_ok=True)

    transcript_path = out_dir / "transcript.jsonl"
    with transcript_path.open("w", encoding="utf-8") as handle:
        for item in graded:
            handle.write(json.dumps(item.as_finding_record(), ensure_ascii=False) + "\n")

    rows = leaderboard(graded)
    run_record = {**metadata, "written_at": now_stamp(), "leaderboard": rows}
    run_path = out_dir / "run.json"
    run_path.write_text(
        json.dumps(run_record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    report_path = out_dir / "report.md"
    report_path.write_text(render_report(graded, run_record), encoding="utf-8")

    return {"run": run_path, "transcript": transcript_path, "report": report_path}


def _judge_from(raw: dict | None) -> JudgeResult | None:
    if raw is None:
        return None
    return JudgeResult(
        verdict=raw.get("verdict", "skipped"),
        model=raw.get("model", ""),
        reasoning=raw.get("reasoning", ""),
        quoted_text=raw.get("quoted_text", ""),
        product_risk=raw.get("product_risk", ""),
        raw=raw.get("raw", ""),
    )


def _gate_from(raw: dict) -> GateResult:
    return GateResult(
        applied=bool(raw.get("applied")),
        verdict=raw.get("verdict", "not_applicable"),
        detail=raw.get("detail", ""),
        evidence=tuple(raw.get("evidence", ())),
        figure_id=raw.get("figure_id", ""),
    )


def graded_from_record(record: dict) -> GradedItem:
    """Rebuild one graded item from one transcript line."""
    item_record = record.get("item", {})
    tokens = item_record.get("output_tokens")
    if isinstance(tokens, str):
        tokens = int(tokens) if tokens.isdigit() else None
    item = Item(
        item_id=item_record.get("item_id", ""),
        jurisdiction=record.get("jurisdiction", ""),
        category=record.get("category", ""),
        rule_id=record.get("rule_id", ""),
        probe=item_record.get("probe", ""),
        system_prompt=record.get("system_prompt", ""),
        permissions=record.get("permissions", "none"),
        reply=item_record.get("reply", ""),
        output_tokens=tokens,
        item_type=item_record.get("type", "chat"),
        lesson_id=item_record.get("lesson_id", ""),
        slide=item_record.get("slide", ""),
    )
    authority = record.get("authority") or {}
    rule = None
    if authority and record.get("rule_id"):
        rule = Rule(
            rule_id=record["rule_id"],
            category=item.category,
            jurisdiction=item.jurisdiction,
            authority=Authority(
                source=authority.get("source", ""),
                clause=authority.get("clause", ""),
                url=authority.get("url", ""),
                retrieved=authority.get("retrieved", ""),
            ),
        )
    repeats = tuple(
        RepeatRun(
            run_index=raw_run.get("run_index", index),
            reply=raw_run.get("reply", ""),
            gate=_gate_from(raw_run.get("gate", {})),
            judge=_judge_from(raw_run.get("judge", {})),
            final_verdict=raw_run.get("final_verdict", "ungraded"),
            decided_by=raw_run.get("decided_by", "none"),
            output_tokens=raw_run.get("output_tokens"),
            judge2=_judge_from(raw_run.get("judge2")),
            tiebreak=_judge_from(raw_run.get("tiebreak")),
            tiebreak_used=bool(raw_run.get("tiebreak_used", False)),
        )
        for index, raw_run in enumerate(record.get("repeats", ()))
    )
    judge = dict(record.get("judge", {}))
    judge.setdefault("product_risk", record.get("product_risk", ""))
    judge_result = _judge_from(judge)
    judge_result = JudgeResult(
        verdict=judge_result.verdict,
        model=judge_result.model,
        reasoning=judge_result.reasoning,
        quoted_text=judge_result.quoted_text,
        product_risk=judge_result.product_risk,
        raw=judge_result.raw,
        output_tokens=record.get("judge_output_tokens"),
    )
    return GradedItem(
        item=item,
        rule=rule,
        gate=_gate_from(record.get("gate", {})),
        judge=judge_result,
        final_verdict=record.get("final_verdict", "ungraded"),
        threshold=record.get("threshold", "n/a"),
        decided_by=record.get("decided_by", "none"),
        assistant=record.get("assistant", ""),
        finding_id=record.get("finding_id", ""),
        error=record.get("error", ""),
        repeats=repeats,
        repeat_tally=dict(record.get("repeat_tally", {})),
        judge2=_judge_from(record.get("judge2")),
        tiebreak=_judge_from(record.get("tiebreak")),
        tiebreak_used=bool(record.get("tiebreak_used", False)),
        tiebreak_passes=int(record.get("tiebreak_passes", 0) or 0),
    )


def load_records(path: Path) -> list[dict]:
    """Every line of a transcript, as written."""
    records = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def load_graded(path: Path) -> list[GradedItem]:
    """Rebuild graded items from a transcript, enough for scoring and re-judging."""
    return [graded_from_record(record) for record in load_records(path)]


def append_transcript(
    out_dir: Path,
    graded: list[GradedItem],
    metadata: dict,
) -> dict[str, Path]:
    """Add newly graded items to an existing run.

    The existing transcript lines are not rewritten: the new records go on the
    end. `run.json` keeps its original fields, takes the judge and permission
    fields of this append (they describe the run as it now stands), and gains
    an entry under `appended` saying what was added and how. The leaderboard
    and the report are rebuilt over every line.
    """
    transcript_path = out_dir / "transcript.jsonl"
    run_path = out_dir / "run.json"
    if not transcript_path.exists() or not run_path.exists():
        raise FileNotFoundError(f"{out_dir}: no run to append to")

    with transcript_path.open("a", encoding="utf-8") as handle:
        for item in graded:
            handle.write(json.dumps(item.as_finding_record(), ensure_ascii=False) + "\n")

    everything = load_graded(transcript_path)
    run_record = json.loads(run_path.read_text(encoding="utf-8"))
    entry = {
        "at": now_stamp(),
        "items": len(graded),
        "item_ids": sorted(g.item.item_id for g in graded),
    }
    for key in ("dataset", "judge", "judge2", "tiebreak", "judge_scheme", "permissions", "repeats", "started_at"):
        if key in metadata:
            entry[key] = metadata[key]
            run_record[key] = metadata[key]
    run_record.setdefault("appended", []).append(entry)
    run_record["items"] = len(everything)
    run_record["written_at"] = now_stamp()
    run_record["leaderboard"] = leaderboard(everything)
    run_path.write_text(
        json.dumps(run_record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    report_path = out_dir / "report.md"
    report_path.write_text(render_report(everything, run_record), encoding="utf-8")
    return {"run": run_path, "transcript": transcript_path, "report": report_path}


def _sort_key(item: GradedItem):
    return (
        VERDICT_ORDER.get(item.final_verdict, 9),
        RISK_ORDER.get(item.judge.product_risk, 3),
        item.item.jurisdiction,
        item.item.item_id,
    )


def render_report(graded: list[GradedItem], run_record: dict) -> str:
    """Render the human-readable report."""
    lines = ["# FinCon Bench run", ""]
    lines += [
        f"- Run ID: `{run_record.get('run_id', '')}`",
        f"- Started: {run_record.get('started_at', '')}",
        f"- Dataset: `{run_record.get('dataset', '')}`",
        f"- Provider: `{run_record.get('provider', '')}`",
        f"- Judge: `{run_record.get('judge', '')}`",
    ]
    if run_record.get("judge2"):
        lines += [
            f"- Judge 2: `{run_record.get('judge2', '')}`",
            f"- Tiebreak: `{run_record.get('tiebreak', '')}`, called only where the two judges disagree",
        ]
    lines += [
        f"- Permissions applied: `{run_record.get('permissions', 'from the dataset')}`",
        f"- Rules read from: `{run_record.get('rules_dir', '')}`",
        f"- Repeats per item: `{run_record.get('repeats', 1)}`",
    ]
    for entry in run_record.get("appended", []):
        lines.append(
            f"- Appended {entry.get('items', 0)} item(s) on {entry.get('at', '')} "
            f"at {entry.get('repeats', 1)} repeat(s), judge `{entry.get('judge', '')}`"
            + (f", judge 2 `{entry['judge2']}`, tiebreak `{entry.get('tiebreak', '')}`" if entry.get("judge2") else "")
        )
    rejudged = run_record.get("rejudged_all")
    if rejudged:
        lines.append(
            f"- Re-judged every row on {rejudged.get('at', '')}: judge `{rejudged.get('judge', '')}`"
            + (f", judge 2 `{rejudged['judge2']}`, tiebreak `{rejudged.get('tiebreak', '')}`" if rejudged.get("judge2") else "")
            + f"; {rejudged.get('tiebreak_passes', 0)} pass(es) needed the tiebreak"
        )
    tiebroken = sum(1 for g in graded if g.tiebreak_used)
    if any(g.judge2 is not None for g in graded):
        lines.append(f"- Rows whose published verdict came from the tiebreak: {tiebroken} of {len(graded)}")
    lines.append("")

    lines += ["## Leaderboard", ""]
    lines += [
        "| Assistant | Threshold | Items | Graded | Fails | Fail rate | Ungraded | Errors |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in run_record.get("leaderboard", []):
        rate = "—" if row["fail_rate"] is None else f"{row['fail_rate'] * 100:.1f}%"
        lines.append(
            f"| {row['assistant']} | {row['threshold']} | {row['items']} | "
            f"{row['graded']} | {row['fails']} | {rate} | {row['ungraded']} | "
            f"{row['errors']} |"
        )
    lines.append("")

    lines += ["## Fails by category", "", "| Category | Axis | Items | Fails |", "|---|---|---|---|"]
    for row in run_record.get("leaderboard", []):
        for category, cell in sorted(
            row["categories"].items(), key=lambda pair: -pair[1]["fails"]
        ):
            lines.append(
                f"| {category} | {cell['axis']} | {cell['items']} | {cell['fails']} |"
            )
    lines.append("")

    miss = run_record.get("miss_rate")
    if miss:
        lines += [
            "## Miss rate against the filed corrections",
            "",
            f"- Filed corrections: {miss['filed']}",
            f"- Rediscovered: {miss['rediscovered']}",
            f"- Missed: {miss['missed']}",
            f"- Miss rate: {miss['miss_rate']}",
            f"- Bar: find at least {int(miss['bar'] * 100)} percent. "
            f"{'Met.' if miss['meets_bar'] else 'Not met.'}",
            "",
        ]

    findings = [item for item in graded if item.is_finding]
    lines += [f"## Findings ({len(findings)})", ""]
    if not findings:
        lines += ["No finding. A pass produces no record.", ""]

    for item in sorted(findings, key=_sort_key):
        authority = item.rule.authority if item.rule else None
        citation = (
            f"{authority.source} {authority.clause} — {authority.url}"
            if authority
            else "no citation on file"
        )
        quoted = item.judge.quoted_text or ", ".join(item.gate.evidence)
        rule_id = item.rule.rule_id if item.rule else (item.item.rule_id or "not stated")
        lines += [
            f"### {item.finding_id}",
            "",
            f"- **Category.** {item.item.category} ({axis_of(item.item.category)})",
            f"- **Jurisdiction.** {item.item.jurisdiction}",
            f"- **Rule.** `{rule_id}`",
            f"- **Authority.** {citation}",
            f"- **Threshold.** {item.threshold}",
            f"- **Decided by.** {item.decided_by}",
        ]
        if item.repeat_tally:
            tally_text = ", ".join(
                f"{count} {verdict}"
                for verdict, count in sorted(item.repeat_tally.items(), key=lambda pair: -pair[1])
            )
            lines.append(f"- **Repeats.** {len(item.repeats)} runs ({tally_text}).")
        if item.judge2 is not None:
            lines.append(
                f"- **Judges.** A `{item.judge.verdict}`, B `{item.judge2.verdict}`"
                + (f", tiebreak `{item.tiebreak.verdict}`" if item.decided_by == "tiebreak" and item.tiebreak else ", agreed")
                + (f"; {item.tiebreak_passes} of {len(item.repeats)} passes needed the tiebreak" if item.repeats else "")
            )
        if item.judge.product_risk:
            lines.append(f"- **Product risk.** {item.judge.product_risk}")
        if item.item.probe:
            lines.append(f"- **Probe.** {item.item.probe}")
        if quoted:
            lines.append(f"- **Quoted text.** {quoted}")
        lines += [f"- **Reasoning.** {item.reasoning}", ""]

    problems = [
        item for item in graded if item.final_verdict in ("ungraded", "error", "arguable")
    ]
    if problems:
        lines += [f"## Items that produced no verdict ({len(problems)})", ""]
        lines += ["| Item | Category | Verdict | Why |", "|---|---|---|---|"]
        for item in sorted(problems, key=_sort_key):
            why = item.error or item.reasoning
            lines.append(
                f"| {item.item.item_id} | {item.item.category} | "
                f"{item.final_verdict} | {why.replace('|', '/')} |"
            )
        lines.append("")

    return "\n".join(lines)
