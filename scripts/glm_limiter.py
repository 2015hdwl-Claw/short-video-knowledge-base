#!/usr/bin/env python3
"""Dual-provider LLM caller with token-bucket rate limiting.

Providers (priority order):
  1. NVIDIA NIM  (z-ai/glm-4.7)
  2. GLM CN      (glm-4.7-flash)

Env vars:
  NVIDIA_API_KEY       - NVIDIA NIM API key
  CLASSIFIER_API_KEY   - GLM CN API key
  LLM_PROVIDERS        - comma-separated provider order (default: nvidia,glm_cn)
"""

import os
import sys
import threading
import time
from dataclasses import dataclass, field

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from openai import OpenAI

PROVIDERS = {
    "nvidia": {
        "base_url": "https://integrate.api.nvidia.com/v1/",
        "model": "google/gemma-3-4b-it",
        "env_key": "NVIDIA_API_KEY",
        "fallback_key": "",
    },
    "glm_cn": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4/",
        "model": "glm-4.7-flash",
        "env_key": "CLASSIFIER_API_KEY",
        "fallback_key": "",
    },
}

_ACTIVE_ORDER = os.getenv("LLM_PROVIDERS", "nvidia,glm_cn").split(",")


class TokenBucket:
    def __init__(self, rate=0.5, capacity=5):
        self.rate = rate
        self.capacity = capacity
        self._tokens = float(capacity)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self):
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last
                self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
                self._last = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self.rate
            time.sleep(wait)


_bucket = TokenBucket(rate=0.5, capacity=5)


@dataclass
class ProviderHealth:
    name: str = ""
    last_error: str = ""
    last_success: float = 0.0
    fail_count: int = 0
    total_calls: int = 0


_health: dict[str, ProviderHealth] = {n: ProviderHealth(name=n) for n in PROVIDERS}
_health_lock = threading.Lock()


def _get_client(provider_name: str) -> OpenAI | None:
    cfg = PROVIDERS.get(provider_name)
    if not cfg:
        return None
    key = os.getenv(cfg["env_key"], "") or cfg.get("fallback_key", "")
    if not key:
        return None
    return OpenAI(api_key=key, base_url=cfg["base_url"])


def _record_success(name: str):
    with _health_lock:
        h = _health[name]
        h.last_success = time.monotonic()
        h.fail_count = 0
        h.total_calls += 1
        h.last_error = ""


def _record_failure(name: str, error: str):
    with _health_lock:
        h = _health[name]
        h.fail_count += 1
        h.total_calls += 1
        h.last_error = str(error)[:120]


def rate_limited_call(messages, max_tokens=500, temperature=0.7, response_format=None):
    _bucket.acquire()
    tried = set()
    for name in _ACTIVE_ORDER:
        if name in tried:
            continue
        tried.add(name)
        cfg = PROVIDERS.get(name)
        if not cfg:
            continue
        client = _get_client(name)
        if not client:
            continue
        try:
            kwargs = {
                "model": cfg["model"],
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            if response_format:
                kwargs["response_format"] = response_format
            resp = client.chat.completions.create(**kwargs)
            _record_success(name)
            return resp
        except Exception as e:
            err = str(e)
            _record_failure(name, err)
            if "429" in err or "timeout" in err.lower() or "rate" in err.lower():
                continue
            raise
    remaining = [n for n in PROVIDERS if n not in tried]
    for name in remaining:
        tried.add(name)
        cfg = PROVIDERS[name]
        client = _get_client(name)
        if not client:
            continue
        try:
            kwargs = {
                "model": cfg["model"],
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            if response_format:
                kwargs["response_format"] = response_format
            resp = client.chat.completions.create(**kwargs)
            _record_success(name)
            return resp
        except Exception as e:
            _record_failure(name, str(e))
            continue
    raise RuntimeError("All providers failed. Health: " + str(provider_status()))


def provider_status() -> dict:
    with _health_lock:
        result = {}
        for name, h in _health.items():
            cfg = PROVIDERS.get(name, {})
            has_key = bool(os.getenv(cfg.get("env_key", ""), ""))
            result[name] = {
                "has_key": has_key,
                "model": cfg.get("model", ""),
                "total_calls": h.total_calls,
                "fail_count": h.fail_count,
                "last_error": h.last_error,
            }
        return result


if __name__ == "__main__":
    status = provider_status()
    for name, info in status.items():
        parts = [name, info["model"], "key=" + str(info["has_key"])]
        if info["last_error"]:
            parts.append("err=" + info["last_error"][:60])
        print(" | ".join(parts))


def extract_llm_content(resp):
    """Extract content from LLM response, handling thinking mode.
    
    GLM thinking models put reasoning in reasoning_content field,
    leaving content empty. This fallback handles both cases.
    """
    msg = resp.choices[0].message
    text = msg.content or ""
    if not text.strip() and hasattr(msg, "reasoning_content") and msg.reasoning_content:
        text = msg.reasoning_content
    return text
