# Run of 2026-09-07 to 2026-09-09 (v1.2) — two judges, repeats, permissions from the row

The four CSVs in this directory now describe this run. Everything from "Run of
2026-08-13" downward describes the earlier run as it was, and is kept as history.

## What changed against the 2026-08-13 run

- **Judges.** Every reply is marked by two judges, `ollama:deepseek-v4-pro`
  (judge A) and `ollama:glm-5.3-flash` (judge B). When they agree, that is the
  verdict. When they disagree, `anthropic:claude-opus-5` marks the reply and
  decides. The choice and its cost are in `docs/judge-selection-2026-09-07.md`.
  1,975 of 36,533 passes (5.4 percent) needed the tiebreak. Two rows are
  self-graded and flagged: `deepseek-v4-pro` (judge A) and `claude-opus-5`
  (the tiebreak).
- **Probes.** 275 open probes, up from 191. The 84 added on 2026-09-01 (the
  pass-class rebalance, one compliant reply per category, jurisdiction and
  permission) were appended to every existing transcript; nothing was
  regenerated for the old 191.
- **Repeats.** The 84 new probes ran 5 passes on Bedrock and Ollama Cloud, 3 on
  the Anthropic API and 1 on the OpenAI API, with the majority verdict
  published and every pass kept under `repeats`. The 191 older probes keep
  their single 2026-08-13 reply. `leaderboard.csv` carries `repeated_items`,
  `pass_rate_mean` and `pass_rate_spread`: the pass rate of each repeat pass
  over the repeated items, its mean and its highest-minus-lowest spread (issue
  #30). Single-pass models have blanks there.
- **Permissions.** The 2026-08-13 run graded every reply under `--permissions
  none`, the 2-condition test, although 144 of the 275 dataset rows declare
  `investment_advice` in the system prompt the model actually saw. This run
  reads the permission from the row: 8,496 of the 16,225 model-item rows are
  graded under the 3-condition test.
- **The old rows were re-judged.** All 10,770 single-pass rows from 2026-08-13
  were marked again by the new judges on their stored reply, under the row's
  own permission, so the whole board is one judging scheme. 35 of those rows
  had no stored reply (an August 429 or an empty reply) and were regenerated.
- **Two new contestants.** `ollama:kimi-k3` and `bedrock:us.writer.palmyra-x5-v1:0`,
  both excluded in August for billing and rate limits, ran all 275 probes.

## The board

59 contestants: 35 through Bedrock, 18 through Ollama Cloud, 3 through the
Anthropic API, 3 through the OpenAI API. 3 same-weights pairs fold into 1 row
each, so `leaderboard.csv` holds 56 rows, 54 of them ranked. Pass rates on the
ranked rows run from 80.0 percent (`claude-sonnet-5`) to 58.6 percent
(`gpt-oss-20b`). `model_outputs.csv` carries all 16,225 model-item rows,
unmerged, with both judges' verdicts, the tiebreak verdict where it ran, the
`tiebreak` flag, the pass count and the number of contested passes.

Two rows are unranked, coverage under 80 percent, and neither is a result about
the model:

- **`bedrock:us.writer.palmyra-x5-v1:0` — 61 of 275 decided.** Bedrock returns
  HTTP 429 on most calls to this model on this account even at 1 or 2 in
  flight (issue #19). 214 rows never got a reply; a repair was stopped after it
  reached retry 5 of 10 on two thirds of the rows it tried.
- **`ollama:deepseek-v4-flash:preview` — 191 of 275 decided.** Ollama Cloud
  retired the tag on 2026-08-27 (HTTP 410), so the 84 new probes could not be
  answered. Its 191 August replies were re-judged and stand. `deepseek-v4-flash:0731`
  is the current tag and is ranked.

Three further caveats.

- **Two reasoning models return nothing on a few probes** within the
  1,024-token reply budget: `moonshot.kimi-k2-thinking` (1 row in error, 3 with
  an empty pass) and `openai.gpt-oss-20b-1:0` (4 rows in error, 5 with an empty
  pass). Regenerating them reproduces it. The rows stay as recorded and count
  against coverage; both remain ranked.
- **The cost and time columns from "Phase 4" are not carried for this run.**
  The transcripts now hold appended runs with mixed pass counts, so the
  wall-clock arithmetic behind `avg_time_s_1pass` no longer holds, and two new
  models have no published price. `avg_reply_tokens` is still computed.
- **Judge failures were never dropped.** Every pass where a judge seat failed
  for a reason other than the rubric (a spent Ollama usage window at 21:00 UTC
  on 2026-09-07, an exhausted monthly credit cap from 02:40 to 09:15 UTC on
  2026-09-09, concurrency throttles, malformed JSON) was re-run until it had a
  verdict or the failure was the contestant's own. The harness now waits out a
  spent budget instead of recording an error (`harness/fincon_runner/endpoints.py`).

## Cost and throughput

Contestant replies: about 22,400 new replies plus 35 regenerated August rows and
the 2 full new contestants. Judging: 70,574 judge A and B calls on the Ollama
Cloud subscription and 1,975 Opus 5 tiebreak calls, about $38 at list price.
Bedrock and the Anthropic and OpenAI contestant lanes came to roughly $35.

Ollama Cloud set the pace. Its account allows about 13 concurrent requests per
model, measured with a raw ramp during the run, and throughput saturates well
before that: a two-judge pass on a real reply costs about 13 seconds at 2 in
flight, dominated by GLM 5.3 Flash's thinking. The run took 43 hours wall
clock from 15:43 UTC on 2026-09-07, of which about 7 hours were the two Ollama
budget outages.

## Reproducing this run

`harness/pipeline/score_contestants.sh` and `run_paid_keys.sh` take the three
judge specs and append to existing transcripts; `harness/pipeline/rejudge_all.py`
re-judges a run's stored replies under new judges; `rejudge_errors.py --unresolved`
regenerates any row with a pass that reached no verdict; `build_outputs.py`
takes `--judge`, `--judge2` and `--tiebreak`. See `harness/README.md`.

---

# Run of 2026-08-13 (v1.1-preliminary) — judge selection, then the leaderboard

> **Superseded.** The CSVs in this directory now hold the 2026-09-07 to 09 run
> described above. This section is the record of the 2026-08-13 run as it was.
> Judge selection was re-run on 2026-09-07 on 424 labelled rows; see
> `docs/judge-selection-2026-09-07.md`.

## Read this before you quote a number

This run is preliminary. Three limits carry through every number below.

1. **One judge, one pass, no repeat.** Nothing here ran twice to measure
   variance.
2. **The judge is also a ranked contestant.**
   `bedrock:mistral.mistral-large-3-675b-instruct` won judge selection and then
   sat at rank 42 of 54 on the leaderboard it graded. That row carries
   `self_graded=yes` — see "Phase 2" below.
3. **The same weights scored 5.8 points apart on 2 inference providers.** Bedrock and Ollama
   Cloud served one identical model and disagreed by more than the gap between
   most neighbouring rows — see "Phase 2" below.

**Judge selection in this run cannot be reproduced or checked from outside.** It
rests on 100 hand-labelled rows that were never published and have since been
lost. The 2026-09-07 re-selection (note above) replaces it with 424 published
labels.

**This file is one run. `README.md` at the top level is the design.** The design
document uses illustrative figures (for example "5 candidate judges") that set
the shape of the benchmark, not a count any single run must match. Every figure
below is what this run actually did.

One overnight run of both phases. Four CSVs in this directory, plus the
per-run audit records under `submissions/`.

| File | What it holds |
|---|---|
| `judge_selection.csv` | Re-written 2026-09-07: 28 candidate judges scored against 424 labelled rows, plus 2 baselines, with bootstrap intervals. The 2026-08-13 table (17 judges, 100 rows) is in git history before commit `3041953`. |
| `model_outputs.csv` | 16,225 rows — one per model per probe: the probe, the reply, judge A's verdict (`judge_verdict`), judge B's (`judge2_verdict`), the tiebreak's where it ran (`tiebreak_verdict`), the `tiebreak` flag, the published verdict with the deciding judge's reasoning, the pass count (`repeats`) and the contested passes (`tiebreak_passes`). Rewritten by the 2026-09-07 to 09 run. |
| `leaderboard.csv` | 56 rows, 54 ranked by pass rate over the probes the judges decided. 3 rows each fold 2 provider runs of the same model into 1, averaged — see "Phase 2" below. Columns added by the 2026-09-07 to 09 run: `repeated_items`, `pass_rate_mean`, `pass_rate_spread`, and `judge` names all three seats. The "Phase 4" estimate columns `est_cost_usd_1pass` and `avg_time_s_1pass` are not carried for this run. |
| `category_breakdown.csv` | 840 rows (56 models × 15 failure categories), long format: the failure rate 1 model earned on 1 category. Same 3-row merge as `leaderboard.csv`, same rule — averaged, not pooled. Backs the website's model-by-category matrix. |
| `roster.json` | Every model the reachability probe tried, and why the 9 that failed did. |

### `leaderboard.csv` — the columns "Phase 4" adds, defined once

The cost and length columns are described in prose in "Phase 4" below; this table is the exact
definition, so a reader does not have to reconstruct it from that section on every visit.

| Column | Meaning | Caveat |
|---|---|---|
| `avg_reply_tokens` | Completion tokens for 1 reply, averaged over the model's decided probes. | From the runner's own token count for that call, not a third-party count — see `harness/README.md` for how the runner records it. |
| `est_cost_usd_1pass` | Estimated USD cost of 1 pass over the item set, at the pricing named in "Phase 4". | Confidence varies by row — real for OpenAI, list-price for Anthropic and most of Bedrock, a market-rate stand-in for Ollama Cloud, blank (not $0) for 3 Bedrock rows with no published rate. |
| `avg_time_s_1pass` | Wall-clock seconds ÷ (items × repeats), at the run's `--concurrency`. | Throughput at that concurrency, not 1 call's latency — see "Phase 4" for the arithmetic. |
| `self_graded` | `yes` if this row's model is also the judge that marked it. | A self-graded row is self-reported; the README's rule is that no assistant grades its own leaderboard row, so treat this flag as a caveat, not a disqualifier. |

## What ran

Both phases went through the existing runner (`harness/fincon_runner`). Two
providers were added to it — `bedrock:` and `ollama:` — because neither the
Anthropic nor the OpenAI key available had inference scope, so both providers
were reached through AWS Bedrock and Ollama Cloud instead for this run. Later
the same day, ordinary inference keys for both replaced them — see "Phase 3"
below for what they added.

So every model in phases 1 and 2 is reached through AWS Bedrock or Ollama
Cloud. The Claude 5 family is listed on Bedrock but not entitled on this
account, so the newest Anthropic models present *there* are Sonnet 4.6, Opus
4.5, Sonnet 4.5 and Haiku 4.5.

**Ollama Cloud is covered in full.** Its catalogue is 18 models — `/api/tags`
and the OpenAI-compatible `/v1/models` return the same 18, so that is the whole
hosted set, not a page of it. 17 of the 18 are on the leaderboard. Do not trust
a stale local cache of the model list for this: the cache on the machine used
for this run listed 21, and 2 of its extras (`kimi-k2.5`, `minimax-m2.5`) were
retired from Ollama Cloud on 2026-07-31. Both still exist on Bedrock and appear here
through that route instead. The much larger `ollama.com/library` is for models
pulled and run locally, which is a different thing from the hosted set — and not
an option on the machine used for this run, which has no GPU.

34 models come through Bedrock and 17 through Ollama Cloud.

## Phase 1 — the judge

Every candidate marked the same 100 hand-labelled rows through the `dataset`
provider, so the only thing that varied was the judge.

**Winner: `bedrock:mistral.mistral-large-3-675b-instruct`** — macro-F1 0.8194,
Cohen's kappa 0.639, MCC 0.640, coverage 0.97. The README picks the judge on
macro-F1, and it leads the field by 0.06 — Claude Sonnet 4.6 is second at
0.7606.

Read the headline next to three things.

- **The labels are lopsided: 92 fail to 8 pass.** A judge that answers `fail`
  every time scores 92 percent accuracy on this set. That degenerate judge is in
  the CSV as `baseline:always-fail`, scoring macro-F1 0.479 and kappa 0.000, so
  the trap is on the page rather than left implied. Kappa and MCC are reported
  because they are chance-corrected; accuracy alone would be misleading here.
- **Second place is better on the minority class.** Claude Sonnet 4.6 has the
  best balanced accuracy of any candidate (0.837 against Mistral's 0.801) and
  full coverage. Mistral wins the documented metric; Sonnet 4.6 is the better
  choice if catching the 8 `pass` rows matters more than macro-F1.
- **8 pass rows is a thin basis for the pass class.** Every pass-side number in
  `judge_selection.csv` rests on them. Labelling more pass rows would firm up
  the choice more than adding candidates would.

One candidate, `bedrock:nvidia.nemotron-super-3-120b`, was stopped after 28
minutes without finishing and is absent from the CSV.

## Phase 2 — the leaderboard

53 models answered the 191 open probes under `--permissions none` (the stricter
2-condition test), and the winning judge marked every reply. 51 ran cleanly; 3
same-model pairs across Bedrock and Ollama Cloud then fold into 1 row each (see
below), so the board holds 48 rows.

The 2 that did not run cleanly are absent from the board. Neither absence is a
result about the model.

- **`ollama:kimi-k3` — HTTP 402 on all 191 items.** "This model uses extra usage
  only (not included plan usage) and your extra usage balance is empty." It is
  billing, not capability: put credit on the Ollama account and it will run.
- **`bedrock:us.writer.palmyra-x5-v1:0` — HTTP 429 on 173 of 191 items**, twice,
  the second time at concurrency 2. It is rate-limited on this account.

Then three things to read the board with.

- **The judge is also a contestant.** `mistral.mistral-large-3-675b-instruct`
  carries `self_graded=yes`. The README says no assistant grades its own row, so
  treat that row as self-reported. It is rank 38 of the 48 rows in this phase,
  and rank 42 once phase 3 adds 6 more. It is mid-table, which is at least not
  the shape self-preference would take.
- **Pass rate uses only decided items**, and `coverage` says what share that was.
  Ranking needs coverage ≥ 0.80 so a thinly-graded model cannot outrank a fully
  graded one. Every ranked model here cleared 0.90. The leaderboard ranks by
  failure rate (1 − pass rate); the lowest failure rate is rank 1.
- **Same weights, 2 inference stacks, 1 row.** Mistral Large 3 675B answered
  every probe twice — once through Bedrock, once through Ollama Cloud, same
  probes, same judge, same prompt — and the 2 runs scored 5.8 points apart:
  65.4 percent through Bedrock, 59.6 through Ollama Cloud. Rather than publish
  that as 2 separately ranked rows, `harness/pipeline/build_outputs.py` folds an
  exact same-model pair like this into 1 row and averages the 2 rates: rank 38
  at 62.5 percent. Both sizes of GPT-OSS get the same treatment. The 5.8-point
  gap the average is built from is still worth reading as a caution — whatever
  separates 2 runs of the same weights (serving config, sampling defaults,
  quantisation) can be wider than the gap between neighbouring rows on this
  board, so a few adjacent places should read as noise, not a quality signal.
  A model that is *not* an exact match across providers (Minimax, for
  example, is a different point release on each inference provider) stays as 2 rows, because
  that is a different test, not the same model twice.

Top of the board: `minimax.minimax-m2.1` at 76.7 percent, then
`minimax.minimax-m2.5` at 75.1 and `moonshotai.kimi-k2.5` at 72.1. Bottom:
`nvidia.nemotron-nano-12b-v2` at 42.0.

The spread across 48 rows is 42 to 77 percent, and the frontier Anthropic and
DeepSeek models sit mid-table rather than on top. Before that is read as a
finding about model quality, note that it is one judge's opinion, that judge
agrees with the human labels at kappa 0.64 — substantial, not near-perfect — and
`datasets/benchmark-open.csv` is published, so no contamination claim is
being made. The honest summary is that the pipeline runs end to end and the
numbers are reproducible from the transcripts, not that the ordering is settled.

## Phase 3 — the paid keys, added the same day

Later on 2026-08-13, ordinary inference keys for Anthropic and OpenAI became
available. `harness/pipeline/run_paid_keys.sh`
then ran a short, hand-picked list of 6 models — 3 Anthropic, 3 OpenAI — using
the native `anthropic:` and `openai:` providers, judged by the same
`bedrock:mistral.mistral-large-3-675b-instruct`, 1 pass per item (the runner's
default for a paid frontier key — see `harness/README.md`, "Repeats").

The list was picked to cover 2 gaps phases 1 and 2 could not reach, not to
re-run anything already on the board:

- **The Claude 5 family — Opus 5, Sonnet 5, Fable 5.** `results/roster.json`
  shows all 3 came back HTTP 403 on Bedrock ("not available for this
  account"). The native Anthropic key is the only lane that reaches them.
- **OpenAI's own hosted chat models — GPT-5.4, GPT-5.4 Mini, GPT-5.4 Nano.**
  Bedrock's `openai.*` entries are the open-weight GPT-OSS line, a different
  artifact from the same company. Neither had run before.

All 6 finished cleanly (191 items each, 0 errors, coverage ≥ 0.98) and now
hold their own rows — `leaderboard.csv` went from 48 rows to 54. One result
worth flagging rather than quietly leaving in the CSV: **Claude Sonnet 5 (rank
3, 74.6 percent) beats Claude Opus 5 (rank 19, 67.7 percent) by 7 points**,
same generation, same judge, same day. That is either a real result — the
smaller model is better-calibrated on this rubric — or a sign that 1 pass per
model is too thin to trust a 7-point gap. Phase 3 ran once per item, same as
every paid-key run so far; nothing here re-runs it to check.

The spread across all 54 rows is still 42 to 77 percent — the 6 new rows
landed inside the existing range, at ranks 3, 19, 26, 41, 43 and 48, not at
either end.

## Phase 4 — cost and time, retrospective

`harness/pipeline/estimate_cost.py` added 2 columns to `leaderboard.csv` after
the fact: `est_cost_usd_1pass` and `avg_time_s_1pass`. Both are normalized to
1 pass per item, even for the `bedrock`/`ollama` rows that actually ran 10 —
divide their real spend and wall-clock by 10 to get a number that means the
same thing as every other row.

Read the note column in the script's `PRICING` table before quoting any 1
row — confidence varies a lot across it:

- **Real, not estimated, for OpenAI.** `gpt-5.4`, `gpt-5.4-mini` and
  `gpt-5.4-nano` are priced from this org's own August 2026 cost report
  (`/v1/organization/costs`), not a list price. `gpt-5.4-mini`'s run was the
  only usage under its cost-report bucket that day, so its cost is fully
  verified: input and output token counts there matched this repo's own
  transcript exactly.
- **First-party list price for Anthropic and most of Bedrock.** Anthropic's
  own pricing page, and AWS's own Bedrock pricing page (or, where a specific
  point release wasn't listed there, an AWS launch blog or AWS Marketplace
  listing for that exact model).
- **No price exists for 3 Bedrock rows.** `qwen.qwen3-coder-480b-a35b-v1:0`,
  `us.meta.llama3-1-70b-instruct-v1:0` and `us.meta.llama4-scout-17b-instruct-v1:0`
  have no published on-demand rate anywhere checked. Their cost cell is
  blank, not a guess.
- **Ollama Cloud bills by subscription, not by token** (Free / Pro $20/mo /
  Max $100/mo / Team, at ollama.com/pricing) — usage counts against a plan's
  limits by a 1–4 "usage level" per model, with no published per-token rate.
  So the 17 Ollama rows carry a different kind of number: what the *same
  open-weight model* costs per token on a normal first-party or well-known
  third-party API (DeepSeek, Z.ai, Moonshot, MiniMax, DeepInfra, OpenRouter,
  DashScope, or — for the 3 weights that are also on Bedrock — Bedrock's own
  rate). That is a market-rate stand-in for "what this would cost off
  Ollama," not what the Ollama Cloud run itself billed, which was $0
  marginal inside a subscription. Several of these come from a third-party
  aggregator rather than the vendor's own page — the script's `note` field
  says "low-confidence source" wherever that's true.
- **Input tokens are always an estimate, for every row.** The runner never
  records what a provider billed for the prompt (see `harness/README.md`),
  so every row's input-token count is 1 estimate applied uniformly — 237.6
  tokens/item, from `tiktoken`'s `cl100k_base` encoding over the dataset's
  own `system_prompt` + `probe` text. Checked once against a real number
  (OpenAI's cost report for `gpt-5.4-mini`: 47,733 real vs 45,389 estimated,
  5 percent low) — a plausible size of error to carry across every row, not
  a bound on it.

**Total, all 54 rows, 1 pass each: $22.63.** The 6 phase-3 paid-key models
alone: $12.53 — $11.11 of that is the 3 Anthropic models, $1.42 the 3 OpenAI
ones, because Claude Opus 5 and Claude Fable 5 both charge $25 and $50 per
million output tokens against GPT-5.4's $15. Cheapest row: Bedrock's `us.amazon.nova-lite-v1:0` at $0.008, with 3 more
under $0.02 (`google.gemma-3-12b-it`, `zai.glm-4.7-flash`,
`nvidia.nemotron-nano-12b-v2`). Most expensive: `claude-fable-5`
at $5.82, ahead of `claude-opus-5` at $4.23 — Fable 5's own list price
($10/$50 per million) is double Opus 5's ($5/$25), so it costs more here
despite writing a shorter average reply.

`avg_time_s_1pass` is wall-clock ÷ (items × repeats) for that run, at
whatever `--concurrency` the run used (4 for phase 3, 6 for phases 1–2) — it
is throughput, not 1 call's true latency. At concurrency 6, a model that
takes 1.6s of wall-clock per pass is really answering in something nearer
6 × 1.6 ≈ 10s per call if the run stayed fully parallel; read the column as
"how fast this made the leaderboard happen," not as a latency benchmark.

Reproduce it: `python3 harness/pipeline/estimate_cost.py` (no key, no
network — it reads `submissions/runs/*/run.json` and
`results/model_outputs.csv`, both already in this repo).

## Reproducing it

Each provider reads its key from the environment. Export the keys, then run the
scripts in order.

```bash
export BEDROCK_API_KEY=...   # phases 1 and 2, and the judge
export OLLAMA_API_KEY=...    # the Ollama Cloud contestants
export ANTHROPIC_API_KEY=... # phase 3 only
export OPENAI_API_KEY=...    # phase 3 only

python3 harness/pipeline/probe_models.py
bash harness/pipeline/select_judge.sh
python3 harness/pipeline/score_judges.py submissions/judges/judge-*/transcript.jsonl

bash harness/pipeline/score_contestants.sh bedrock:mistral.mistral-large-3-675b-instruct

# Phase 3 — the 6 models bedrock and ollama cannot reach.
bash harness/pipeline/run_paid_keys.sh bedrock:mistral.mistral-large-3-675b-instruct

python3 harness/pipeline/build_outputs.py submissions/runs/run-*/transcript.jsonl \
  --judge bedrock:mistral.mistral-large-3-675b-instruct
```

Bedrock uses region `us-east-1` unless a model ID names its own region as
`model@region`.

**Phase 1 reads `harness/pipeline/human-labels.csv`**, which is gitignored; copy
`harness/pipeline/human-labels-claude.csv` (the 424 published labels) to that
path first. The 2026-08-13 selection used a 100-row file that was never
published and is lost, so that choice of judge cannot be re-derived; the
2026-09-07 selection can.

### If you use 1Password

`secrets.op.env` holds `op://` references only, so it carries no secret. Point
`op run` at it and drop the `export` lines:

```bash
op run --env-file=secrets.op.env --no-masking -- python3 harness/pipeline/probe_models.py
```
