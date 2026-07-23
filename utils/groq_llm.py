"""
utils/groq_llm.py
--------------------
Alternative LLM backend using Groq's LPU inference via LangChain's
`langchain-groq` integration (ChatGroq). Matches the chat_completion()
signature of claude_llm.py / the old nvidia_llm.py, so it can be used
interchangeably in the Linear RAG engine.

Note: Groq cannot use Anthropic's hosted MCP connector. Live EULER tools
for Groq are handled separately in utils/mcp_agent_engine.py (our own MCP
client + tool loop), which linear_query_engine enables when EULER is connected.

SETUP:
1. pip install langchain-groq (see requirements.txt)
2. Set GROQ_API_KEY in your environment/.env (get one at
   https://console.groq.com/keys)
3. Optionally set GROQ_MODEL to override the default model.
"""

from __future__ import annotations

import json
import os

from dotenv import load_dotenv
from gptcache import cache
from gptcache.adapter.api import get, put
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_groq import ChatGroq

# Initialize GPTCache for exact-match caching (avoids downloading ML models)
cache.init(pre_embedding_func=lambda data, **kwargs: kwargs.get("prompt_key"))

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

_ROLE_TO_MESSAGE = {
    "system": SystemMessage,
    "assistant": AIMessage,
    "user": HumanMessage,
}


def _to_langchain_messages(messages: list[dict[str, str]]) -> list:
    converted = []
    for m in messages:
        cls = _ROLE_TO_MESSAGE.get(m.get("role", "user"), HumanMessage)
        converted.append(cls(content=m.get("content", "")))
    return converted


def chat_completion(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.7,
    top_p: float = 0.95,
    max_tokens: int = 8192,
    use_cache: bool = True,
) -> str:
    """
    Standard chat completion using Groq via LangChain's ChatGroq wrapper,
    with an optional GPTCache exact-match layer.

    Pass use_cache=False for tool-agent rounds so stale answers never mask
    live EULER MCP results.
    """
    prompt_key = json.dumps(messages, sort_keys=True)

    if use_cache:
        cached_answer = get(prompt_key, prompt_key=prompt_key)
        if cached_answer:
            return cached_answer

    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set")

    try:
        llm = ChatGroq(
            model=model or GROQ_MODEL,
            api_key=GROQ_API_KEY,
            temperature=temperature,
            max_tokens=max_tokens,
            model_kwargs={"top_p": top_p},
        )

        response = llm.invoke(_to_langchain_messages(messages))
        content = (response.content or "").strip()
        if not content:
            raise RuntimeError("Groq returned empty content.")

        if use_cache:
            put(prompt_key, content, prompt_key=prompt_key)
        return content
    except Exception as exc:
        raise RuntimeError(f"Groq API request failed: {exc}") from exc
