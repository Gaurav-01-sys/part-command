"""
utils/mcp_agent_engine.py
-------------------------
Groq + live EULER MCP tools with a clean agentic loop:

  1. Route the user question to the right tool(s)
  2. Call EULER MCP
  3. Answer in natural human language
  4. Attach structured tool_results + DataFrame for the UI grid

Primary API:
    result = run_euler_agent(messages, question="Show partners", model=...)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import pandas as pd

from utils.euler_mcp_client import EulerMCPClient, EULER_KNOWN_TOOLS
from utils.groq_llm import chat_completion as groq_chat
from utils.token_budget import (
    trim_tool_raw,
    fit_messages,
    backend_name as _token_backend,
)

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 4

# Intent → preferred tool (order matters: first match wins).
# Only official EULER names from partner-capabilities / capabilities docs.
# "company_deals" is NOT a tool — deals are partner_artifacts(action=deals)
# or get_search_deals. Live catalog still gates every candidate at runtime.
_INTENT_ROUTES: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (("artifact", "artifacts", "agreement", "agreements", "tracking link", "tracking links"), ("partner_artifacts",)),
    (("referral", "referrals", "deal registration"), ("referrals", "submit_referral")),
    (("deal", "deals", "pipeline"), ("partner_artifacts", "get_search_deals", "influenced_sourced_deals")),
    (("commission", "commissions", "payout", "payouts"), ("commissions",)),
    (("invoice", "invoices", "charge", "charges"), ("partner_artifacts", "company_invoices")),
    (("performance", "kpi", "scorecard", "how am i performing"), ("performance",)),
    (("content", "shared files", "shared content", "enablement", "knowledge base"), ("content_list", "content_search")),
    (("directory", "search partner", "find partner"), ("partner_directory_search", "partners")),
    (("partner user", "partner users", "team member", "team members"), ("partner_users",)),
    (("role", "roles", "team access", "assign roles"), ("partner_users", "manage_partner_users")),
    (("flow", "flows", "onboarding"), ("flows",)),
    (("incentive", "incentives", "tier package", "commission tier"), ("partner_inc1_incentives", "partner_inc2_incentives")),
    (("service project", "service projects", "si project"), ("si_service_projects", "si_manage_service_project")),
    (("feedback", "feature request", "report a problem"), ("submit_feedback",)),
    (("account", "accounts", "who am i", "my access", "what can you see"), ("list_accounts",)),
    (("help", "what can you do", "capabilities"), ("euler_help", "list_accounts")),
]

# Tools that typically need a partner_id before they return useful data.
_PARTNER_SCOPED_TOOLS = frozenset({
    "partner_artifacts",
    "commissions",
    "performance",
    "influenced_sourced_deals",
    "content_list",
    "content_search",
    "partner_users",
    "manage_partner_users",
    "partner_inc1_incentives",
    "partner_inc2_incentives",
    "si_service_projects",
    "referrals",
    "get_search_deals",
})

# Map question keywords → partner_artifacts action
_ARTIFACT_ACTIONS = (
    ("agreement", "agreements"),
    ("tracking", "tracking_links"),
    ("invoice", "invoices"),
    ("charge", "charges"),
    ("deal", "deals"),
    ("pipeline", "deals"),
)


def _tool_catalog(tools: list[dict[str, Any]] | set[str]) -> dict[str, dict[str, Any]]:
    """Normalize a live tool list, while keeping the old set-based API usable."""
    if isinstance(tools, set):
        return {name: {"name": name} for name in tools}
    return {
        str(tool.get("name")): tool
        for tool in tools
        if isinstance(tool, dict) and tool.get("name")
    }


def _tools_for_prompt(tools: list[dict[str, Any]]) -> str:
    """Render tool names, descriptions, and JSON schemas for the picker LLM."""
    lines = []
    for t in tools:
        name = t.get("name", "?")
        desc = (t.get("description") or "").strip().replace("\n", " ")[:160]
        schema = t.get("inputSchema") or t.get("input_schema") or {}
        schema_text = json.dumps(schema, default=str, separators=(",", ":"))[:1400]
        lines.append(f"- {name}: {desc} | inputSchema={schema_text}")
    return "\n".join(lines) if lines else "(no tools)"


def _missing_required_arguments(tool: dict[str, Any], arguments: dict[str, Any]) -> list[str]:
    """Return required JSON-schema fields absent from a proposed tool call."""
    schema = tool.get("inputSchema") or tool.get("input_schema") or {}
    required = schema.get("required") if isinstance(schema, dict) else []
    if not isinstance(required, list):
        return []
    return [
        str(name)
        for name in required
        if name not in arguments or arguments.get(name) in (None, "")
    ]


def _fallback_route(
    tools: list[dict[str, Any]] | set[str],
    *,
    exclude: set[str] | None = None,
) -> tuple[str, dict[str, Any]] | None:
    """Choose a safe discovery tool instead of guessing a data tool."""
    catalog = _tool_catalog(tools)
    excluded = exclude or set()
    for name in ("euler_help", "list_accounts"):
        if name in catalog and name not in excluded:
            return name, {}
    return None


def _no_live_tools_message(reason: str = "") -> str:
    """Return a clear, honest message when the live tool catalog is empty.

    Lists EULER_KNOWN_TOOLS as a reference so the user knows what to expect
    once the connection/token issue is resolved.
    """
    known = ", ".join(t["name"] for t in EULER_KNOWN_TOOLS)
    parts = [
        "The live EULER tool catalog could not be retrieved"
        + (f" ({reason})" if reason else "") + ".",
        "No tool calls have been made to avoid sending requests to tools that may not exist.",
        "",
        "**Please check:**",
        "- Your EULER MCP token is valid (reconnect via the EULER Connect tab if needed).",
        "- The EULER MCP server is reachable.",
        "",
        f"**Tools EULER typically supports** (once connected): {known}.",
        "",
        "Try asking again after reconnecting, or ask \"what can you do?\" to confirm available tools.",
    ]
    return "\n".join(parts)


def _extract_tool_calls(text: str) -> list[dict[str, Any]]:
    text = text.strip()
    candidates: list[str] = []
    for m in re.finditer(r"```(?:tool|json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL):
        candidates.append(m.group(1))
    if text.startswith("{") or text.startswith("["):
        candidates.append(text)
    if not candidates:
        m = re.search(r"\{[^{}]*\"name\"\s*:\s*\"[^\"]+\"[^{}]*\}", text, re.DOTALL)
        if m:
            candidates.append(m.group(0))

    calls: list[dict[str, Any]] = []
    for raw in candidates:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        items = parsed if isinstance(parsed, list) else [parsed]
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("tool") or item.get("tool_name")
            if not name:
                continue
            args = item.get("arguments") or item.get("args") or item.get("parameters") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            # Guard: never pass multi-paragraph prompt blobs as args
            if isinstance(args, dict):
                args = {
                    k: v
                    for k, v in args.items()
                    if not (isinstance(v, str) and (len(v) > 120 or "\n" in v))
                }
            calls.append({"name": str(name), "arguments": args if isinstance(args, dict) else {}})
    return calls


def _route_intent(
    question: str,
    tools: list[dict[str, Any]] | set[str],
) -> tuple[str, dict] | None:
    """Map natural language to a confirmed-live EULER tool.

    ``tools`` must contain only tools the live server advertised — callers are
    responsible for never passing the EULER_KNOWN_TOOLS reference catalog here.
    Returns None when no intent match is found; the caller then falls through to
    the LLM picker, which also operates on the same live-only tool set.
    """
    q = (question or "").lower().strip()
    if not q:
        return None

    catalog = _tool_catalog(tools)
    tool_names = set(catalog)

    # Explicit "Call <tool>" or tool-name-in-query form
    for name in sorted(tool_names, key=len, reverse=True):
        if re.search(rf"\bcall\s+{re.escape(name)}\b", q) or re.search(
            rf"\b{re.escape(name)}\b", q.replace(" ", "_")
        ):
            args: dict[str, Any] = {}
            m = re.search(r'["\']([^"\']+)["\']', question)
            if m:
                args["query"] = m.group(1)
            return name, args

    quoted = re.search(r'["\']([^"\']+)["\']', question)
    for keywords, candidates in _INTENT_ROUTES:
        if any(kw in q for kw in keywords):
            for tool in candidates:
                if tool not in tool_names:
                    continue
                args: dict[str, Any] = {}
                if quoted and tool in {
                    "get_search_deals",
                    "partner_directory_search",
                    "content_list",
                    "content_search",
                    "euler_help",
                }:
                    args["query"] = quoted.group(1)
                if tool == "get_search_deals" and quoted:
                    args.setdefault("deal_name", quoted.group(1))
                if tool == "partner_artifacts":
                    for kw, action in _ARTIFACT_ACTIONS:
                        if kw in q:
                            args["action"] = action
                            break
                    if _missing_required_arguments(catalog[tool], args):
                        if "list_accounts" in tool_names:
                            return "list_accounts", {}
                        continue
                elif tool in _PARTNER_SCOPED_TOOLS and "partner_id" not in args:
                    if "partner_id" in (
                        (catalog[tool].get("inputSchema") or {}).get("required") or []
                    ):
                        if "list_accounts" in tool_names:
                            return "list_accounts", {}
                        continue
                return tool, args
            log.info(
                "Intent keywords matched %s but no candidate tools are live; falling to LLM picker.",
                keywords,
            )
            return None

    # Broad partner question: prefer live admin/partner discovery tools.
    if "partner" in q:
        for tool in ("partners", "partner_directory_search", "list_accounts"):
            if tool not in tool_names:
                continue
            args = {"query": quoted.group(1)} if quoted and tool == "partner_directory_search" else {}
            if tool == "partners" and "pending" in q:
                args["action"] = "pending"
            elif tool == "partners" and any(w in q for w in ("how many", "count", "summary")):
                args["action"] = "summary"
            return tool, args
        return _fallback_route(tools)

    return None


def _try_parse_json(text: str) -> Any | None:
    if not text or not isinstance(text, str) or text.startswith("[tool error]"):
        return None
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        for a, b in (("{", "}"), ("[", "]")):
            start, end = s.find(a), s.rfind(b)
            if start >= 0 and end > start:
                try:
                    return json.loads(s[start : end + 1])
                except json.JSONDecodeError:
                    pass
    return None


def _cell(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        if all(isinstance(x, (str, int, float, bool)) or x is None for x in value):
            return ", ".join("" if x is None else str(x) for x in value)
        return json.dumps(value, default=str)[:400]
    if isinstance(value, dict):
        return json.dumps(value, default=str)[:400]
    return str(value)[:400]


def _records_from_payload(payload: Any, *, tool: str = "") -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        rows = []
        for i, item in enumerate(payload):
            if isinstance(item, dict):
                rows.append({"_tool": tool, **{k: _cell(v) for k, v in item.items()}})
            else:
                rows.append({"_tool": tool, "value": _cell(item)})
        return rows
    if isinstance(payload, dict):
        for key in ("data", "items", "results", "partners", "deals", "accounts", "records", "rows", "artifacts"):
            if isinstance(payload.get(key), list):
                return _records_from_payload(payload[key], tool=tool)
        return [{"_tool": tool, **{k: _cell(v) for k, v in payload.items()}}]
    return [{"_tool": tool, "value": _cell(payload)}]


def _df_from_tool_results(tool_results: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for tr in tool_results:
        tool = tr.get("name", "")
        parsed = tr.get("parsed")
        if parsed is None and not tr.get("error"):
            parsed = _try_parse_json(tr.get("raw") or "")
        if parsed is None:
            continue
        rows.extend(_records_from_payload(parsed, tool=tool))
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _record_tool(
    tool_results: list[dict[str, Any]],
    name: str,
    arguments: dict,
    result_text: str,
) -> None:
    raw = result_text or ""
    error = raw if raw.startswith("[tool error]") else ""
    parsed = None if error else _try_parse_json(raw)
    tool_results.append(
        {
            "name": name,
            "arguments": arguments or {},
            "raw": raw,
            "parsed": parsed,
            "error": error,
        }
    )


def _execute_tool(
    client: EulerMCPClient,
    tools: dict[str, dict[str, Any]],
    tool_results: list[dict[str, Any]],
    name: str,
    arguments: dict[str, Any] | None = None,
) -> bool:
    """Validate and execute one tool call.

    Validation happens before the network call so a model cannot turn a
    missing required field into a noisy MCP validation loop.
    """
    args = dict(arguments or {})
    tool = tools.get(name)
    if tool is None:
        log.warning("Skipping unavailable EULER tool: %s", name)
        return False

    missing = _missing_required_arguments(tool, args)
    if missing:
        log.warning(
            "Skipping invalid EULER tool call name=%s missing_required=%s args=%s",
            name,
            missing,
            args,
        )
        return False

    log.info("Calling EULER tool name=%s args=%s", name, args)
    try:
        result_text = client.call_tool(name, args)
    except Exception as exc:
        result_text = f"[tool error] {exc}"
    _record_tool(tool_results, name, args, result_text)
    return not tool_results[-1].get("error")


def _summarize_for_human(
    question: str,
    tool_results: list[dict[str, Any]],
    *,
    model: str | None,
    temperature: float,
    top_p: float,
    max_tokens: int,
    available_tools: list[str] | None = None,
) -> str:
    """Second-stage LLM call: natural language answer only, no tool JSON."""
    successful_results = [tr for tr in tool_results if not tr.get("error")]
    if not tool_results:
        if available_tools:
            return (
                "I couldn't match that request to a live EULER tool.\n\n"
                f"Tools confirmed available: **{', '.join(available_tools)}**.\n\n"
                "Ask \"what can you do?\" to discover the available capabilities."
            )
        return "I wasn't able to retrieve live EULER data for that question."
    if not successful_results:
        failed_tools = ", ".join(str(tr.get("name") or "unknown") for tr in tool_results)
        available_hint = (
            f"\n\nTools confirmed available on your EULER account: **{', '.join(available_tools)}**."
            if available_tools
            else "\n\nNo live tools were available to suggest."
        )
        return (
            f"The live EULER tool call failed for: **{failed_tools}**.\n\n"
            "That tool was advertised by the live catalog, but the request did not succeed."
            + available_hint
            + "\n\nTry one of the available tools above, or ask \"what can you do?\" "
            "to see the full live list."
        )

    blocks = []
    for tr in tool_results:
        raw = trim_tool_raw(tr.get("raw") or "", max_tokens=1500, model=model)
        blocks.append(
            f"Tool: {tr.get('name')}\n"
            f"Args: {json.dumps(tr.get('arguments') or {}, default=str)}\n"
            f"Result:\n{raw}"
        )
    payload = "\n\n---\n\n".join(blocks)

    messages = [
        {
            "role": "system",
            "content": (
                "You are a helpful partner-operations assistant for the EULER Partner Platform. "
                "Answer in clear, natural language for a business user. "
                "Use short paragraphs or bullets. Name concrete partners, IDs, and fields from the data. "
                "Do not dump raw JSON. Do not mention tool names unless useful. "
                "If the data is empty or errored, say so plainly and suggest what to try next. "
                "Never mention Project Euler or the mathematician Euler."
            ),
        },
        {
            "role": "user",
            "content": (
                f"User question:\n{question}\n\n"
                f"Live data from EULER:\n{payload}\n\n"
                "Write the answer now."
            ),
        },
    ]
    # Keep the summarizer prompt itself under a safe budget
    messages = fit_messages(messages, max_tokens=6000, model=model)
    log.debug("token_budget backend=%s for summary", _token_backend())

    try:
        return groq_chat(
            messages,
            model=model,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            use_cache=False,
        ).strip()
    except Exception as exc:
        log.warning("Summary LLM failed: %s", exc)
        df = _df_from_tool_results(tool_results)
        if df.empty:
            return f"Retrieved tool data but could not summarize it ({exc})."
        cols = [c for c in df.columns if not c.startswith("_")]
        lines = [f"Found {len(df)} record(s). Fields: {', '.join(cols)}.", ""]
        for _, row in df.head(5).iterrows():
            bits = [f"{c}: {row[c]}" for c in cols if str(row.get(c, "")).strip()]
            lines.append("- " + "; ".join(bits[:8]))
        return "\n".join(lines)

def _partner_id_from_row(item: dict[str, Any], *, prefer_partner_type: bool = True) -> str | None:
    if not isinstance(item, dict):
        return None
    explicit = item.get("partner_id")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    ptype = str(item.get("type") or item.get("account_type") or "").lower()
    if prefer_partner_type and ptype and "partner" not in ptype and "affiliate" not in ptype:
        return None
    bare = item.get("id")
    if isinstance(bare, str) and bare.strip():
        return bare.strip()
    return None


def _extract_partner_id(tool_results: list[dict[str, Any]]) -> str | None:
    """Pull a partner_id from list_accounts / partners / similar payloads."""
    for tr in tool_results:
        if tr.get("error"):
            continue
        parsed = tr.get("parsed")
        if parsed is None:
            parsed = _try_parse_json(tr.get("raw") or "")
        if parsed is None:
            continue

        if isinstance(parsed, dict):
            direct = _partner_id_from_row(parsed, prefer_partner_type=False)
            if direct and parsed.get("partner_id"):
                return direct

            for nest_key in ("accounts", "partners", "data", "items", "results", "records"):
                nest = parsed.get(nest_key)
                if not isinstance(nest, list):
                    continue
                for item in nest:
                    pid = _partner_id_from_row(item, prefer_partner_type=True)
                    if pid:
                        return pid
                for item in nest:
                    pid = _partner_id_from_row(item, prefer_partner_type=False)
                    if pid:
                        return pid

        if isinstance(parsed, list):
            for item in parsed:
                pid = _partner_id_from_row(item if isinstance(item, dict) else {}, prefer_partner_type=False)
                if pid:
                    return pid
    return None


def _infer_followup_tool(
    q_lower: str,
    tool_names: set[str],
    partner_id: str,
    already: set[str],
) -> tuple[str, dict[str, Any]] | tuple[None, dict]:
    """After list_accounts resolved a partner_id, pick the real data tool."""
    args_base = {"partner_id": partner_id}

    for kw, action in _ARTIFACT_ACTIONS:
        if kw in q_lower and "partner_artifacts" in tool_names and "partner_artifacts" not in already:
            return "partner_artifacts", {**args_base, "action": action}

    if any(k in q_lower for k in ("artifact", "document", "file")) and "partner_artifacts" in tool_names:
        if "partner_artifacts" not in already:
            return "partner_artifacts", args_base

    checks: list[tuple[tuple[str, ...], str, dict[str, Any]]] = [
        (("commission", "payout"), "commissions", args_base),
        (("performance", "kpi", "scorecard", "how am i performing"), "performance", args_base),
        (("sourced", "influenced", "attribution"), "influenced_sourced_deals", args_base),
        (("content search", "search content", "semantic"), "content_search", args_base),
        (("content", "shared file", "enablement"), "content_list", args_base),
        (("referral",), "referrals", args_base),
        (("user", "team", "role"), "partner_users", args_base),
        (("incentive", "inc 1", "inc1"), "partner_inc1_incentives", args_base),
        (("inc 2", "inc2", "tier badge"), "partner_inc2_incentives", args_base),
        (("service project", "si project"), "si_service_projects", args_base),
        (("deal", "pipeline"), "partner_artifacts", {**args_base, "action": "deals"}),
        (("fund", "mdf", "cif"), "fund_requests", args_base),
    ]
    for keywords, tool, args in checks:
        if any(k in q_lower for k in keywords) and tool in tool_names and tool not in already:
            return tool, args
    return None, {}

def run_euler_agent(
    messages: list[dict[str, str]],
    *,
    question: str | None = None,
    model: str | None = None,
    temperature: float = 0.2,
    top_p: float = 0.95,
    max_tokens: int = 600,
    max_rounds: int = MAX_TOOL_ROUNDS,
) -> dict[str, Any]:
    """
    Agentic loop against EULER MCP.

    Returns human-readable `answer` plus structured `tool_results` and `dataframe`.
    """
    empty = {
        "answer": "",
        "markdown": "",
        "tool_results": [],
        "dataframe": pd.DataFrame(),
        "error": "",
        "tools_available": [],
        "euler_live_fetch_ok": False,
    }

    # Prefer the explicit short question; fall back to last user message
    if not question:
        for m in reversed(messages):
            if m.get("role") == "user":
                # Prefer a line after "User question:" if present
                content = m.get("content") or ""
                if "User question:" in content:
                    question = content.split("User question:")[-1].strip()
                else:
                    question = content.strip()
                break
    question = (question or "").strip()

    client: EulerMCPClient | None = None
    tool_results: list[dict[str, Any]] = []
    try:
        client = EulerMCPClient()
        tools = client.list_tools()
        if not client.live_fetch_ok or not tools:
            log.warning(
                "mcp_agent: live tool fetch failed (live_fetch_ok=False) | question=%r",
                question[:120],
            )
            msg = _no_live_tools_message()
            empty["error"] = msg
            empty["answer"] = msg
            empty["markdown"] = msg
            return empty

        tool_names = {t.get("name") for t in tools if t.get("name")}

        log.info(
            "mcp_agent live tools: %s | question=%r",
            sorted(tool_names),
            question[:120],
        )
        tool_catalog = _tool_catalog(tools)

        # ── 1) Intent route or LLM-chosen tool ───────────────────────────
        routed = _route_intent(question, tools)
        if routed:
            name, args = routed
            log.info("Intent route → %s %s", name, args)
            succeeded = _execute_tool(client, tool_catalog, tool_results, name, args)
            if not succeeded:
                fallback = _fallback_route(tools, exclude={name})
                if fallback:
                    fallback_name, fallback_args = fallback
                    log.info("Route fallback → %s %s", fallback_name, fallback_args)
                    _execute_tool(
                        client,
                        tool_catalog,
                        tool_results,
                        fallback_name,
                        fallback_args,
                    )
        else:
            # Let the model pick a tool once
            pick_messages = [
                {
                    "role": "system",
                    "content": (
                        "You pick ONE EULER tool for the user question. "
                        "Use only the listed tools and obey each inputSchema, including required fields. "
                        "Never choose partner_artifacts for a broad partner question; use euler_help when "
                        "the request is ambiguous or a required field is unavailable. "
                        "Reply with ONLY a JSON tool block, no prose.\n\n"
                        f"Tools:\n{_tools_for_prompt(tools)}\n\n"
                        "Format:\n```tool\n{\"name\": \"tool_name\", \"arguments\": {}}\n```"
                    ),
                },
                {"role": "user", "content": question},
            ]
            pick = groq_chat(
                pick_messages,
                model=model,
                temperature=0.1,
                top_p=top_p,
                max_tokens=200,
                use_cache=False,
            )
            calls = [c for c in _extract_tool_calls(pick) if c["name"] in tool_names]
            valid_calls = []
            for call in calls[:2]:
                name = call["name"]
                args = call.get("arguments") or {}
                missing = _missing_required_arguments(tool_catalog[name], args)
                if missing:
                    log.warning(
                        "LLM selected %s without required arguments %s; skipping it.",
                        name,
                        missing,
                    )
                    continue
                valid_calls.append((name, args))

            if not valid_calls:
                fallback = _fallback_route(tools)
                valid_calls = [fallback] if fallback else []

            for name, args in valid_calls:
                log.info("LLM-picked tool → %s %s", name, args)
                _execute_tool(client, tool_catalog, tool_results, name, args)

            if tool_results and not any(not item.get("error") for item in tool_results):
                fallback = _fallback_route(
                    tools,
                    exclude={str(item.get("name")) for item in tool_results},
                )
                if fallback:
                    fallback_name, fallback_args = fallback
                    log.info("All LLM-picked calls failed; falling back to %s", fallback_name)
                    _execute_tool(
                        client,
                        tool_catalog,
                        tool_results,
                        fallback_name,
                        fallback_args,
                    )

        # ── 2) Auto-resolve partner_id and follow up ─────────────────────
        partner_id = _extract_partner_id(tool_results)
        if partner_id and tool_results and not tool_results[-1].get("error"):
            q_lower = question.lower()
            already = {str(tr.get("name")) for tr in tool_results}
            follow_name, follow_args = _infer_followup_tool(
                q_lower, tool_names, partner_id, already
            )
            if follow_name:
                log.info("Follow-up after partner_id=%s → %s %s", partner_id, follow_name, follow_args)
                _execute_tool(client, tool_catalog, tool_results, follow_name, follow_args)

        # ── 3) Human-readable answer ─────────────────────────────────────
        answer = _summarize_for_human(
            question,
            tool_results,
            model=model,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            available_tools=sorted(tool_names) if tool_names else None,
        )
        df = _df_from_tool_results(tool_results)
        all_calls_failed = bool(tool_results) and not any(
            not item.get("error") for item in tool_results
        )
        error = "" if not all_calls_failed else answer
        if not tool_results:
            error = "No compatible live EULER tool was available for this request."

        return {
            "answer": answer,
            "markdown": answer,
            "tool_results": tool_results,
            "dataframe": df,
            "error": error,
            "tools_available": sorted(tool_names),
            "euler_live_fetch_ok": True,
        }
    except Exception as exc:
        if client is None:
            log.warning("EULER client could not be created: %s", exc)
            msg = _no_live_tools_message(str(exc))
            empty["error"] = msg
            empty["answer"] = msg
            empty["markdown"] = msg
            return empty
        log.exception("run_euler_agent failed")
        empty["error"] = str(exc)
        empty["answer"] = f"Something went wrong talking to EULER: {exc}"
        empty["markdown"] = empty["answer"]
        empty["tool_results"] = tool_results
        if tool_results:
            empty["dataframe"] = _df_from_tool_results(tool_results)
        return empty
    finally:
        if client is not None:
            client.close()


def chat_with_euler_tools(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.2,
    top_p: float = 0.95,
    max_tokens: int = 600,
    max_rounds: int = MAX_TOOL_ROUNDS,
) -> str:
    result = run_euler_agent(
        messages,
        model=model,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        max_rounds=max_rounds,
    )
    return result.get("answer") or result.get("error") or ""
