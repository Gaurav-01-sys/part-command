from __future__ import annotations

import json
import os
import sqlite3

import pandas as pd
from dotenv import load_dotenv

# ── Retrieval: BM25 (pure-Python, no server required) ─────────────────
try:
    from utils.bm25_rag_engine import retrieve as bm25_retrieve, index_status as bm25_index_status
    _BM25_AVAILABLE = True
except Exception:
    bm25_retrieve = None  # type: ignore[assignment]
    bm25_index_status = None  # type: ignore[assignment]
    _BM25_AVAILABLE = False
from utils.claude_llm import chat_completion as claude_chat, get_euler_status
from utils.groq_llm import chat_completion as groq_chat

load_dotenv()

# DATA = os.path.join(os.path.dirname(__file__), "..", "data")

# TABLE_MAP = {
#     "ms_partners": f"{DATA}/microsoft/partners.csv",
#     "ms_deals": f"{DATA}/microsoft/deals.csv",
#     "ms_certs": f"{DATA}/microsoft/certifications.csv",
#     "sf_fact_deals": f"{DATA}/snowflake/fact_deals.csv",
#     "sf_dim_partners": f"{DATA}/snowflake/dim_partners.csv",
#     "db_usage": f"{DATA}/databricks/product_usage.csv",
#     "db_health": f"{DATA}/databricks/partner_health_scores.csv",
#     "dbt_models": f"{DATA}/dbt/model_run_results.csv",
#     "coalesce_nodes": f"{DATA}/coalesce/pipeline_runs.csv",
# }

# SOURCE_TABLES = {
#     "microsoft": ["ms_partners", "ms_deals", "ms_certs"],
#     "snowflake": ["sf_fact_deals", "sf_dim_partners"],
#     "databricks": ["db_usage", "db_health"],
#     "dbt": ["dbt_models"],
#     "coalesce": ["coalesce_nodes"],
# }

# _conn: sqlite3.Connection | None = None
# _datasets: dict[str, pd.DataFrame] | None = None


# def _load_datasets() -> dict[str, pd.DataFrame]:
#     global _datasets
#     if _datasets is None:
#         _datasets = {}
#         for table, path in TABLE_MAP.items():
#             _datasets[table] = pd.read_csv(path)
#     return _datasets


def get_connection():
    """No-op stub — synthetic SQLite DB is disabled."""
    return None


# def _candidate_tables(source: str) -> list[str]:
#     if source == "All":
#         return list(TABLE_MAP.keys())
#     return SOURCE_TABLES.get(source.lower(), list(TABLE_MAP.keys()))


# def _filter_frame(df: pd.DataFrame, region: str, tier: str) -> pd.DataFrame:
#     filtered = df.copy()
#
#     if region != "All" and "region" in filtered.columns:
#         filtered = filtered[filtered["region"] == region]
#     if tier != "All" and "tier" in filtered.columns:
#         filtered = filtered[filtered["tier"] == tier]
#
#     if (region != "All" or tier != "All") and "partner_id" in filtered.columns:
#         partners = _load_datasets()["ms_partners"][["partner_id", "region", "tier"]].drop_duplicates()
#         filtered = filtered.merge(partners, on="partner_id", how="left", suffixes=("", "_partner"))
#         if region != "All" and "region_partner" in filtered.columns:
#             filtered = filtered[filtered["region_partner"] == region]
#         if tier != "All" and "tier_partner" in filtered.columns:
#             filtered = filtered[filtered["tier_partner"] == tier]
#         filtered = filtered.drop(columns=[c for c in ("region_partner", "tier_partner") if c in filtered.columns])
#
#     return filtered


def _history_summary(history: list[dict]) -> str:
    if not history:
        return "No prior conversation."
    try:
        from utils.token_budget import trim_text
    except Exception:
        trim_text = None  # type: ignore

    parts: list[str] = []
    for item in history[-6:]:
        role = item.get("role", "unknown")
        content = str(item.get("content", "")).strip()
        if trim_text is not None:
            content = trim_text(content, max_tokens=120)
        else:
            content = content[:300]
        parts.append(f"{role}: {content}")
    return "\n".join(parts)


def _hits_frame(hits: list[dict[str, object]]) -> pd.DataFrame:
    if not hits:
        return pd.DataFrame(columns=["label", "table", "score", "reasons", "snippet"])
    df = pd.DataFrame(hits)
    if "passage_id" in df.columns and "label" not in df.columns:
        df["label"] = df["passage_id"]
    return df


