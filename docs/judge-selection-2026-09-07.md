# Judge selection, 2026-09-07: what it cost, what broke, what to do before the leaderboard run

Branch `ven/pass-class`. Results in `results/judge_selection.csv`; transcripts under `submissions/judges/`.

## What ran

| Quantity | Value |
|---|---|
| Labelled rows | 424 (258 pass, 166 fail): 274 hand-written rows labelled by two blind passes, 150 model-written replies labelled and blind-checked |
| Candidate judges | 28: 14 Bedrock, 9 Ollama Cloud, 3 Anthropic direct, 2 OpenAI direct |
| Judge calls | about 12,300, including 500 re-judged rows |
| Leader | `ollama:deepseek-v4-pro`, macro-F1 0.958, interval 0.94 to 0.98, coverage 1.00 |
| Inside the leader's interval | claude-opus-5, gpt-5.6-terra, claude-sonnet-5, glm-5.3-flash |
| Published judge (mistral-large-3) | rank 17, macro-F1 0.924 |

## What it cost

Input tokens are estimated from a 20-prompt sample counted on Anthropic's tokenizer (about 2,240 tokens per judge prompt) and OpenAI's reported usage (about 1,275). Output tokens are the providers' own counts from the transcripts. Rates: Anthropic and OpenAI list prices; Bedrock rates from `harness/pipeline/estimate_cost.py`. Ollama Cloud is a flat subscription and is not metered here.

| Lane | Judges | Metered cost |
|---|---|---|
| Anthropic direct (Opus 5, Sonnet 5, Opus 4.8) | 3 | about $17 |
| Bedrock (14 models) | 14 | about $21, of which the four Claude models are $15 |
| OpenAI direct (GPT-5.6 Terra, Luna) | 2 | about $2 |
| Ollama Cloud | 9 | subscription |
| Total metered | | about $40 |

Per judge, 424 rows: Opus 5 $7.80, Opus 4.5 on Bedrock $6.50, Sonnet 5 $3.20, GPT-5.6 Terra $1.75, DeepSeek V4 Pro $0 metered, most other Bedrock models under $1.

## Projection for the leaderboard run

Passes per item are now 5 on Bedrock and Ollama Cloud, 3 on Anthropic, 1 on OpenAI (`harness/fincon_runner/providers.py`). The published rows were single-pass.

| Work | Contestant calls | Judge calls |
|---|---|---|
| 84 new open probes, 57 contestants | 34 Bedrock × 84 × 5 = 14,280; 17 Ollama × 84 × 5 = 7,140; 3 Anthropic × 84 × 3 = 756; 3 OpenAI × 84 = 252. Total about 22,400 | same, about 22,400 |
| Re-judge the 10,887 existing rows with the new judge | 0 | 10,887 |
| Total judge calls | | about 33,300 |

Judge cost at 33,300 calls, using this run's per-call rates: DeepSeek V4 Pro on Ollama Cloud, subscription only; GLM 5.3 Flash, subscription only; Sonnet 5 about $250; Opus 5 about $610; GPT-5.6 Terra about $135. Contestant cost is dominated by Bedrock and is roughly 1.6 times the 2026-08-13 run's Bedrock spend, since 84 probes at 5 passes is 420 replies per model against 191 before.

## What went wrong, and the fix that is now in place

1. **Ollama Cloud throttles the subscription, not the model.** Five judges at six concurrent requests lost 159 rows to HTTP 429. Fix: `select_judge.sh` runs Ollama judges after the other lanes, one at a time, at `OLLAMA_CONCURRENCY` (default 2). `score_contestants.sh` does the same for Ollama contestants.
2. **The Bedrock key's account had not submitted the Anthropic use-case form.** All four Bedrock Claude judges returned HTTP 404 on every row. Fix: `check_keys.sh` now calls a Claude model on Bedrock, not only Mistral. The Engineering "AWS Bedrock API (Prototype: Tooling)" key is the one with access.
3. **The OpenAI organisation had no credits**, and the OpenAI lane sent `max_tokens` and `temperature`, which GPT-5.6 rejects. Fix: the lane sends `max_completion_tokens` and drops `temperature` on the specific 400s; check the billing page before a run.
4. **Output caps cut thinking models off before the verdict.** The Anthropic lane allowed 1,024 tokens and the Ollama and Bedrock lanes 4,096; Opus 5, Sonnet 5, GLM 5.3 and GLM 5.3 Flash returned empty or truncated JSON. Fix: both caps are 8,192.
5. **The JSON extractor was greedy.** It matched from the first brace to the last, so a judge that added a sentence after its answer failed to parse. Fix: balanced-object extraction, first object carrying a `verdict` wins.
6. **Thinking-only replies on Ollama were fed to the parser.** When the reply was empty the lane passed the thinking text on. Fix: one retry with `think: false`.
7. **Silent rows flattered judges.** Rows a judge could not answer were dropped from its score. Once every such row was re-run, Opus 5 fell from 0.954 to 0.947 and GLM 5.3 Flash from 0.952 to 0.941; the skipped rows were the hard ones. Fix: `rejudge_errors.py` re-runs failed rows in place, transport failures by default and judge-output failures with `--include-judge-output` after a harness fix; the transcript keeps the judge's raw text on every unread verdict.
8. **Editing a running shell script.** `select_judge.sh` was edited while a run had it open, and bash tripped on the changed bytes after the last judge finished. No verdict was lost. Rule: do not edit a `.sh` file while a run of it is live; Python files are safe because they are imported at start.
9. **macOS bash 3.2 has no `wait -n`.** The throttle loop spun instead of blocking. Fix: poll with `sleep`.
10. **The 1Password session lapsed mid-run.** `op run` injects keys at launch, so live runs were unaffected, but later re-judge passes failed until the app was unlocked. Rule: unlock 1Password before starting a batch and keep the app open.
11. **The repeat default was documented but never run.** The README said 10 passes; the published rows were 1. Fix: the README carries a history note, and `run.json` records the count per run.

## Before the leaderboard run

1. Pick the judge (separate conversation; criteria in memory: reliability, then running cost, possibly two judges with one from a cheap lane).
2. Unlock 1Password. Run `op run --env-file=secrets.op.env --no-masking -- harness/pipeline/check_keys.sh` and expect four `set` lines and four HTTP 200s, including the Bedrock Claude call.
3. Dry run: `op run --env-file=secrets.op.env --no-masking -- harness/pipeline/dry_run.sh <judge-spec>`. It sends 3 probes to one contestant per lane at the lane's default pass count, judges them, and prints every verdict and error. Expect zero errors and a `repeats` block on the Bedrock, Ollama and Anthropic rows.
4. Add an append mode to the contestant run so the 84 new probes join the existing 191-row transcripts instead of overwriting them. `score_contestants.sh` today skips a contestant whose transcript exists. This is the one piece of harness work still open.
5. Run Bedrock, Anthropic and OpenAI contestants in parallel, then Ollama contestants back to back. Watch `logs/` for 429s and re-judge with `rejudge_errors.py` before scoring.
6. Drop the `--permissions none` override in `score_contestants.sh`. The 2026-08-13 run graded every reply under the 2-condition test even where the system prompt declared a regulated bank with advice permission. Every dataset row now carries the permission that matches its prompt, so the grader should read it from the row.
7. Re-judge the existing 10,887 rows with the chosen judge if it is not Mistral Large 3, so the leaderboard has one judge throughout.
