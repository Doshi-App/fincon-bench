#!/usr/bin/env bash
# A small end-to-end check before a leaderboard run: one contestant per lane,
# a few probes each, the lane's default pass count, judged by the judge you
# are about to commit to. Prints every verdict and error so a broken key, a
# rejected parameter, or a throttled lane shows up on 12 rows, not 22,000.
#
#   op run --env-file=secrets.op.env --no-masking -- harness/pipeline/dry_run.sh <judge-spec> [probes]
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
JUDGE="${1:?pass the judge spec, e.g. ollama:deepseek-v4-pro}"
PROBES="${2:-3}"
OUT="submissions/dry-runs/$(date +%Y%m%d-%H%M%S)"
CONTESTANTS=(
  "bedrock:mistral.mistral-large-3-675b-instruct"
  "ollama:glm-5.2"
  "anthropic:claude-sonnet-5"
  "openai:gpt-5.4-mini"
)
harness/pipeline/check_keys.sh || exit 1
mkdir -p "$OUT"
for c in "${CONTESTANTS[@]}"; do
  name="dry-$(echo "$c" | tr ':/@.' '----' | tr -cd 'A-Za-z0-9-')"
  ( cd harness && python3 -m fincon_runner run --dataset ../datasets/benchmark-open.csv \
      --assistant "$name" --provider "$c" --judge "$JUDGE" --limit "$PROBES" \
      --concurrency 2 --run-id "$name" --out "../$OUT" --quiet ) >"$OUT/$name.log" 2>&1
  echo "== $c rc=$?"
  python3 - "$OUT/$name/transcript.jsonl" <<'PY'
import json, sys
for line in open(sys.argv[1]):
    r = json.loads(line); j = r.get("judge", {})
    print(f"   {r['item']['item_id']}  final={r['final_verdict']:<6} judge={j.get('verdict','')!s:<6} "
          f"repeats={len(r.get('repeats') or [])}  {(j.get('reasoning') or '')[:80]}")
PY
done
echo "dry run written to $OUT"
