"""
utils/euler_mcp_client.py
-------------------------
Minimal MCP client for the remote EULER server (https://mcp.eulerapp.com/mcp).

Uses plain HTTP JSON-RPC (Streamable HTTP style) via httpx so Groq (or any
non-Anthropic LLM) can call the same EULER tools Claude gets through the
Anthropic MCP connector.

Auth: Bearer token from euler_oauth (OAuth Connect tab) or EULER_MCP_TOKEN.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

EULER_MCP_URL = os.getenv("EULER_MCP_URL", "https://mcp.eulerapp.com/mcp")
PROTOCOL_VERSION = "2024-11-05"
CLIENT_INFO = {"name": "partner-command-center", "version": "1.0.0"}

# Public-reference catalog from mcp.eulerapp.com partner + customer docs.
# Display / empty-catalog hints only — NEVER injected into routing.
# Routing always uses only what list_tools() returns from the live server.
# Official refs:
#   https://mcp.eulerapp.com/public/partner-capabilities
#   https://mcp.eulerapp.com/public/capabilities
EULER_KNOWN_TOOLS: list[dict[str, Any]] = [
    {"name": "list_accounts", "description": "Accounts the current OAuth session can access", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "euler_help", "description": "Search EULER help / capability guidance", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}}},
    {"name": "performance", "description": "Partner performance metrics over a date range", "inputSchema": {"type": "object", "properties": {"partner_id": {"type": "string"}, "start_date": {"type": "string"}, "end_date": {"type": "string"}, "action": {"type": "string"}}}},
    {"name": "influenced_sourced_deals", "description": "Sourced vs influenced deal attribution", "inputSchema": {"type": "object", "properties": {"partner_id": {"type": "string"}, "start_date": {"type": "string"}, "end_date": {"type": "string"}}}},
    {"name": "commissions", "description": "Commission earnings and deal-level breakdowns", "inputSchema": {"type": "object", "properties": {"partner_id": {"type": "string"}, "start_date": {"type": "string"}, "end_date": {"type": "string"}, "action": {"type": "string"}}}},
    {"name": "partner_inc1_incentives", "description": "Inc 1.0 incentive plan for a partner", "inputSchema": {"type": "object", "properties": {"partner_id": {"type": "string"}}}},
    {"name": "partner_inc2_incentives", "description": "Inc 2.0 incentive plan / tier status", "inputSchema": {"type": "object", "properties": {"partner_id": {"type": "string"}}}},
    {"name": "partner_artifacts", "description": "Agreements, tracking links, deals, charges, or invoices for one partner", "inputSchema": {"type": "object", "required": ["partner_id"], "properties": {"action": {"type": "string", "enum": ["agreements", "tracking_links", "deals", "charges", "invoices"]}, "partner_id": {"type": "string"}}}},
    {"name": "get_search_deals", "description": "Search a specific deal by name", "inputSchema": {"type": "object", "properties": {"deal_name": {"type": "string"}, "partner_id": {"type": "string"}, "query": {"type": "string"}}}},
    {"name": "referrals", "description": "List and filter referrals / deal registrations", "inputSchema": {"type": "object", "properties": {"partner_id": {"type": "string"}, "action": {"type": "string"}}}},
    {"name": "submit_referral", "description": "Validate and submit a referral", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "content_list", "description": "List content shared by a customer", "inputSchema": {"type": "object", "properties": {"partner_id": {"type": "string"}, "query": {"type": "string"}}}},
    {"name": "content_search", "description": "Semantic search inside shared partner content", "inputSchema": {"type": "object", "properties": {"partner_id": {"type": "string"}, "query": {"type": "string"}}}},
    {"name": "partner_users", "description": "List partner team users and roles", "inputSchema": {"type": "object", "properties": {"partner_id": {"type": "string"}, "action": {"type": "string"}}}},
    {"name": "manage_partner_users", "description": "Manage partner team roles and assignments", "inputSchema": {"type": "object", "properties": {"partner_id": {"type": "string"}, "action": {"type": "string"}}}},
    {"name": "si_service_projects", "description": "List and inspect SI service projects", "inputSchema": {"type": "object", "properties": {"partner_id": {"type": "string"}}}},
    {"name": "si_manage_service_project", "description": "Create and manage SI service projects", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "submit_feedback", "description": "Send structured feedback to EULER engineering", "inputSchema": {"type": "object", "properties": {"type": {"type": "string"}, "affected_tool": {"type": "string"}}}},
    {"name": "partners", "description": "Customer partner list / summary / pending queue", "inputSchema": {"type": "object", "properties": {"action": {"type": "string"}, "filter_name": {"type": "string"}}}},
    {"name": "partner_directory_search", "description": "Search the public partner directory", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "entity_key": {"type": "string"}}}},
    {"name": "get_partner_overall_stats", "description": "Program-wide partner stats snapshot", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "company_invoices", "description": "Company-wide invoice summary and lists", "inputSchema": {"type": "object", "properties": {"action": {"type": "string"}, "partner_id": {"type": "string"}}}},
    {"name": "flows", "description": "Onboarding flows, steps, and assignments", "inputSchema": {"type": "object", "properties": {"action": {"type": "string"}, "flow_id": {"type": "string"}}}},
]


def _get_token() -> str:
    try:
        from utils.euler_oauth import get_token_set

        ts = get_token_set()
        if ts and ts.access_token:
            return ts.access_token
    except Exception:
        pass
    return os.getenv("EULER_MCP_TOKEN", "").strip()


def _headers(token: str, session_id: str | None = None) -> dict[str, str]:
    h = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session_id:
        h["Mcp-Session-Id"] = session_id
    return h


def _parse_response_body(resp: httpx.Response) -> dict[str, Any]:
    """Handle plain JSON or SSE-style bodies from streamable HTTP MCP servers."""
    ctype = (resp.headers.get("content-type") or "").lower()
    text = resp.text.strip()
    if not text:
        return {}

    # SSE: collect last JSON data payload (or any payload that has result/error)
    if "text/event-stream" in ctype or text.startswith("event:") or text.startswith("data:"):
        best: dict[str, Any] = {}
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                best = obj
                if "result" in obj or "error" in obj:
                    return obj
        return best

    try:
        return resp.json()
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise RuntimeError(f"Unparseable MCP response: {text[:400]}")


def _extract_tools(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Be tolerant of slightly different tools/list shapes."""
    if not result:
        return []
    if "error" in result:
        return []
    body = result.get("result", result)
    if isinstance(body, list):
        return [t for t in body if isinstance(t, dict) and t.get("name")]
    if isinstance(body, dict):
        tools = body.get("tools") or body.get("Tools") or body.get("data") or []
        if isinstance(tools, list):
            return [t for t in tools if isinstance(t, dict) and t.get("name")]
    return []


