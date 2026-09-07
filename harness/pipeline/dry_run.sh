#!/usr/bin/env bash
# A small end-to-end check before a leaderboard run: one contestant per lane,
# a few probes each, the lane's default pass count, judged by the judge (or
# judge panel) you are about to commit to. Prints every verdict and error so a
# broken key, a rejected parameter, or a throttled lane shows up on 12 rows,
# not 22,000.
#
#   op run --env-file=secrets.op.env --no-masking -- \
#     harness/pipeline/dry_run.sh <judge> [judge2] [tiebreak] [probes]
# e.g.
#   ... dry_run.sh ollama:deepseek-v4-pro ollama:glm-5.3-flash anthropic:claude-opus-5 3
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
JUDGE="${1:?pass the judge spec, e.g. ollama:deepseek-v4-pro}"
JUDGE2="${2:-}"
TIEBREAK="${3:-}"
PROBES="${4:-3}"
if [ -n "$JUDGE2" ] && [ -z "$TIEBREAK" ]; then echo "a second judge needs a tiebreak" >&2; exit 1; fi
JUDGE_FLAGS=(--judge "$JUDGE")
[ -n "$JUDGE2" ] && JUDGE_FLAGS+=(--judge2 "$JUDGE2" --tiebreak "$TIEBREAK")
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
      --assistant "$name" --provider "$c" "${JUDGE_FLAGS[@]}" --limit "$PROBES" \
      --concurrency 2 --run-id "$name" --out "../$OUT" --quiet ) >"$OUT/$name.log" 2>&1
  echo "== $c rc=$?"
  python3 - "$OUT/$name/transcript.jsonl" <<'PY'
import json, sys
def v(seat): return (seat or {}).get("verdict", "") or "-"
for line in open(sys.argv[1]):
    r = json.loads(line); j = r.get("judge", {})
    panel = ""
    if r.get("judge2") is not None:
        c = v(r.get("tiebreak")) if r.get("tiebreak_used") else "-"
        panel = (f" A={v(j)} B={v(r.get('judge2'))} C={c} "
                 f"tiebreak={'yes' if r.get('tiebreak_used') else 'no'}({r.get('tiebreak_passes', 0)} passes)")
    print(f"   {r['item']['item_id']}  final={r['final_verdict']:<6} perm={r.get('permissions','')}{panel} "
          f"repeats={len(r.get('repeats') or [])}  {(r.get('reasoning') or '')[:70]}")
    for p in r.get("repeats") or []:
        seats = [("A", p.get("judge")), ("B", p.get("judge2")), ("C", p.get("tiebreak"))]
        errs = [f"{k}: {(s or {}).get('reasoning','')[:90]}" for k, s in seats if s and s.get("verdict") == "error"]
        if p.get("final_verdict") == "error" or errs:
            print(f"      pass {p.get('run_index')}: final={p.get('final_verdict')} " + " | ".join(errs))
PY
done
echo "dry run written to $OUT"
