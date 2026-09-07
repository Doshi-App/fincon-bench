"""Execute a run.

The order for one item is fixed.

1. Get the reply from the provider.
2. Run the deterministic gate, if the category defines one.
3. If the gate failed the item, stop. The gate is published data, so it decides.
4. Otherwise send the rubric, the item and the gate evidence to the judge.
5. Record the final verdict, the citation and the reasoning.

`RunConfig.repeats` runs that sequence more than once for the same item and
takes the majority verdict. `cli.py` sets it to 5 for the `ollama` and
`bedrock` providers, 3 for `anthropic` and 1 for every other provider — see
`providers.DEFAULT_REPEATS_BY_KIND`. Every pass is kept on the graded item, in
`GradedItem.repeats`, for audit.

The judge stage (`judge_pass`) is its own function so that a stored reply can
be marked again under a new judge without being regenerated. `rejudge_pass`
does exactly that for one recorded pass; `assemble` turns the passes of one
item back into a `GradedItem`. `pipeline/rejudge_all.py` uses both.

The runner never guesses. An item it cannot grade is recorded as `ungraded` or
`error`, never as a pass.
"""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from .figures import FigureBook
from .gates import run_gate
from .judge import Judge, PanelVerdict, build_prompt, threshold_for
from .models import GateResult, GradedItem, Item, JudgeResult, RepeatRun, Rubric, Rule
from .providers import Provider, ProviderError, Reply
from .rules import RuleBook

# Ties break toward `fail`, then the rest in this order. This is a deliberate
# exception to docs/method.md, which says a false positive costs more than a
# missed finding everywhere else in the run. A tie on a repeated item is rare
# — an even split of the passes — and the choice here is to let it surface for
# a person to look at, rather than let a coin flip decide it silently.
TIE_BREAK_ORDER = ("fail", "error", "arguable", "ungraded", "pass")


@dataclass
class RunConfig:
    """Everything a run needs that is not the data itself."""

    assistant: str
    run_id: str
    permissions_override: str = ""
    confirm_gate_fails: bool = False
    include_examples: bool = False
    concurrency: int = 4
    allow_uncited: bool = False
    # Passes per item. 1 means the old, single-pass behaviour exactly. See
    # `providers.REPEATED_PROVIDER_KINDS` and `providers.DEFAULT_REPEATS`.
    repeats: int = 1


def finding_id(run_id: str, item: Item) -> str:
    """A stable ID for one graded item in one run."""
    digest = hashlib.sha1(
        f"{run_id}|{item.item_id}|{item.category}".encode("utf-8")
    ).hexdigest()[:8]
    return f"f-{run_id}-{item.jurisdiction}-{item.item_id}-{digest}"


def _apply_permissions(item: Item, override: str) -> Item:
    """The submission declares its permissions. That declaration wins.

    `docs/rubric.md` says the threshold is a property of the submission. The
    dataset column carries a default for the row. When a run declares the
    permissions of the assistant under test, the declaration replaces the
    column for every row.
    """
    if not override or override == item.permissions:
        return item
    return Item(**{**item.__dict__, "permissions": override})


def _run_once(
    item: Item,
    config: RunConfig,
    provider: Provider,
    judge: Judge,
    rubric: Rubric,
    rule: Rule | None,
    figure_book: FigureBook | None,
    run_index: int,
) -> tuple[Item, RepeatRun]:
    """One pass over one item: get a reply, gate it, judge it.

    Never raises. A provider failure becomes an `error` pass instead of an
    exception, so one bad call among several repeats does not sink the item.
    """
    try:
        reply = provider.reply_for(item)
    except ProviderError as exc:
        run = RepeatRun(
            run_index=run_index,
            reply="",
            gate=GateResult(applied=False, detail=str(exc)),
            judge=JudgeResult(verdict="error", model=judge.name, reasoning=str(exc)),
            final_verdict="error",
            decided_by="none",
        )
        return item, run

    item = Item(**{**item.__dict__, "reply": reply.text, "output_tokens": reply.output_tokens})
    gate = run_gate(item, reply.text, figure_book)

    if gate.verdict == "fail" and not config.confirm_gate_fails:
        run = RepeatRun(
            run_index=run_index,
            reply=reply.text,
            gate=gate,
            judge=JudgeResult(
                verdict="skipped",
                model=judge.name,
                reasoning="The deterministic check failed the item, so the judge did not run.",
            ),
            final_verdict="fail",
            decided_by="gate",
            output_tokens=reply.output_tokens,
        )
        return item, run

    run = judge_pass(
        item, reply.text, gate, config, judge, rubric, rule, run_index, reply.output_tokens
    )
    return item, run


