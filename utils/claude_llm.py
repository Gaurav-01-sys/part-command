"""
utils/claude_llm.py
--------------------
Drop-in replacement for utils/nvidia_llm.py. Same chat_completion() signature,
so utils/linear_query_engine.py only needs a one-line import change.

Two things happen here:
1. All LLM calls go to Claude instead of NVIDIA's endpoint.
2. Claude is given direct, live access to EULER's Partner Data Lake via
   Anthropic's MCP connector - so questions like "which Gold partners are
   at risk?" can be answered from EULER's real, current data instead of
   the local CSV snapshots.

SETUP:
1. pip install anthropic (see requirements.txt)
2. Set ANTHROPIC_API_KEY in your environment/.env
3. To enable live EULER access either:
   a) Use the in-app "EULER Connect" tab to complete the OAuth 2.1 flow
      (recommended — token is obtained, persisted, and injected automatically)
   b) Set EULER_MCP_TOKEN manually in .env as a fallback for testing

The module exposes set_euler_token() so the OAuth callback can activate live
EULER tool access at runtime without requiring an app restart.
"""

from __future__ import annotations

import os
import threading
from functools import lru_cache

from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")

EULER_MCP_URL = os.getenv("EULER_MCP_URL", "https://mcp.eulerapp.com/mcp")

# Runtime token store removed — we now fetch dynamically from euler_oauth
# to ensure we always have the freshest token (and handle silent refreshes).

# Try to load a persisted token from the OAuth module on startup.
try:
    from utils.euler_oauth import try_load_persisted as _try_load
    _try_load()
except Exception:
    pass  # euler_oauth not available or disk has no token — not fatal

# Beta header for the MCP connector — check docs.anthropic.com for updates.
MCP_BETA_HEADER = "mcp-client-2025-11-20"


@lru_cache(maxsize=1)
def _client() -> Anthropic:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    return Anthropic(api_key=ANTHROPIC_API_KEY)


# ── Public API for runtime token management ───────────────────────────────────

def set_euler_token(token: str) -> None:
    """Legacy injection method - no longer needed as we fetch from euler_oauth."""
    pass


def get_euler_status() -> dict:
    """Return a dict describing the current EULER connection state.
    Suitable for rendering a status badge in the UI.

    Token resolution order:
      1. OAuth token set (in-memory / refreshed)
      2. EULER_MCP_TOKEN environment variable (Render / .env)
    """
    token = ""
    source = ""
    try:
        from utils.euler_oauth import get_token_set

        ts = get_token_set()
        if ts and getattr(ts, "access_token", None):
            token = ts.access_token
            source = "oauth"
    except Exception:
        pass

    if not token:
        token = (os.getenv("EULER_MCP_TOKEN") or "").strip()
        if token:
            source = "env"

    if token:
        preview = token[:4] + "..." + token[-4:] if len(token) > 8 else "****"
        return {"enabled": True, "preview": preview, "source": source}
    return {"enabled": False, "preview": ""}


def _mcp_servers_config() -> list[dict] | None:
    """Return the MCP server config list if a token is available."""
    from utils.euler_oauth import get_token_set
    ts = get_token_set()
    token = ts.access_token if ts else os.getenv("EULER_MCP_TOKEN", "")
    
    if not token:
        return None
    return [
        {
            "type": "url",
            "url":  EULER_MCP_URL,
            "name": "euler",
            "authorization_token": token,
        }
    ]


def _to_anthropic_messages(messages: list[dict[str, str]]) -> tuple[str | None, list[dict]]:
    """Split OpenAI-style messages (with an optional 'system' role) into
    Claude's (system_prompt, messages) shape."""
    system_prompt = None
    converted = []
    for m in messages:
        if m.get("role") == "system":
            system_prompt = m.get("content", "")
        else:
            converted.append({"role": m.get("role", "user"), "content": m.get("content", "")})
    return system_prompt, converted


def chat_completion(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.1,
    top_p: float = 0.95,
    max_tokens: int = 900,
) -> str:
    try:
        system_prompt, anthropic_messages = _to_anthropic_messages(messages)
        mcp_servers = _mcp_servers_config()

        kwargs = dict(
            model=model or CLAUDE_MODEL,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            messages=anthropic_messages,
        )
        if system_prompt:
            kwargs["system"] = system_prompt

        if mcp_servers:
            # mcp-client-2025-11-20 requires BOTH mcp_servers AND mcp_toolset.
            # Without tools=[], the server is attached but Claude never sees EULER tools.
            if max_tokens < 1500:
                kwargs["max_tokens"] = 1500
            server_name = mcp_servers[0]["name"]
            response = _client().beta.messages.create(
                **kwargs,
                mcp_servers=mcp_servers,
                tools=[{"type": "mcp_toolset", "mcp_server_name": server_name}],
                betas=[MCP_BETA_HEADER],
            )
        else:
            response = _client().messages.create(**kwargs)

        text_parts = [
            block.text
            for block in response.content
            if getattr(block, "type", None) == "text" and getattr(block, "text", None)
        ]
        text = "".join(text_parts).strip()
        if not text:
            raise RuntimeError(
                f"Claude returned no text content; stop_reason={getattr(response, 'stop_reason', None)}; "
                f"content_types={[getattr(b, 'type', type(b).__name__) for b in (response.content or [])]}"
            )
        return text
    except Exception as exc:
        raise RuntimeError(f"Claude API request failed: {exc}") from exc
