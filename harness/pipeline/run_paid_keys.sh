#!/usr/bin/env bash
# Run the paid frontier models — Anthropic and OpenAI — that bedrock and
# ollama cannot reach, then leave the transcripts for build_outputs.py.
#
# The contestant list below is deliberately short and hand-picked, not read
# from a roster like score_contestants.sh. A model already reachable through bedrock
# or ollama (the Claude 4.x family, the GPT-OSS open weights) stays off this
# list on purpose — see harness/README.md, "Anthropic and OpenAI — only the
# models bedrock and ollama cannot reach". Re-adding one here would pay for a
# reply the free lane already produced.
#
# Anthropic runs 3 passes per item and OpenAI 1 (see
# harness/fincon_runner/providers.py, DEFAULT_REPEATS_BY_KIND) — paid
# frontier calls, unlike the 5 passes bedrock/ollama get, so this list should
# stay short.
#
# Append mode: an existing transcript gains only the probes it does not hold
# yet (`--append`). Permissions are read from the dataset row.
#
# Usage:
#   op run --env-file=secrets.op.env --no-masking -- \
#     harness/pipeline/run_paid_keys.sh <judge> [judge2] [tiebreak]
set -uo pipefail

cd "$(dirname "$0")/../.." || exit 1
mkdir -p logs submissions/runs

JUDGE="${1:?pass the judge spec, e.g. ollama:deepseek-v4-pro}"
JUDGE2="${2:-}"
TIEBREAK="${3:-}"
if [ -n "$JUDGE2" ] && [ -z "$TIEBREAK" ]; then echo "a second judge needs a tiebreak" >&2; exit 1; fi
JUDGE_FLAGS=(--judge "$JUDGE")
[ -n "$JUDGE2" ] && JUDGE_FLAGS+=(--judge2 "$JUDGE2" --tiebreak "$TIEBREAK")
DATASET="../datasets/benchmark-open.csv"
MAX_PARALLEL="${MAX_PARALLEL:-3}"

CONTESTANTS=(
  "anthropic:claude-opus-5"
  "anthropic:claude-sonnet-5"
  "anthropic:claude-fable-5"
  "openai:gpt-5.4"
  "openai:gpt-5.4-mini"
  "openai:gpt-5.4-nano"
)

echo "judge: $JUDGE${JUDGE2:+ + $JUDGE2, tiebreak $TIEBREAK}" >logs/paid-keys.log
echo "contestants: ${#CONTESTANTS[@]}" >>logs/paid-keys.log

slug() { echo "$1" | tr ':/@.' '----' | tr -cd 'A-Za-z0-9-'; }

# `wait -n` needs bash 4.3+. macOS ships bash 3.2 at /bin/bash, which errors
# on `-n` as an invalid option and spins forever instead of blocking. Batch
# by MAX_PARALLEL and `wait` for the whole batch instead — less overlap at a
# batch edge, but it works on every bash this runs on.
running=0
for contestant in "${CONTESTANTS[@]}"; do
  name="run-$(slug "$contestant")"
  (
    cd harness || exit 1
    python3 -m fincon_runner run \
      --dataset "$DATASET" \
      --assistant "$contestant" \
      --provider "$contestant" \
      "${JUDGE_FLAGS[@]}" \
      --append \
      --concurrency 2 \
      --run-id "$name" \
      --out ../submissions/runs \
      --quiet >>"../logs/${name}.log" 2>&1
    echo "done $contestant rc=$?" >>../logs/paid-keys.log
  ) &
  running=$((running + 1))
  if [ "$running" -ge "$MAX_PARALLEL" ]; then
    wait
    running=0
  fi
done
wait
echo "paid-key runs complete" >>logs/paid-keys.log
