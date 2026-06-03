"""
OpenCode Zen client with model rotation + automatic fallback.

Routes all LLM calls through https://opencode.ai/zen/v1 (OpenAI-compatible).
On failure (rate limit, timeout, 5xx, JSON parse fail), rotates to next model
in the tier list. Tries free models last to preserve paid quota.

Free models on Zen (limited time, used as last-resort fallback):
- deepseek-v4-flash-free
- mimo-v2.5-free
- nemotron-3-super-free
- big-pickle-free
"""

import os
import json
import re
import time
import logging
from typing import Optional

import httpx

log = logging.getLogger("zen_client")

ZEN_BASE_URL = "https://opencode.ai/zen/v1"

# Tier list per agent. Order = priority. First one that succeeds wins.
# Paid/strong models first, free models last.

CLIP_FINDER_TIERS = [
    "claude-opus-4-6",         # best reasoning, expensive
    "claude-sonnet-4-6",       # strong, cheaper
    "gemini-3.1-pro",          # good reasoning
    "deepseek-v4-flash",       # fast reasoning
    "mimo-v2.5-free",          # free fallback (confirmed working)
    "deepseek-v4-flash-free",  # free fallback
    "big-pickle",              # free fallback
    "nemotron-3-super-free",   # free fallback
]

METADATA_TIERS = [
    "deepseek-v4-flash",       # fast, good enough for metadata
    "gemini-3.5-flash",        # free + fast
    "claude-sonnet-4-6",       # strong fallback
    "mimo-v2.5-free",          # free fallback (confirmed working)
    "deepseek-v4-flash-free",  # free fallback
    "big-pickle",              # free fallback
]

AGENT_TIERS = {
    "clip_finder": CLIP_FINDER_TIERS,
    "metadata_generator": METADATA_TIERS,
}

AGENT_PARAMS = {
    "clip_finder": {
        "temperature": 0.3,
        "max_tokens": 2000,
    },
    "metadata_generator": {
        "temperature": 0.4,
        "max_tokens": 4000,
    },
}

HARD_RULES = "CRITICAL: Output MUST be valid JSON array only. No markdown, no code fences, no explanation."

RETRY_STATUS_CODES = {408, 409, 413, 429, 500, 502, 503, 504, 529}
MAX_RETRIES_PER_MODEL = 2
REQUEST_TIMEOUT = 90.0


class ZenError(Exception):
    pass


class ZenAllModelsExhausted(ZenError):
    pass


def _api_key() -> str:
    key = (
        os.getenv("OPENCODE_API_KEY", "").strip()
        or os.getenv("OPENCODE_ZEN_API_KEY", "").strip()
    )
    if not key:
        raise ZenError(
            "OPENCODE_API_KEY (or OPENCODE_ZEN_API_KEY) not set. "
            "Add it to backend/.env (get a key at https://opencode.ai/auth)"
        )
    return key


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _is_retryable_error(err_str: str) -> bool:
    """
    Decide if a failure is transient (retry) or permanent (skip to next model).
    401/403 (auth/credits), 400 (bad request), 404 (not found) are NOT retryable —
    retrying the same model won't help. Rate limit, timeout, 5xx ARE retryable.
    """
    if "CreditsError" in err_str or "PaymentRequired" in err_str:
        return False
    if "ModelError" in err_str or "ModelNotFound" in err_str:
        return False
    if "InvalidRequest" in err_str or "BadRequest" in err_str:
        return False
    if "401" in err_str or "403" in err_str or "404" in err_str or "400" in err_str:
        return False
    for code in RETRY_STATUS_CODES:
        if str(code) in err_str:
            return True
    if "timeout" in err_str.lower():
        return True
    if "connection" in err_str.lower():
        return True
    return False


