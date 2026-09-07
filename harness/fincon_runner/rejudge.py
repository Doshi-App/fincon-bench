"""Mark the rows of an existing run again, under a new judge, without
regenerating a single reply.

The leaderboard must be graded by one scheme throughout. When the judge
changes, every row already on it is marked again by the new judge, on the
reply the transcript stored. The reply, the gate result and the pass count
stay exactly as they were; only the judge stage runs.

Permissions come from the dataset row, not from the stored record. The
2026-08-13 run graded every reply under `--permissions none`, while the
system prompt the model actually saw came from the dataset row and declared
the row's own permission. Re-judging under the dataset permission grades each
reply against the test its own prompt set.

`rejudge_record` does one row. `pipeline/rejudge_all.py` drives it over a
run directory, resumably.
"""

from __future__ import annotations

from .judge import Judge, threshold_for
from .models import GateResult, GradedItem, Item, JudgeResult, RepeatRun
from .rules import RuleBook
from .runner import RunConfig, assemble, rejudge_pass
from .transcript import graded_from_record


def _passes_of(graded: GradedItem) -> list[RepeatRun]:
    """The stored passes of a row. A single-pass row becomes one pass."""
    if graded.repeats:
        return list(graded.repeats)
    return [
        RepeatRun(
            run_index=0,
            reply=graded.item.reply,
            gate=graded.gate,
            judge=graded.judge,
            final_verdict=graded.final_verdict,
            decided_by=graded.decided_by,
            output_tokens=graded.item.output_tokens,
        )
    ]


def rejudge_record(
    record: dict,
    dataset_item: Item | None,
    config: RunConfig,
    judge: Judge,
    rule_book: RuleBook,
) -> GradedItem:
    """Mark one transcript row again with `judge`.

    `dataset_item` is the row's dataset entry, used for its permissions,
    system prompt and probe. When it is `None` the record's own values stand.
    The stored reply and gate of every pass are kept.
    """
    graded = graded_from_record(record)
    item = graded.item
    if dataset_item is not None:
        item = Item(
            **{
                **item.__dict__,
                "permissions": dataset_item.permissions,
                "system_prompt": dataset_item.system_prompt or item.system_prompt,
                "probe": dataset_item.probe or item.probe,
                "rule_id": item.rule_id or dataset_item.rule_id,
            }
        )
    rule = rule_book.rule_for_item(item.rule_id, item.category, item.jurisdiction)
    rubric = rule_book.rubric_for(item.category)
    threshold = (
        threshold_for(item.permissions)
        if item.category == "product_recommendation"
        else "n/a"
    )

    if rubric is None:
        # The row cannot be graded under this rulebook. Keep it as an error.
        reason = f"No rule file defines the category `{item.category}`."
        return GradedItem(
            item=item,
            rule=rule,
            gate=GateResult(applied=False, detail=reason),
            judge=JudgeResult(verdict="error", model=judge.name, reasoning=reason),
            final_verdict="error",
            threshold=threshold,
            decided_by="none",
            assistant=graded.assistant,
            finding_id=graded.finding_id,
            error=reason,
        )
    if graded.final_verdict == "ungraded" and graded.decided_by == "none" and not graded.item.reply:
        # Never scored: no citation in its jurisdiction, no reply. Leave it.
        return graded

    passes = [rejudge_pass(item, stored, config, judge, rubric, rule) for stored in _passes_of(graded)]
    if not graded.repeats and len(passes) == 1:
        # A single-pass row stays single-pass: `assemble` writes no repeats
        # trail for one pass, matching the row's original shape.
        pass
    fresh = assemble(item, rule, passes, config, threshold)
    # `assemble` derives the finding ID from the config's run ID; the stored
    # one is the published identity of the row, so keep it.
    fresh.finding_id = graded.finding_id or fresh.finding_id
    fresh.assistant = graded.assistant or config.assistant
    return fresh
