#!/usr/bin/env bash
# Confirms the four provider keys resolve and answer. Run under:
#   op run --env-file=secrets.op.env --no-masking -- harness/pipeline/check_keys.sh
set -u
ok=0
for k in BEDROCK_API_KEY OLLAMA_API_KEY ANTHROPIC_API_KEY OPENAI_API_KEY; do
  if [ -n "${!k:-}" ]; then echo "$k set"; ok=$((ok+1)); else echo "$k MISSING"; fi
done
[ "$ok" -eq 4 ] || exit 1
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
echo "bedrock  HTTP $(code -X POST https://bedrock-runtime.us-east-1.amazonaws.com/model/mistral.mistral-large-3-675b-instruct/converse -H "Authorization: Bearer $BEDROCK_API_KEY" -H 'Content-Type: application/json' -d '{"messages":[{"role":"user","content":[{"text":"hi"}]}],"inferenceConfig":{"maxTokens":5}}')  (want 200)"
echo "bedrock claude HTTP $(code -X POST https://bedrock-runtime.us-east-1.amazonaws.com/model/us.anthropic.claude-sonnet-4-6/converse -H "Authorization: Bearer $BEDROCK_API_KEY" -H 'Content-Type: application/json' -d '{"messages":[{"role":"user","content":[{"text":"hi"}]}],"inferenceConfig":{"maxTokens":3}}')  (want 200; 404 means the account has not submitted the Anthropic use-case form)"
echo "ollama   HTTP $(code https://ollama.com/api/tags -H "Authorization: Bearer $OLLAMA_API_KEY")  (want 200)"
echo "anthropic HTTP $(code https://api.anthropic.com/v1/models -H "x-api-key: $ANTHROPIC_API_KEY" -H 'anthropic-version: 2023-06-01')  (want 200)"
echo "openai   HTTP $(code https://api.openai.com/v1/models -H "Authorization: Bearer $OPENAI_API_KEY")  (want 200)"
