"""
utils/token_budget.py
---------------------
Fast token counting and context trimming for LLM calls.

Backends (first available wins):
  1. gigatoken  — GB/s Rust tokenizer (pip install gigatoken)
  2. tiktoken   — OpenAI-compatible (pip install tiktoken)
  3. heuristic  — ~4 characters per token

Usage:
    from utils.token_budget import count_tokens, trim_text, fit_messages

    n = count_tokens("hello world", model="llama-3.3-70b-versatile")
    clipped = trim_text(huge_tool_json, max_tokens=2000)
    msgs = fit_messages(messages, max_tokens=6000)
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

log = logging.getLogger(__name__)

# Soft defaults for chat + tool-summary calls in this app
DEFAULT_MAX_CONTEXT = 6000
DEFAULT_MAX_TOOL_RAW = 3500
DEFAULT_MAX_HISTORY_CHARS = 4000

_BACKEND: str | None = None


def _detect_backend() -> str:
    global _BACKEND
    if _BACKEND is not None:
        return _BACKEND
    try:
        import gigatoken  # noqa: F401

        _BACKEND = "gigatoken"
        log.info("token_budget backend: gigatoken")
        return _BACKEND
    except Exception:
        pass
    try:
        import tiktoken  # noqa: F401

        _BACKEND = "tiktoken"
        log.info("token_budget backend: tiktoken")
        return _BACKEND
    except Exception:
        pass
    _BACKEND = "heuristic"
    log.info("token_budget backend: heuristic (~4 chars/token)")
    return _BACKEND


@lru_cache(maxsize=8)
def _gigatoken_encoder(model_hint: str):
    import gigatoken as gt

    # Map common app model ids to a HF-style id gigatoken can load
    hint = (model_hint or "").lower()
    if "llama" in hint or "groq" in hint:
        name = "meta-llama/Meta-Llama-3-8B"
    elif "qwen" in hint:
        name = "Qwen/Qwen2.5-7B"
    elif "gpt-oss" in hint or "gpt" in hint:
        name = "openai-community/gpt2"
    else:
        name = "openai-community/gpt2"
    try:
        return gt.Tokenizer(name)
    except Exception:
        return gt.Tokenizer("openai-community/gpt2")


@lru_cache(maxsize=4)
def _tiktoken_encoder(model_hint: str):
    import tiktoken

    hint = (model_hint or "").lower()
    # cl100k_base covers GPT-4 / many chat models; good enough for budgeting
    for name in ("cl100k_base", "o200k_base", "p50k_base"):
        try:
            return tiktoken.get_encoding(name)
        except Exception:
            continue
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str, model: str | None = None) -> int:
    """Return approximate token count for *text*."""
    if not text:
        return 0
    backend = _detect_backend()
    try:
        if backend == "gigatoken":
            enc = _gigatoken_encoder(model or "")
            # Native API varies slightly by version — try common shapes
            if hasattr(enc, "encode"):
                ids = enc.encode(text)
                return len(ids) if not isinstance(ids, int) else ids
            if hasattr(enc, "tokenize"):
                return len(enc.tokenize(text))
        if backend == "tiktoken":
            enc = _tiktoken_encoder(model or "")
            return len(enc.encode(text))
    except Exception as exc:
        log.debug("token count fallback after error: %s", exc)
    # heuristic
    return max(1, len(text) // 4)


def trim_text(text: str, max_tokens: int, model: str | None = None) -> str:
    """
    Truncate *text* so it fits in roughly max_tokens.
    Keeps the start (usually the most relevant for tool JSON headers).
    """
    if not text or max_tokens <= 0:
        return text or ""
    if count_tokens(text, model) <= max_tokens:
        return text

    # Binary search on character length using the active backend
    lo, hi = 0, len(text)
    best = ""
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = text[:mid]
        if count_tokens(candidate, model) <= max_tokens:
            best = candidate
            lo = mid + 1
        else:
            hi = mid - 1
    if best and len(best) < len(text):
        return best.rstrip() + "\n…[truncated to fit token budget]"
    return best or text[: max_tokens * 4]


def fit_messages(
    messages: list[dict[str, Any]],
    max_tokens: int = DEFAULT_MAX_CONTEXT,
    model: str | None = None,
    *,
    keep_system: bool = True,
) -> list[dict[str, Any]]:
    """
    Trim a chat message list to fit under max_tokens.

    Strategy: always keep the system message (if any) and the last user
    message; drop or shrink older turns from the middle.
    """
    if not messages:
        return messages

    def _msg_tokens(m: dict) -> int:
        return count_tokens(str(m.get("content") or ""), model) + 4  # role overhead

    total = sum(_msg_tokens(m) for m in messages)
    if total <= max_tokens:
        return messages

    system = [m for m in messages if m.get("role") == "system"] if keep_system else []
    rest = [m for m in messages if m.get("role") != "system"] if keep_system else list(messages)

    # Always keep the last message
    if not rest:
        return system

    kept: list[dict[str, Any]] = [rest[-1]]
    budget = max_tokens - sum(_msg_tokens(m) for m in system) - _msg_tokens(rest[-1])

    # Walk backward through older messages
    for m in reversed(rest[:-1]):
        cost = _msg_tokens(m)
        if cost <= budget:
            kept.insert(0, m)
            budget -= cost
        else:
            # Try a truncated version of this turn
            content = str(m.get("content") or "")
            # Leave a little room
            if budget > 50:
                clipped = trim_text(content, budget - 8, model)
                kept.insert(0, {"role": m.get("role", "user"), "content": clipped})
            break

    return system + kept


def trim_tool_raw(raw: str, max_tokens: int = DEFAULT_MAX_TOOL_RAW, model: str | None = None) -> str:
    """Convenience: cap a single tool payload before feeding it to the summarizer."""
    return trim_text(raw or "", max_tokens, model)


def backend_name() -> str:
    """Return the active counting backend (gigatoken | tiktoken | heuristic)."""
    return _detect_backend()
