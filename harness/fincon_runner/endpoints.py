"""Raw HTTP calls to two model hosts, with no SDK.

`providers.py` needs these to get a reply; `judge.py` needs them to mark one.
Both live here so the request shape is written once.

Neither host needs a package: both are one POST with a bearer token. That keeps
the clone-and-run story in `harness/README.md` intact — the runner still has no
required dependency.

- **Bedrock** speaks the Converse API. One key covers every model in a region,
  so a run can move across vendors without a second credential.
- **Ollama Cloud** speaks its own `/api/chat`.

A key is read from the environment at call time and never written to a
transcript.
"""

from __future__ import annotations

import http.client
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request

BEDROCK_KEY = "BEDROCK_API_KEY"
OLLAMA_KEY = "OLLAMA_API_KEY"
DEFAULT_REGION = "us-east-1"
OLLAMA_URL = "https://ollama.com/api/chat"

# A fan-out across 20 models throttles. Retry the codes that clear on their own.
RETRYABLE = (408, 429, 500, 502, 503, 504)

# Ollama Cloud answers 429 with "usage limit" when the subscription's window is
# spent, not when a call is too fast. That clears in minutes to hours, not
# seconds, so such a call waits `USAGE_LIMIT_WAIT` seconds between tries, up to
# `USAGE_LIMIT_ATTEMPTS` times, before it is recorded as an error. Set
# FINCON_USAGE_LIMIT_WAIT=0 to disable the long wait.
# Both the session window ("session usage limit") and the monthly credit cap
# ("usage credits auto reload monthly max reached") are spent-budget answers,
# not throttling. Matched by these substrings, case-insensitively.
USAGE_LIMIT_MARKS = ("usage limit", "usage credits")
USAGE_LIMIT_MARK = USAGE_LIMIT_MARKS[0]  # kept for callers
USAGE_LIMIT_WAIT = int(os.environ.get("FINCON_USAGE_LIMIT_WAIT", "300"))
USAGE_LIMIT_ATTEMPTS = 24

# A plain throttle (HTTP 429 without the usage-limit message) gets its own,
# longer budget: some Bedrock models carry a per-minute quota that a 30-second
# backoff cannot outlast. Sleeps double from 2 s and are capped at 60 s.
THROTTLE_ATTEMPTS = int(os.environ.get("FINCON_THROTTLE_ATTEMPTS", "10"))
THROTTLE_MAX_SLEEP = 60.0


class EndpointError(RuntimeError):
    """A call that failed after its retry budget was spent."""


def _post(url: str, payload: dict, headers: dict, timeout: int) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _with_retries(call, attempts: int = 5, base: float = 2.0) -> dict:
    """Back off on throttling. Fail fast on anything a retry cannot fix."""
    last = ""
    limit_waits = 0
    throttles = 0
    attempt = 0
    while attempt < attempts:
        try:
            return call()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            last = f"HTTP {exc.code}: {detail}"
            if exc.code == 429 and any(m in detail.lower() for m in USAGE_LIMIT_MARKS) and USAGE_LIMIT_WAIT > 0:
                # The budget is spent. Wait it out; do not burn the retry budget.
                limit_waits += 1
                print(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} usage limit: waiting {USAGE_LIMIT_WAIT}s (wait {limit_waits}/{USAGE_LIMIT_ATTEMPTS}): {detail[:120]}", file=sys.stderr, flush=True)
                if limit_waits > USAGE_LIMIT_ATTEMPTS:
                    raise EndpointError(last) from None
                time.sleep(USAGE_LIMIT_WAIT + random.uniform(0, 15))
                continue
            if exc.code == 429 or "hrottl" in detail:
                # A throttle. Longer, capped backoff on its own counter, so a
                # per-minute quota does not exhaust the general retry budget.
                throttles += 1
                print(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} retry after HTTP {exc.code} throttle (attempt {throttles}/{THROTTLE_ATTEMPTS})", file=sys.stderr, flush=True)
                if throttles >= THROTTLE_ATTEMPTS:
                    raise EndpointError(last) from None
                time.sleep(min(THROTTLE_MAX_SLEEP, base * (2 ** (throttles - 1))) + random.uniform(0, 1.5))
                continue
            if exc.code not in RETRYABLE:
                raise EndpointError(last) from None
        except (
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
            # A host that closes the connection mid-body (IncompleteRead,
            # RemoteDisconnected) or resets it. All clear on a retry.
            http.client.HTTPException,
            ConnectionError,
        ) as exc:
            last = f"{type(exc).__name__}: {exc}"
        attempt += 1
        if attempt < attempts:
            time.sleep(base * (2 ** (attempt - 1)) + random.uniform(0, 1.5))
    raise EndpointError(last or "the call failed for an unknown reason")


def _require(name: str) -> str:
    key = os.environ.get(name)
    if not key:
        raise EndpointError(f"{name} is not set")
    return key


def bedrock_chat(
    model: str,
    system: str,
    user: str,
    max_tokens: int = 1024,
    temperature: float = 0.0,
    region: str = "",
    timeout: int = 180,
) -> tuple[str, int | None]:
    """One Converse call. Returns the text and the output token count.

    A model ID may carry its region as `model@region`, because a few models are
    hosted in one region only.
    """
    key = _require(BEDROCK_KEY)
    if "@" in model:
        model, _, suffix = model.partition("@")
        region = region or suffix
    region = region or DEFAULT_REGION
    payload: dict = {
        "messages": [{"role": "user", "content": [{"text": user}]}],
        "inferenceConfig": {"maxTokens": max_tokens, "temperature": temperature},
    }
    if system:
        payload["system"] = [{"text": system}]
    body = _with_retries(
        lambda: _post(
            f"https://bedrock-runtime.{region}.amazonaws.com/model/{model}/converse",
            payload,
            {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            timeout,
        )
    )
    blocks = body.get("output", {}).get("message", {}).get("content", []) or []
    # A reasoning model puts its thinking in a separate block. Take the text.
    text = "".join(block.get("text", "") for block in blocks if "text" in block)
    tokens = (body.get("usage") or {}).get("outputTokens")
    return text.strip(), tokens


def ollama_chat(
    model: str,
    system: str,
    user: str,
    max_tokens: int = 1024,
    temperature: float = 0.0,
    timeout: int = 300,
) -> tuple[str, int | None]:
    """One Ollama Cloud call. Returns the text and the output token count."""
    key = _require(OLLAMA_KEY)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})
    body = _with_retries(
        lambda: _post(
            OLLAMA_URL,
            {
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {"num_predict": max_tokens, "temperature": temperature},
            },
            {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            timeout,
        )
    )
    message = body.get("message") or {}
    text = (message.get("content") or "").strip()
    if not text and message.get("thinking"):
        # A thinking model spent the whole budget before the answer. Ask once
        # more with thinking off so the reply itself comes back; the earlier
        # fallback handed the thinking text to the parser, which never held
        # the JSON answer.
        body = _with_retries(
            lambda: _post(
                OLLAMA_URL,
                {
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    "think": False,
                    "options": {"num_predict": max_tokens, "temperature": temperature},
                },
                {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                timeout,
            )
        )
        message = body.get("message") or {}
        text = (message.get("content") or "").strip()
    return text, body.get("eval_count")