def _call_model(
    model: str,
    system_prompt: str,
    user_message: str,
    temperature: float,
    max_tokens: int,
) -> str:
    """
    Single model call. Returns raw text content. Raises on failure.
    """
    url = f"{ZEN_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt + "\n\n" + HARD_RULES},
            {"role": "user", "content": user_message},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
        resp = client.post(url, headers=headers, json=payload)

    if resp.status_code != 200:
        err_body = resp.text[:500]
        raise ZenError(f"HTTP {resp.status_code} from {model}: {err_body}")

    data = resp.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise ZenError(f"Malformed response from {model}: {e}")

    if not content or not content.strip():
        raise ZenError(f"Empty response from {model}")

    return _strip_code_fence(content)


def call_with_rotation(
    agent_key: str,
    system_prompt: str,
    user_message: str,
    parse_json: bool = True,
    extra_tiers: Optional[list] = None,
) -> dict:
    """
    Call LLM via OpenCode Zen with rotation through the agent's tier list.

    Returns parsed JSON dict if parse_json=True, else returns {"_raw": "text", "_model": "..."}.
    Raises ZenAllModelsExhausted if all tiers fail.
    """
    if agent_key not in AGENT_TIERS:
        raise ZenError(f"Unknown agent_key: {agent_key}")

    params = AGENT_PARAMS[agent_key]
    tiers = list(AGENT_TIERS[agent_key])
    if extra_tiers:
        tiers = tiers + [t for t in extra_tiers if t not in tiers]

    last_error = None
    attempted = []

    for model in tiers:
        for attempt in range(MAX_RETRIES_PER_MODEL):
            attempted.append(model)
            t0 = time.time()
            try:
                content = _call_model(
                    model=model,
                    system_prompt=system_prompt,
                    user_message=user_message,
                    temperature=params["temperature"],
                    max_tokens=params["max_tokens"],
                )
                elapsed = time.time() - t0
                log.info(
                    f"[zen] {agent_key} -> {model} OK ({elapsed:.1f}s, {len(content)} chars)"
                )

                if not parse_json:
                    return {"_raw": content, "_model": model}

                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, dict):
                        parsed["_model"] = model
                    elif isinstance(parsed, list):
                        parsed = {"_raw_list": parsed, "_model": model}
                    return parsed
                except json.JSONDecodeError as e:
                    log.warning(
                        f"[zen] {model} returned invalid JSON: {str(e)[:100]}. "
                        f"Retrying with stricter prompt..."
                    )
                    try:
                        retry_content = _call_model(
                            model=model,
                            system_prompt=system_prompt
                            + "\n\nCRITICAL: You MUST return ONLY valid JSON. No explanation, no markdown, no code fences.",
                            user_message=user_message,
                            temperature=0.1,
                            max_tokens=params["max_tokens"],
                        )
                        parsed = json.loads(retry_content)
                        if isinstance(parsed, dict):
                            parsed["_model"] = model
                        elif isinstance(parsed, list):
                            parsed = {"_raw_list": parsed, "_model": model}
                        return parsed
                    except Exception as retry_err:
                        last_error = f"{model}: invalid JSON: {e}; retry failed: {retry_err}"
                        break

            except Exception as e:
                elapsed = time.time() - t0
                err_str = str(e)
                last_error = f"{model}: {err_str[:200]}"
                log.warning(
                    f"[zen] {agent_key} -> {model} FAILED "
                    f"(attempt {attempt + 1}/{MAX_RETRIES_PER_MODEL}, {elapsed:.1f}s): {err_str[:200]}"
                )
                if not _is_retryable_error(err_str):
                    break
                time.sleep(1.0 * (attempt + 1))

    raise ZenAllModelsExhausted(
        f"All {len(tiers)} models failed for {agent_key}. "
        f"Last error: {last_error}. Attempted: {attempted}"
    )


def list_available_models() -> list:
    """Fetch the live Zen model catalog. Useful for /models command."""
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(
                f"{ZEN_BASE_URL}/models",
                headers={"Authorization": f"Bearer {_api_key()}"},
            )
        if resp.status_code == 200:
            data = resp.json()
            return [m.get("id", m) for m in data.get("data", [])]
    except Exception as e:
        log.warning(f"[zen] could not fetch model list: {e}")
    return []


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print("Zen model catalog:")
    models = list_available_models()
    for m in models[:20]:
        print(f"  - {m}")
    print(f"\nTotal: {len(models)} models")