def judge_pass(
    item: Item,
    reply: str,
    gate: GateResult,
    config: RunConfig,
    judge: Judge,
    rubric: Rubric,
    rule: Rule | None,
    run_index: int,
    output_tokens: int | None,
) -> RepeatRun:
    """The judge stage for one pass: build the prompt, mark, settle the verdict.

    The gate has already run and did not fail the item (or the run confirms
    gate fails). Under a `JudgePanel` this is where judge A, judge B and the
    tiebreak are called, one after the other.
    """
    prompt = build_prompt(item, reply, rubric, rule, gate, config.include_examples)
    panel: PanelVerdict = judge.mark_panel(prompt)

    if panel.verdict in ("fail", "pass", "arguable"):
        final = panel.verdict
        # `tiebreak` says the two judges disagreed and the third decided.
        # The leaderboard counts it as a judge decision.
        decided_by = "tiebreak" if panel.tiebreak_used else "judge"
    elif gate.verdict == "fail":
        # The judge was asked to confirm the gate and could not answer. The gate
        # stands, because the gate reads published data.
        final = "fail"
        decided_by = "gate"
    elif gate.verdict == "pass":
        final = "pass"
        decided_by = "gate"
    else:
        final = "ungraded"
        decided_by = "none"

    return RepeatRun(
        run_index=run_index,
        reply=reply,
        gate=gate,
        judge=panel.judge,
        final_verdict=final,
        decided_by=decided_by,
        output_tokens=output_tokens,
        judge2=panel.judge2,
        tiebreak=panel.tiebreak,
        tiebreak_used=panel.tiebreak_used,
    )


def rejudge_pass(
    item: Item,
    stored: RepeatRun,
    config: RunConfig,
    judge: Judge,
    rubric: Rubric,
    rule: Rule | None,
) -> RepeatRun:
    """Mark a recorded pass again with `judge`, keeping its reply and gate.

    A pass with no reply (the provider failed) stays an error. A pass the gate
    failed, when the run does not confirm gate fails, stays decided by the gate
    and the judge is not called: the gate reads published data, and nothing
    about it has changed.
    """
    if not stored.reply:
        return stored
    if stored.gate.verdict == "fail" and not config.confirm_gate_fails:
        return RepeatRun(
            run_index=stored.run_index,
            reply=stored.reply,
            gate=stored.gate,
            judge=JudgeResult(
                verdict="skipped",
                model=judge.name,
                reasoning="The deterministic check failed the item, so the judge did not run.",
            ),
            final_verdict="fail",
            decided_by="gate",
            output_tokens=stored.output_tokens,
        )
    return judge_pass(
        item, stored.reply, stored.gate, config, judge, rubric, rule,
        stored.run_index, stored.output_tokens,
    )


def _majority(runs: list[RepeatRun]) -> tuple[str, dict[str, int]]:
    """The verdict most of the runs reached. Ties break toward `fail`."""
    tally: dict[str, int] = {}
    for run in runs:
        tally[run.final_verdict] = tally.get(run.final_verdict, 0) + 1
    best = max(tally.values())
    winners = {verdict for verdict, count in tally.items() if count == best}
    final = next(verdict for verdict in TIE_BREAK_ORDER if verdict in winners)
    return final, tally


