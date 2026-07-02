"""
AI Provider — multi-provider LLM routing, failover, and token tracking.

Routes calls across Groq, NVIDIA, and optionally Anthropic with task-based
intelligent routing, automatic failover, and per-call token tracking.
"""
import asyncio
import json
import re
import time
from collections import defaultdict
from datetime import date
from itertools import cycle
from typing import Optional
from loguru import logger
import httpx
from config import settings


# ══════════════════════════════════════════════════════════════
#  PROVIDER REGISTRY
# ══════════════════════════════════════════════════════════════

_PROVIDERS = {
    "groq": {
        "api": "openai",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "key": lambda: settings.GROQ_API_KEY,
        "model": lambda: settings.GROQ_MODEL,
        "rpm": 30,
        "cost_per_1k_input": 0.0,
        "cost_per_1k_output": 0.0,
    },
    "nvidia": {
        "api": "openai",
        "url": "https://integrate.api.nvidia.com/v1/chat/completions",
        "key": lambda: settings.NVIDIA_API_KEY,
        "model": lambda: settings.NVIDIA_MODEL,
        "rpm": 20,
        "cost_per_1k_input": 0.0,
        "cost_per_1k_output": 0.0,
    },
    "anthropic": {
        "api": "anthropic",
        "url": "https://api.anthropic.com/v1/messages",
        "key": lambda: settings.ANTHROPIC_API_KEY,
        "model": lambda: settings.ANTHROPIC_MODEL,
        "rpm": 50,
        "cost_per_1k_input": 0.003,
        "cost_per_1k_output": 0.015,
    },
}

TASK_ROUTING = {
    "json_extract": ["groq", "nvidia"],
    "freeform": ["groq", "nvidia"],
    "reasoning": ["anthropic", "groq", "nvidia"],
    "scoring": ["groq", "nvidia"],
    "conversation": ["groq", "nvidia", "anthropic"],
}


def _available_providers() -> list[str]:
    available = []
    for name, cfg in _PROVIDERS.items():
        try:
            key = cfg["key"]()
            if key and key.strip() and not key.startswith("your_"):
                available.append(name)
        except Exception:
            pass
    return available


_provider_cycle = None
_call_counts: dict[str, list[float]] = {}


def _next_provider(task_type: str | None = None) -> str:
    global _provider_cycle
    available = _available_providers()
    if not available:
        raise RuntimeError("No AI providers configured. Set GROQ_API_KEY or NVIDIA_API_KEY in .env")

    if task_type and task_type in TASK_ROUTING:
        preferred = [p for p in TASK_ROUTING[task_type] if p in available]
        if preferred:
            now = time.time()
            for name in preferred:
                if name not in _call_counts:
                    _call_counts[name] = []
                _call_counts[name] = [t for t in _call_counts[name] if now - t < 60]
                rpm = _PROVIDERS[name].get("rpm", 20)
                if len(_call_counts[name]) < rpm:
                    _call_counts[name].append(now)
                    return name
            return preferred[0]

    if len(available) == 1:
        return available[0]

    if _provider_cycle is None:
        _provider_cycle = cycle(available)

    now = time.time()
    for _ in range(len(available)):
        name = next(_provider_cycle)
        if name not in _call_counts:
            _call_counts[name] = []
        _call_counts[name] = [t for t in _call_counts[name] if now - t < 60]
        rpm = _PROVIDERS[name].get("rpm", 20)
        if len(_call_counts[name]) < rpm:
            _call_counts[name].append(now)
            return name

    return min(available, key=lambda n: len(_call_counts.get(n, [])))


# ══════════════════════════════════════════════════════════════
#  TOKEN / COST TRACKING
# ══════════════════════════════════════════════════════════════

_daily_usage: dict[str, dict] = defaultdict(lambda: {
    "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0,
})


def _track_usage(provider: str, input_tokens: int, output_tokens: int):
    today = date.today().isoformat()
    key = f"{today}:{provider}"
    _daily_usage[key]["calls"] += 1
    _daily_usage[key]["input_tokens"] += input_tokens
    _daily_usage[key]["output_tokens"] += output_tokens
    cfg = _PROVIDERS.get(provider, {})
    cost = (input_tokens / 1000 * cfg.get("cost_per_1k_input", 0)
            + output_tokens / 1000 * cfg.get("cost_per_1k_output", 0))
    _daily_usage[key]["cost"] += cost


def get_usage_stats() -> dict:
    today = date.today().isoformat()
    stats = {}
    for key, data in _daily_usage.items():
        if key.startswith(today):
            provider = key.split(":", 1)[1]
            stats[provider] = dict(data)
    return {"date": today, "providers": stats}


def _extract_usage(provider: str, data: dict) -> tuple[int, int]:
    usage = data.get("usage", {})
    if _PROVIDERS.get(provider, {}).get("api") == "anthropic":
        return usage.get("input_tokens", 0), usage.get("output_tokens", 0)
    return usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)


