"""
Groq client with 4-key rotation + automatic model fallback.

Routes all LLM calls through https://api.groq.com/openai/v1 (OpenAI-compatible).
On failure (rate limit, timeout, 5xx, JSON parse fail), rotates to next key
or next model in the fallback list.

Available Groq models (June 2026):
- meta-llama/llama-4-scout-17b-16e-instruct  (primary, 17B MoE, 128K context)
- llama-3.3-70b-versatile                    (fallback 1, 70B dense)
- llama-3.1-8b-instant                       (fallback 2, fast)
- meta-llama/llama-4-maverick-17b-128e-instruct (fallback 3)
"""

import os
import json
import re
import time
import logging
import itertools
from typing import Optional

from groq import Groq

log = logging.getLogger("groq_client")

GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# Tier list per agent. Order = priority. First one that succeeds wins.
# Within a tier, we rotate across API keys to spread rate limit.

CLIP_FINDER_TIERS = [
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "llama-3.3-70b-versatile",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "llama-3.1-8b-instant",
]

METADATA_TIERS = [
    "llama-3.3-70b-versatile",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "llama-3.1-8b-instant",
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

RETRY_STATUS_CODES = {408, 409, 413, 429, 500, 502, 503, 504}
MAX_RETRIES_PER_MODEL = 2
REQUEST_TIMEOUT = 90.0


class ZenError(Exception):
    pass


class ZenAllModelsExhausted(ZenError):
    pass


_api_keys = []
_key_cycle = None


def _load_keys():
    """Load all GROQ_API_KEY* from env. Raises ZenError if none found."""
    global _api_keys, _key_cycle
    primary = os.getenv("GROQ_API_KEY", "").strip()
    if primary and primary != "your_new_groq_api_key_here":
        _api_keys.append(primary)
    for i in range(2, 10):
        k = os.getenv(f"GROQ_API_KEY_{i}", "").strip()
        if k and k != "your_new_groq_api_key_here":
            _api_keys.append(k)
    if not _api_keys:
        raise ZenError(
            "No GROQ_API_KEY found. Set GROQ_API_KEY in backend/.env"
        )
    _key_cycle = itertools.cycle(range(len(_api_keys)))
    log.info(f"[groq] loaded {len(_api_keys)} API keys")


def _next_key_idx() -> int:
    global _key_cycle
    if _key_cycle is None:
        _load_keys()
    return next(_key_cycle)


def _get_client() -> Groq:
    if not _api_keys:
        _load_keys()
    return Groq(api_key=_api_keys[_next_key_idx()])


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _is_retryable_error(err_str: str) -> bool:
    """
    Decide if a failure is transient (retry) or permanent (skip to next model).
    401/403 (auth), 400 (bad request), 404 (not found) are NOT retryable —
    retrying the same model won't help. Rate limit, timeout, 5xx ARE retryable.
    """
    if "401" in err_str or "403" in err_str:
        return False
    if "400" in err_str and "rate_limit" not in err_str.lower():
        return False
    if "404" in err_str or "model_not_found" in err_str.lower():
        return False
    if "invalid_api_key" in err_str.lower():
        return False
    for code in RETRY_STATUS_CODES:
        if str(code) in err_str:
            return True
    if "rate" in err_str.lower() and "limit" in err_str.lower():
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
    client = _get_client()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt + "\n\n" + HARD_RULES},
            {"role": "user", "content": user_message},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=REQUEST_TIMEOUT,
    )
    try:
        content = response.choices[0].message.content
    except (KeyError, IndexError, AttributeError) as e:
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
    Call LLM via Groq with rotation through the agent's tier list.
    Within a tier, rotates across API keys to spread rate limit.

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
                    f"[groq] {agent_key} -> {model} OK ({elapsed:.1f}s, {len(content)} chars)"
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
                        f"[groq] {model} returned invalid JSON: {str(e)[:100]}. "
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
                    f"[groq] {agent_key} -> {model} FAILED "
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
    """Fetch the live Groq model catalog."""
    try:
        client = _get_client()
        response = client.models.list()
        return [m.id for m in response.data]
    except Exception as e:
        log.warning(f"[groq] could not fetch model list: {e}")
    return []


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print("Groq model catalog:")
    models = list_available_models()
    for m in models[:20]:
        print(f"  - {m}")
    print(f"\nTotal: {len(models)} models")
