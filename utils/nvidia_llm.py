"""
utils/nvidia_llm.py
--------------------
Alternative LLM backend using NVIDIA NIM (via OpenAI SDK).
Matches the chat_completion signature of claude_llm.py so it can be used
interchangeably in the Linear RAG engine.

Note: NIM does not natively support the Anthropic MCP protocol, so live EULER
tool access is not available when using this provider.
"""

from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from openai import OpenAI
import json
from gptcache import cache
from gptcache.adapter.api import get, put

# Initialize GPTCache for exact match (avoids downloading ML models)
cache.init(pre_embedding_func=lambda data, **kwargs: kwargs.get("prompt_key"))

load_dotenv()

from langchain_nvidia_ai_endpoints import ChatNVIDIA

import requests

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "minimaxai/minimax-m3")

def chat_completion(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 1.0,
    top_p: float = 0.95,
    max_tokens: int = 8192,
) -> str:
    """
    Standard chat completion using NVIDIA NIM via raw HTTP requests with GPTCache.
    """
    prompt_key = json.dumps(messages, sort_keys=True)
    
    # 1. Check cache
    cached_answer = get(prompt_key, prompt_key=prompt_key)
    if cached_answer:
        return cached_answer

    if not NVIDIA_API_KEY:
        raise RuntimeError("NVIDIA_API_KEY is not set")

    invoke_url = "https://integrate.api.nvidia.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Accept": "application/json",
    }
    payload = {
        "model": model or NVIDIA_MODEL,
        "messages": messages,
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
        "stream": False
    }

    try:
        response = requests.post(invoke_url, headers=headers, json=payload)
        response.raise_for_status()
        
        data = response.json()
        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("NIM returned no choices.")
            
        content = choices[0].get("message", {}).get("content", "")
        if not content:
            raise RuntimeError("NIM returned empty content.")
        
        answer = content.strip()
        # 2. Store in cache
        put(prompt_key, answer, prompt_key=prompt_key)
        return answer
    except Exception as exc:
        raise RuntimeError(f"NVIDIA API request failed: {exc}") from exc