class EulerMCPClient:
    """Synchronous MCP client for list_tools / call_tool against EULER."""

    def __init__(self, token: str | None = None, url: str | None = None, timeout: float = 60.0):
        self.token = token or _get_token()
        if not self.token:
            raise RuntimeError(
                "No EULER MCP token. Connect via the EULER Connect tab or set EULER_MCP_TOKEN."
            )
        self.url = (url or EULER_MCP_URL).rstrip("/")
        self.timeout = timeout
        self.session_id: str | None = None
        self._initialized = False
        self._tools_cache: list[dict[str, Any]] | None = None
        # True only when list_tools() successfully fetched ≥1 tools from the live server.
        # False means the server was unreachable, returned an error, or returned 0 tools.
        # Callers must check this before routing — never call tools when it is False.
        self.live_fetch_ok: bool = False
        # Keep one client so connection / session cookies stay warm
        self._http = httpx.Client(timeout=timeout, follow_redirects=True)

    def close(self) -> None:
        try:
            self._http.close()
        except Exception:
            pass

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        resp = self._http.post(
            self.url,
            headers=_headers(self.token, self.session_id),
            json=payload,
        )
        sid = resp.headers.get("mcp-session-id") or resp.headers.get("Mcp-Session-Id")
        if sid:
            self.session_id = sid

        # 202 Accepted is valid for notifications
        if resp.status_code >= 400:
            raise RuntimeError(f"MCP HTTP {resp.status_code}: {resp.text[:500]}")

        if resp.status_code == 202 and not resp.text.strip():
            return {}

        parsed = _parse_response_body(resp)
        log.info(
            "MCP %s → status=%s session=%s keys=%s",
            payload.get("method"),
            resp.status_code,
            (self.session_id or "")[:12],
            list(parsed.keys()) if isinstance(parsed, dict) else type(parsed),
        )
        return parsed

    def initialize(self) -> None:
        if self._initialized:
            return
        req_id = str(uuid.uuid4())
        result = self._post(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "clientInfo": CLIENT_INFO,
                },
            }
        )
        if result.get("error"):
            raise RuntimeError(f"MCP initialize failed: {result['error']}")

        try:
            self._post(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                    "params": {},
                }
            )
        except Exception as exc:
            log.debug("notifications/initialized optional failure: %s", exc)

        self._initialized = True
        log.info("EULER MCP initialized (session=%s)", self.session_id)

    def list_tools(self, *, force: bool = False) -> list[dict[str, Any]]:
        """Return the live tool descriptors from the EULER MCP server.

        Returns an empty list (and sets ``self.live_fetch_ok = False``) when the
        server is unreachable, returns a JSON-RPC error, or advertises 0 tools.
        Callers must check ``self.live_fetch_ok`` before routing — this method
        never injects the ``EULER_KNOWN_TOOLS`` reference catalog into the result.
        Use ``EulerMCPClient.known_tools()`` for display/hint purposes only.
        """
        if self._tools_cache is not None and not force:
            return self._tools_cache

        try:
            self.initialize()
            req_id = str(uuid.uuid4())
            result = self._post(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "method": "tools/list",
                    "params": {},
                }
            )
        except Exception as exc:
            self.live_fetch_ok = False
            self._tools_cache = []
            log.warning(
                "MCP tools/list failed — no tools available for routing. "
                "Raw response/error: %s",
                exc,
            )
            return self._tools_cache

        raw_result = json.dumps(result, default=str)[:800]
        if not isinstance(result, dict) or result.get("error"):
            log.warning(
                "MCP tools/list returned an error — no tools available for routing. "
                "Raw response: %s",
                raw_result,
            )
            self.live_fetch_ok = False
            self._tools_cache = []
            return self._tools_cache

        tools = _extract_tools(result)
        if not tools:
            log.warning(
                "MCP tools/list returned 0 tools (raw keys=%s). "
                "Routing will not be attempted.",
                list(result.keys()) if isinstance(result, dict) else type(result),
            )
            log.warning("MCP tools/list raw (truncated): %s", raw_result)
            self.live_fetch_ok = False
            self._tools_cache = []
            return self._tools_cache

        log.info("MCP tools/list → %d live tools: %s", len(tools), [t.get("name") for t in tools])
        self.live_fetch_ok = True
        self._tools_cache = tools
        return tools

    @staticmethod
    def known_tools() -> list[dict[str, Any]]:
        """Return the EULER_KNOWN_TOOLS reference catalog for display/hint purposes.

        These are tools EULER *typically* exposes, but their availability depends
        on the specific account and server version. Never use this for routing.
        """
        return list(EULER_KNOWN_TOOLS)

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        """
        Call a tool and return a text summary of the result content.

        Retries a few common argument-key variants when the first call errors
        (e.g. query vs q vs search for directory search tools).
        """
        self.initialize()
        base_args = dict(arguments or {})
        attempts = _argument_variants(name, base_args)

        last_error = ""
        last_raw = ""
        for args in attempts:
            req_id = str(uuid.uuid4())
            log.info("MCP tools/call name=%s args=%s", name, args)
            try:
                result = self._post(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "method": "tools/call",
                        "params": {
                            "name": name,
                            "arguments": args,
                        },
                    }
                )
            except Exception as exc:
                last_error = str(exc)
                log.warning("MCP tools/call transport error name=%s: %s", name, exc)
                continue

            last_raw = json.dumps(result, default=str)[:2000]

            if result.get("error"):
                err = result["error"]
                last_error = str(err.get("message", err))
                log.warning("MCP tools/call error name=%s args=%s err=%s", name, args, last_error)
                continue

            body = result.get("result") if isinstance(result.get("result"), (dict, list, str)) else result
            if isinstance(body, dict) and body.get("isError"):
                last_error = self._content_to_text(body.get("content")) or "isError=true"
                log.warning("MCP tools/call isError name=%s: %s", name, last_error[:300])
                continue

            if isinstance(body, dict):
                text = self._content_to_text(body.get("content"))
                if not text:
                    # Prefer structured dump of the whole result body
                    text = json.dumps(
                        {k: v for k, v in body.items() if k not in ("isError",)},
                        default=str,
                    )[:8000]
            else:
                text = self._content_to_text(body)

            if text and text not in ("[tool returned empty content]",):
                return text
            last_error = last_error or "empty content"
            last_raw = text or last_raw

        return (
            f"[tool error] {name} failed after {len(attempts)} attempt(s). "
            f"last_error={last_error!r} raw={last_raw[:800]!r}"
        )

    @staticmethod
    def _content_to_text(content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            return json.dumps(content, default=str)[:8000]
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        parts.append(str(block.get("text", "")))
                    else:
                        parts.append(json.dumps(block, default=str))
                else:
                    parts.append(str(block))
            return "\n".join(parts)[:8000]
        return str(content)[:8000]


def _argument_variants(name: str, args: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a small list of argument dicts to try for finicky tool schemas."""
    variants: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(d: dict[str, Any]) -> None:
        key = json.dumps(d, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            variants.append(d)

    add(args)
    add({})  # some tools take no args

    # Promote a single "query-like" value across common keys
    q = None
    for k in ("query", "q", "search", "searchTerm", "search_term", "text", "keyword", "name"):
        if k in args and args[k] not in (None, ""):
            q = args[k]
            break
    if q is not None:
        for k in ("query", "q", "search", "searchTerm", "search_term", "text", "keyword"):
            add({k: q})
        add({"query": q, "limit": 10})
        add({"q": q, "limit": 10})

    # Directory / partners often accept filters
    if "partner" in name.lower() or "directory" in name.lower() or "search" in name.lower():
        if q is not None:
            add({"filter": q})
            add({"filters": {"query": q}})

    return variants


def get_euler_tools_summary() -> str:
    """Human-readable tool list for prompts / debug."""
    client = EulerMCPClient()
    try:
        tools = client.list_tools()
        lines = []
        for t in tools:
            name = t.get("name", "?")
            desc = (t.get("description") or "").strip().replace("\n", " ")
            lines.append(f"- {name}: {desc[:160]}")
        return "\n".join(lines) if lines else "(no tools returned)"
    finally:
        client.close()