def grade_item(
    item: Item,
    config: RunConfig,
    provider: Provider,
    judge: Judge,
    rule_book: RuleBook,
    figure_book: FigureBook | None,
) -> GradedItem:
    """Run one item all the way through, `config.repeats` times."""
    item = _apply_permissions(item, config.permissions_override)
    rule = rule_book.rule_for_item(item.rule_id, item.category, item.jurisdiction)
    rubric = rule_book.rubric_for(item.category)
    threshold = (
        threshold_for(item.permissions)
        if item.category == "product_recommendation"
        else "n/a"
    )

    def failed(reason: str, gate: GateResult | None = None) -> GradedItem:
        return GradedItem(
            item=item,
            rule=rule,
            gate=gate or GateResult(applied=False, detail=reason),
            judge=JudgeResult(verdict="error", model=judge.name, reasoning=reason),
            final_verdict="error",
            threshold=threshold,
            decided_by="none",
            assistant=config.assistant,
            finding_id=finding_id(config.run_id, item),
            error=reason,
        )

    if rubric is None:
        return failed(f"No rule file defines the category `{item.category}`.")

    if rule is None and not config.allow_uncited:
        # A finding must cite its authority (docs/rubric.md). When the category
        # cites nothing in this jurisdiction, the item is not scored there.
        return GradedItem(
            item=item,
            rule=None,
            gate=GateResult(
                applied=False,
                detail=f"`{item.category}` has no rule for `{item.jurisdiction}`.",
            ),
            judge=JudgeResult(
                verdict="skipped",
                model=judge.name,
                reasoning=(
                    f"The category `{item.category}` cites no authority in "
                    f"`{item.jurisdiction}`, so this item cannot produce a finding "
                    f"that names its authority."
                ),
            ),
            final_verdict="ungraded",
            threshold=threshold,
            decided_by="none",
            assistant=config.assistant,
            finding_id=finding_id(config.run_id, item),
        )

    passes = max(1, config.repeats)
    runs = [
        _run_once(item, config, provider, judge, rubric, rule, figure_book, index)[1]
        for index in range(passes)
    ]
    return assemble(item, rule, runs, config, threshold)


def _with_reasoning(result: JudgeResult, reasoning: str) -> JudgeResult:
    return JudgeResult(
        verdict=result.verdict,
        model=result.model,
        reasoning=reasoning,
        quoted_text=result.quoted_text,
        product_risk=result.product_risk,
        raw=result.raw,
        output_tokens=result.output_tokens,
    )


def assemble(
    item: Item,
    rule: Rule | None,
    runs: list[RepeatRun],
    config: RunConfig,
    threshold: str,
) -> GradedItem:
    """Turn the passes of one item into its transcript row.

    The majority verdict wins; the first pass that reached it is the
    representative whose reply, gate and judge answers the row shows. A single
    pass leaves no `repeats` trail, so a 1-pass run keeps its old shape.
    """
    passes = len(runs)
    final, tally = _majority(runs)
    representative = next(run for run in runs if run.final_verdict == final)

    decider = representative.tiebreak if (
        representative.tiebreak_used and representative.tiebreak is not None
    ) else representative.judge
    reasoning = decider.reasoning
    if passes > 1:
        reasoning = f"{tally[final]}/{passes} run(s) marked this `{final}`. {reasoning}"

    graded_item = Item(
        **{
            **item.__dict__,
            "reply": representative.reply,
            "output_tokens": representative.output_tokens,
        }
    )

    # The row's `tiebreak_used` flag is true when any pass needed the third
    # judge, so a reader filtering on it sees every row the tiebreak touched.
    # `decided_by` says whether the representative pass itself was contested.
    contested = [run for run in runs if run.tiebreak_used]
    tiebreak = representative.tiebreak
    if representative.tiebreak_used and tiebreak is not None:
        judge_a = representative.judge
        tiebreak = _with_reasoning(tiebreak, reasoning)
    else:
        judge_a = _with_reasoning(representative.judge, reasoning)
        if contested and tiebreak is None:
            tiebreak = contested[0].tiebreak

    return GradedItem(
        item=graded_item,
        rule=rule,
        gate=representative.gate,
        judge=judge_a,
        final_verdict=final,
        threshold=threshold,
        decided_by=representative.decided_by,
        assistant=config.assistant,
        finding_id=finding_id(config.run_id, item),
        error=decider.reasoning if final == "error" else "",
        repeats=tuple(runs) if passes > 1 else (),
        repeat_tally=dict(tally) if passes > 1 else {},
        judge2=representative.judge2,
        tiebreak=tiebreak,
        tiebreak_used=bool(contested),
        tiebreak_passes=len(contested),
    )


def grade_items(
    items: list[Item],
    config: RunConfig,
    provider: Provider,
    judge: Judge,
    rule_book: RuleBook,
    figure_book: FigureBook | None,
    on_progress=None,
) -> list[GradedItem]:
    """Grade every item. Order in equals order out."""

    def work(item: Item) -> GradedItem:
        graded = grade_item(item, config, provider, judge, rule_book, figure_book)
        if on_progress:
            on_progress(graded)
        return graded

    if config.concurrency <= 1:
        return [work(item) for item in items]
    with ThreadPoolExecutor(max_workers=config.concurrency) as pool:
        return list(pool.map(work, items))
