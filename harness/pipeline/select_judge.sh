#!/usr/bin/env bash
# Phase 1: every candidate judge marks the human-labelled rows.
#
# The provider is `dataset`, so every candidate reads the same pre-written
# replies and the only thing that varies is the judge.
#
# The rows are the ones in harness/pipeline/human-labels.csv, whatever their
# item_id. An earlier version ran `--limit 100` because the first 100 rows by
# item_id happened to be the labelled ones. That tied selection to file order,
# and it would have let any unlabelled row that later landed in the first 100
# (the 120 model-written rows, for one) into the judge set without a label. The
# labels file is now the only thing that decides which rows count.
#
# Run under: op run --env-file=secrets.op.env --no-masking -- harness/pipeline/select_judge.sh
set -uo pipefail

cd "$(dirname "$0")/../.." || exit 1
mkdir -p logs submissions/judges

LABELS="harness/pipeline/human-labels.csv"
LABELLED_SET="submissions/judges/labelled-rows.csv"

if [ ! -f "$LABELS" ]; then
  echo "No $LABELS. Judge selection needs the hand labels; see results/README.md." >&2
  exit 1
fi

# The subset of meta-eval.csv that carries a human label, in the same schema.
python3 - "$LABELS" "$LABELLED_SET" <<'PY'
import csv, sys
labels_path, out_path = sys.argv[1], sys.argv[2]
with open(labels_path, newline="", encoding="utf-8") as fh:
    labelled = {r["item_id"].strip() for r in csv.DictReader(fh)
                if r.get("human_label", "").strip().lower() in ("pass", "fail")}
with open("datasets/meta-eval.csv", newline="", encoding="utf-8") as fh:
    reader = csv.DictReader(fh)
    rows = [r for r in reader if r["item_id"].strip() in labelled]
    fields = reader.fieldnames
missing = labelled - {r["item_id"].strip() for r in rows}
if missing:
    sys.exit(f"{len(missing)} labelled item_ids are not in datasets/meta-eval.csv: {sorted(missing)[:10]}")
with open(out_path, "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=fields); w.writeheader(); w.writerows(rows)
print(f"{len(rows)} labelled rows -> {out_path}")
PY
[ $? -eq 0 ] || exit 1

CANDIDATES=(
  "bedrock:us.anthropic.claude-opus-4-5-20251101-v1:0"
  "bedrock:us.anthropic.claude-sonnet-4-6"
  "bedrock:us.anthropic.claude-sonnet-4-5-20250929-v1:0"
  "bedrock:us.anthropic.claude-haiku-4-5-20251001-v1:0"
  "bedrock:deepseek.v3.2"
  "bedrock:qwen.qwen3-235b-a22b-2507-v1:0@us-west-2"
  "bedrock:zai.glm-5"
  "bedrock:moonshotai.kimi-k2.5"
  "bedrock:mistral.mistral-large-3-675b-instruct"
  "bedrock:openai.gpt-oss-120b-1:0"
  "bedrock:minimax.minimax-m2.5"
  "bedrock:us.meta.llama4-maverick-17b-instruct-v1:0"
  "bedrock:us.amazon.nova-pro-v1:0"
  "bedrock:nvidia.nemotron-super-3-120b"
  "ollama:deepseek-v4-pro"
  "ollama:qwen3.5:397b"
  "ollama:nemotron-3-ultra"
  "ollama:glm-5.2"
)

MAX_PARALLEL=5

slug() { echo "$1" | tr ':/@.' '----' | tr -cd 'A-Za-z0-9-'; }

for candidate in "${CANDIDATES[@]}"; do
  while [ "$(jobs -rp | wc -l)" -ge "$MAX_PARALLEL" ]; do wait -n; done
  name="judge-$(slug "$candidate")"
  (
    cd harness || exit 1
    python3 -m fincon_runner run \
      --dataset "../$LABELLED_SET" \
      --assistant "hand-written-replies" \
      --provider dataset \
      --judge "$candidate" \
      --concurrency 6 \
      --run-id "$name" \
      --out ../submissions/judges \
      --quiet >"../logs/${name}.log" 2>&1
    echo "done $candidate rc=$?" >>../logs/select-judge.log
  ) &
done
wait
echo "select-judge complete" >>logs/select-judge.log