# ══════════════════════════════════════════════════════════════
#  CORE LLM CALLS
# ══════════════════════════════════════════════════════════════

def _build_request(provider: str, system: str, user: str, max_tokens: int):
    cfg = _PROVIDERS[provider]
    api_key = cfg["key"]()

    if cfg["api"] == "anthropic":
        payload = {
            "model": cfg["model"](),
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "temperature": 0.6,
        }
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
    else:
        payload = {
            "model": cfg["model"](),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.6,
            "top_p": 0.95,
            "max_tokens": max_tokens,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
    return cfg["url"], payload, headers


def _extract_text(provider: str, data: dict) -> str:
    cfg = _PROVIDERS.get(provider, {})
    if cfg.get("api") == "anthropic":
        blocks = data.get("content", [])
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
    msg = data["choices"][0]["message"]
    return (msg.get("content") or msg.get("reasoning_content") or "").strip()


def _call_provider(provider: str, system: str, user: str, max_tokens: int = 2000) -> str:
    url, payload, headers = _build_request(provider, system, user, max_tokens)

    with httpx.Client(timeout=120.0) as http:
        resp = http.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    inp, out = _extract_usage(provider, data)
    _track_usage(provider, inp, out)
    return _extract_text(provider, data)


async def _call_provider_async(provider: str, system: str, user: str, max_tokens: int = 2000) -> str:
    url, payload, headers = _build_request(provider, system, user, max_tokens)

    async with httpx.AsyncClient(timeout=120.0) as http:
        resp = await http.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    inp, out = _extract_usage(provider, data)
    _track_usage(provider, inp, out)
    return _extract_text(provider, data)


def _call_llm(
    system: str,
    user: str,
    max_tokens: int = 2000,
    prefer: list[str] | None = None,
    task_type: str | None = None,
) -> str:
    available = _available_providers()
    if prefer:
        ordered = [p for p in prefer if p in available] + [p for p in available if p not in prefer]
        if not ordered:
            raise RuntimeError("No AI providers configured.")
        primary = ordered[0]
    else:
        ordered = available
        primary = _next_provider(task_type)

    try:
        return _call_provider(primary, system, user, max_tokens)
    except Exception as e:
        logger.warning(f"{primary} failed: {e}")
        for fallback in ordered:
            if fallback != primary:
                try:
                    logger.info(f"Falling back to {fallback}")
                    return _call_provider(fallback, system, user, max_tokens)
                except Exception as e2:
                    logger.warning(f"{fallback} also failed: {e2}")
        raise


def call_llm(
    system: str,
    user: str,
    max_tokens: int = 2000,
    prefer: list[str] | None = None,
    task_type: str | None = None,
) -> str:
    """Public API — task-routed LLM call with failover."""
    return _call_llm(system, user, max_tokens, prefer, task_type)


def parse_json_response(text: str) -> dict:
    """Extract JSON from LLM response, handling markdown fences and reasoning blocks."""
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", cleaned).strip()
    match = re.search(r"(\{.*\}|\[.*\])", cleaned, flags=re.DOTALL)
    if match:
        cleaned = match.group(1)
    result = json.loads(cleaned)
    if isinstance(result, list):
        return result[0] if result and isinstance(result[0], dict) else {}
    return result


# Keep underscore alias for backward compatibility
_parse_json_response = parse_json_response


# ══════════════════════════════════════════════════════════════
#  BATCH PROCESSING UTILITIES
# ══════════════════════════════════════════════════════════════

def _is_rate_limit(e: Exception) -> bool:
    return "429" in str(e) or "too many requests" in str(e).lower()


async def _call_with_backoff(provider: str, system: str, prompt: str, max_tokens: int, job_index: int) -> str:
    delays = [2.0, 4.0, 8.0]
    for attempt, delay in enumerate([0.0, *delays]):
        if delay:
            await asyncio.sleep(delay)
        try:
            return await _call_provider_async(provider, system, prompt, max_tokens)
        except Exception as e:
            if _is_rate_limit(e) and attempt < len(delays):
                logger.debug(f"[Job {job_index}] {provider} 429 — backing off {delays[attempt]}s")
                continue
            raise
    raise RuntimeError("unreachable")


async def process_single_job(
    provider: str,
    system: str,
    prompt: str,
    max_tokens: int,
    job_index: int,
    semaphore: asyncio.Semaphore,
) -> tuple[int, Optional[dict], str]:
    async with semaphore:
        available = _available_providers()
        try:
            raw = await _call_with_backoff(provider, system, prompt, max_tokens, job_index)
            return (job_index, parse_json_response(raw), provider)
        except Exception as e:
            logger.warning(f"[Job {job_index}] {provider} failed: {e}")
            for fallback in available:
                if fallback != provider:
                    try:
                        raw = await _call_with_backoff(fallback, system, prompt, max_tokens, job_index)
                        return (job_index, parse_json_response(raw), fallback)
                    except Exception as e2:
                        logger.warning(f"[Job {job_index}] {fallback} fallback also failed: {e2}")
            return (job_index, None, provider)