def _display_frame(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean tool/RAG frames for the UI grid:
    - drop internal columns (_tool, _index, …)
    - friendly column titles
    - shorten very long IDs for readability
    """
    if df is None or df.empty:
        return pd.DataFrame()

    out = df.copy()
    drop_cols = [c for c in out.columns if str(c).startswith("_")]
    out = out.drop(columns=drop_cols, errors="ignore")

    # Prefer a useful column order when present
    preferred = [
        "name", "type", "affiliate_company_name", "partner_id", "company_id",
        "id", "dashboard_url", "status", "tier", "region", "score", "label", "table",
    ]
    ordered = [c for c in preferred if c in out.columns]
    ordered += [c for c in out.columns if c not in ordered]
    out = out[ordered]

    # Shorten long opaque IDs for display (keep full value in tooltip via raw tool_results)
    for col in out.columns:
        if out[col].dtype == object:
            out[col] = out[col].map(
                lambda v: (
                    (str(v)[:18] + "…") if isinstance(v, str) and len(v) > 28 and ("x" in v or ":" in v)
                    else v
                )
            )

    # Title-case headers for the grid
    out = out.rename(columns={c: str(c).replace("_", " ").strip().title() for c in out.columns})
    return out


def _chart_spec_for_hits(df: pd.DataFrame) -> dict:
    """
    Only emit a chart when there is meaningful categorical + numeric data.
    Single-row account lookups and ID-only frames return chart_type=none
    so the UI does not render a useless bar of partner IDs.
    """
    if df is None or df.empty:
        return {"chart_type": "none", "x": None, "y": None, "color": None}

    # Work on a copy without internal cols
    cols = [c for c in df.columns if not str(c).startswith("_")]
    if len(cols) < 2 or len(df) < 2:
        return {"chart_type": "none", "x": None, "y": None, "color": None}

    numeric = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]
    # score-like columns are the only ones worth charting for partner data
    score_cols = [c for c in numeric if str(c).lower() in ("score", "count", "amount", "value", "total", "revenue")]
    if not score_cols:
        return {"chart_type": "none", "x": None, "y": None, "color": None}

    cat_candidates = [c for c in cols if c not in numeric and str(c).lower() in (
        "name", "label", "partner", "tier", "region", "status", "type", "table"
    )]
    x = cat_candidates[0] if cat_candidates else cols[0]
    y = score_cols[0]
    color = "table" if "table" in df.columns else ("tier" if "tier" in df.columns else None)
    return {"chart_type": "bar", "x": x, "y": y, "color": color, "title": f"{y} by {x}"}


def ask(question: str, history: list[dict], region: str = "All", tier: str = "All", source: str = "All", model_provider: str = "Claude") -> dict:
    """Route the user's question directly to the LLM (Claude or Groq).

    Synthetic CSV retrieval is disabled — the LLM relies exclusively on
    EULER MCP tools (when connected) to answer partner-related questions.
    """
    try:
        if not question.strip():
            return {
                "strategy": "euler_mcp",
                "answer": "",
                "sql": "",
                "dataframe": pd.DataFrame(),
                "chart_specs": [{"chart_type": "none", "x": None, "y": None, "color": None}],
                "error": "",
                "trace": "",
                "provider": "",
                "providers_used": [],
                "retrieved_context": "",
                "subqueries": [],
                "tool_results": [],
                "markdown": "",
                "table_names": [],
                "euler_live_fetch_ok": False,
            }

        # ── BM25RAG retrieval (pure-Python, in-process, no server) ────────
        if _BM25_AVAILABLE and bm25_retrieve is not None and bm25_index_status is not None:
            status = bm25_index_status()
            if status["built"]:
                try:
                    context, table_names, trace, hits = bm25_retrieve(
                        question,
                        region=region,
                        tier=tier,
                        source=source,
                        top_k=6,
                    )
                except Exception as _bm25_err:
                    context = ""
                    table_names = []
                    trace = f"BM25RAG: skipped ({_bm25_err})"
                    hits = []
            else:
                context = ""
                table_names = []
                trace = "BM25RAG: index not built (call index_euler_data() to enable)"
                hits = []
        else:
            context = ""
            table_names: list[str] = []
            trace = "BM25RAG: skipped (bm25s not installed)"
            hits: list[dict] = []

        use_groq = model_provider.lower().startswith("groq")
        status = get_euler_status()
        euler_on = bool(status.get("enabled"))
        # Render / .env: honour EULER_MCP_TOKEN even if OAuth store is empty
        if not euler_on and (os.getenv("EULER_MCP_TOKEN") or "").strip():
            euler_on = True
        # Claude → Anthropic hosted MCP connector
        use_claude_mcp = euler_on and not use_groq
        # Groq → our MCP client + tool loop (utils/mcp_agent_engine.py)
        use_groq_mcp = euler_on and use_groq

        groq_model = None
        if use_groq:
            # NOTE: Groq deprecated qwen/qwen3-32b (shutdown 2026-07-17, already
            # past) and llama-3.3-70b-versatile (shutdown 2026-08-16, imminent).
            # Both branches below point at their recommended replacements —
            # see https://console.groq.com/docs/deprecations before changing.
            mp = model_provider.lower()
            if "qwen" in mp:
                groq_model = "qwen/qwen3.6-27b"
            else:
                # Covers "gpt-oss" and the plain "Groq" default alike.
                groq_model = "openai/gpt-oss-120b"

        live_tools = use_claude_mcp or use_groq_mcp
        system_prompt = (
            "You are the Partner Command Center assistant for the EULER Partner Platform "
            "(eulerapp.com — partner / channel data lake). "
            "The word EULER always means this platform, never the mathematician, "
            "Project Euler, or Euler's theorem.\n"
        ) + (
            "You have live tool access to EULER. Use only the tools exposed by "
            "the live connector for current data, and do not invent partner records.\n"
            if live_tools
            else "Live EULER tools are NOT connected right now. Say so if the user needs live partner data.\n"
        ) + """
If the user's question is best answered visually, you may generate one or more chart specifications in your answer.
To do so, include a JSON block exactly like this:
```json
{
  "charts": [
    {"chart_type": "bar", "x": "column_name", "y": "column_name", "title": "Chart Title"}
  ]
}
```
Available chart_type: 'bar', 'line', 'pie', 'scatter'.
Only use columns that are explicitly mentioned in the context or that you can synthesize into a table format.
"""

        prompt = f"""
Use{" the live EULER Partner Platform tools and" if live_tools else ""} the prior conversation to answer the user's question.
If the information is incomplete, say so directly.
Prefer concise, factual prose with short bullets when useful.

Conversation context:
{_history_summary(history)}
{(chr(10) + 'Retrieved context:' + chr(10) + context + chr(10)) if context else ''}
User question:
{question}
""".strip()

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        tool_results: list = []
        markdown = ""
        tool_df = pd.DataFrame()
        agent_error = ""
        euler_live_fetch_ok = False

        if use_groq_mcp:
            from utils.mcp_agent_engine import run_euler_agent

            agent_out = run_euler_agent(
                messages,
                question=question,  # short original question only — not the prompt blob
                model=groq_model,
                temperature=0.2,
                top_p=0.95,
                max_tokens=1200,
            )
            answer = agent_out.get("answer") or agent_out.get("error") or ""
            markdown = agent_out.get("markdown") or answer
            tool_results = agent_out.get("tool_results") or []
            agent_error = agent_out.get("error") or ""
            euler_live_fetch_ok = bool(agent_out.get("euler_live_fetch_ok"))
            tool_df = agent_out.get("dataframe")
            if tool_df is None:
                tool_df = pd.DataFrame()
        elif use_groq:
            answer = groq_chat(
                messages,
                model=groq_model,
                temperature=0.2,
                top_p=0.95,
                max_tokens=650,
            )
            markdown = answer
        else:
            answer = claude_chat(
                messages,
                model=None,
                temperature=0.2,
                top_p=0.95,
                max_tokens=1500 if use_claude_mcp else 650,
            )
            markdown = answer

        import re
        chart_specs = []
        json_match = re.search(r"```json\s*(.*?)\s*```", answer, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group(1))
                if "charts" in parsed:
                    chart_specs = parsed["charts"]
            except Exception:
                pass

        hits_df = _hits_frame(hits)
        # Prefer structured MCP tool rows in the grid when present
        if tool_df is not None and not tool_df.empty:
            raw_df = tool_df
        else:
            raw_df = hits_df

        # Chart from raw (pre-display) frame; grid gets the cleaned display frame
        if not chart_specs:
            chart_specs = [_chart_spec_for_hits(raw_df)]
        result_df = _display_frame(raw_df)

        if use_groq_mcp and euler_live_fetch_ok:
            provider_label = "groq+euler_mcp"
            providers_used_list = ["groq", "euler_mcp"]
        elif use_groq_mcp:
            provider_label = "groq (EULER unavailable)"
            providers_used_list = ["groq"]
        elif use_groq:
            provider_label = "groq"
            providers_used_list = ["groq"]
        elif use_claude_mcp:
            provider_label = "claude+euler_mcp"
            providers_used_list = ["claude", "euler_mcp"]
        else:
            provider_label = "claude"
            providers_used_list = ["claude"]

        return {
            "strategy": "euler_mcp",
            "answer": answer,
            "sql": answer,
            "markdown": markdown,
            "dataframe": result_df,
            "chart_specs": chart_specs,
            "error": agent_error,
            "trace": trace,
            "provider": provider_label,
            "providers_used": providers_used_list,
            "retrieved_context": context,
            "subqueries": [],
            "table_names": table_names,
            "tool_results": tool_results,
            "euler_live_fetch_ok": euler_live_fetch_ok,
        }
    except Exception as exc:
        use_mcp_err = get_euler_status()["enabled"]
        return {
            "strategy": "error",
            "answer": "",
            "sql": "",
            "markdown": "",
            "dataframe": pd.DataFrame(),
            "chart_specs": [{"chart_type": "none", "x": None, "y": None, "color": None}],
            "error": f"Query error: {exc}",
            "trace": "",
            "provider": "claude" + ("+euler_mcp" if use_mcp_err else ""),
            "providers_used": ["claude", "euler_mcp"] if use_mcp_err else ["claude"],
            "retrieved_context": "",
            "subqueries": [],
            "table_names": [],
            "tool_results": [],
            "euler_live_fetch_ok": False,
        }