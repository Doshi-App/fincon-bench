#!/usr/bin/env bash
# Phase 2: every Bedrock and Ollama Cloud contestant answers the open probes,
# and the judge panel marks every reply.
#
# Generation and marking happen in one pass per contestant, so one transcript
# holds both the reply and the verdict for each item — that is the audit record
# the leaderboard and the outputs CSV are both built from.
#
# Append mode. A contestant whose transcript already exists is not skipped and
# not overwritten: the runner grades only the probes the transcript does not
# hold yet and adds them (`--append`). Re-running this script after a partial
# run therefore finishes it. Contestants with no transcript at all are left
# out unless INCLUDE_NEW_CONTESTANTS=1, so a roster addition cannot start a
# full 275-probe run by surprise.
#
# Permissions are read from the dataset row. Do not add `--permissions none`.
#
# Usage:
#   op run --env-file=secrets.op.env --no-masking -- \
#     harness/pipeline/score_contestants.sh <judge> [judge2] [tiebreak]
# e.g.
#   ... score_contestants.sh ollama:deepseek-v4-pro ollama:glm-5.3-flash anthropic:claude-opus-5
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
MAX_PARALLEL="${MAX_PARALLEL:-4}"
INCLUDE_NEW_CONTESTANTS="${INCLUDE_NEW_CONTESTANTS:-0}"

# Every model the reachability probe cleared. Read from the roster so the two
# stages cannot drift apart.
mapfile -t CONTESTANTS < <(python3 -c "
import json
for r in json.load(open('results/roster.json')):
    if r['ok']:
        print(f\"{r['kind']}:{r['model']}\")
")

echo "judge: $JUDGE${JUDGE2:+ + $JUDGE2, tiebreak $TIEBREAK}" >logs/score-contestants.log
echo "contestants: ${#CONTESTANTS[@]}" >>logs/score-contestants.log

slug() { echo "$1" | tr ':/@.' '----' | tr -cd 'A-Za-z0-9-'; }

run_one() { # contestant concurrency
  local contestant="$1" concurrency="$2" name
  name="run-$(slug "$contestant")"
  if [ ! -f "submissions/runs/${name}/transcript.jsonl" ] && [ "$INCLUDE_NEW_CONTESTANTS" != "1" ]; then
    echo "skip $contestant (no prior run; set INCLUDE_NEW_CONTESTANTS=1 to add it)" >>logs/score-contestants.log
    return 0
  fi
  (
    cd harness || exit 1
    python3 -m fincon_runner run \
      --dataset "$DATASET" \
      --assistant "$contestant" \
      --provider "$contestant" \
      "${JUDGE_FLAGS[@]}" \
      --append \
      --concurrency "$concurrency" \
      --run-id "$name" \
      --out ../submissions/runs \
      --quiet >>"../logs/${name}.log" 2>&1
    echo "done $contestant rc=$?" >>../logs/score-contestants.log
  )
}

# Ollama Cloud throttles the whole subscription, and the two main judges live
# on it too; its contestants run after the other lanes, one at a time, at
# OLLAMA_CONCURRENCY (default 2).
OLLAMA_CONCURRENCY="${OLLAMA_CONCURRENCY:-2}"
OLLAMA_QUEUE=()
for contestant in "${CONTESTANTS[@]}"; do
  case "$contestant" in ollama:*) OLLAMA_QUEUE+=("$contestant"); continue;; esac
  # macOS bash 3.2 has no `wait -n`; poll instead of spinning.
  while [ "$(jobs -rp | wc -l)" -ge "$MAX_PARALLEL" ]; do sleep 5; done
  run_one "$contestant" "${BEDROCK_CONCURRENCY:-2}" &
done
wait

for contestant in "${OLLAMA_QUEUE[@]}"; do
  run_one "$contestant" "$OLLAMA_CONCURRENCY"
done
echo "score-contestants complete" >>logs/score-contestants.log
