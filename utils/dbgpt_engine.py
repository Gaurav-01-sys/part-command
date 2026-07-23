"""
Hybrid SQL + local context engine for Partner Command Center.

The app now talks directly to NVIDIA's OpenAI-compatible chat endpoint. That
keeps the inference layer simple and avoids provider-specific branching in the
application code.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3

import pandas as pd
from dotenv import load_dotenv
from utils.claude_llm import chat_completion

load_dotenv()

DATA = os.path.join(os.path.dirname(__file__), "..", "data")

TABLE_MAP = {
    "ms_partners": f"{DATA}/microsoft/partners.csv",
    "ms_deals": f"{DATA}/microsoft/deals.csv",
    "ms_certs": f"{DATA}/microsoft/certifications.csv",
    "sf_fact_deals": f"{DATA}/snowflake/fact_deals.csv",
    "sf_dim_partners": f"{DATA}/snowflake/dim_partners.csv",
    "db_usage": f"{DATA}/databricks/product_usage.csv",
    "db_health": f"{DATA}/databricks/partner_health_scores.csv",
    "dbt_models": f"{DATA}/dbt/model_run_results.csv",
    "coalesce_nodes": f"{DATA}/coalesce/pipeline_runs.csv",
}

SOURCE_TABLES = {
    "microsoft": ["ms_partners", "ms_deals", "ms_certs"],
    "snowflake": ["sf_fact_deals", "sf_dim_partners"],
    "databricks": ["db_usage", "db_health"],
    "dbt": ["dbt_models"],
    "coalesce": ["coalesce_nodes"],
}

_conn: sqlite3.Connection | None = None
_datasets: dict[str, pd.DataFrame] | None = None


def _load_datasets() -> dict[str, pd.DataFrame]:
    global _datasets
    if _datasets is None:
        _datasets = {}
        for table, path in TABLE_MAP.items():
            _datasets[table] = pd.read_csv(path)
    return _datasets


def get_connection() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(":memory:", check_same_thread=False)
        for table, df in _load_datasets().items():
            df.to_sql(table, _conn, if_exists="replace", index=False)
    return _conn


def run_sql(sql: str) -> tuple[pd.DataFrame, str]:
    conn = get_connection()
    try:
        df = pd.read_sql_query(sql, conn)
        return df, ""
    except Exception as exc:
        return pd.DataFrame(), str(exc)


def _chat_completion(
    messages: list[dict[str, str]],
    *,
    documents: list[dict[str, str]] | None = None,
    temperature: float = 0.1,
    max_tokens: int = 900,
) -> str:
    if documents:
        document_text = "\n\n".join(
            f"{item.get('title', 'Document')}: {item.get('content', '')}" for item in documents
        )
        messages = [
            *messages,
            {"role": "system", "content": f"Additional retrieved context:\n{document_text}"},
        ]

    return chat_completion(
        messages,
        temperature=temperature,
        top_p=0.95,
        max_tokens=max_tokens,
    )


def _schema_summary() -> str:
    parts: list[str] = []
    for table, df in _load_datasets().items():
        cols = ", ".join(df.columns.tolist())
        parts.append(f"{table}({cols})")
    return "\n".join(parts)


def _candidate_tables(source: str) -> list[str]:
    if source == "All":
        return list(TABLE_MAP.keys())
    return SOURCE_TABLES.get(source.lower(), list(TABLE_MAP.keys()))


def _filter_context_frame(df: pd.DataFrame, table: str, region: str, tier: str) -> pd.DataFrame:
    filtered = df.copy()

    if region != "All" and "region" in filtered.columns:
        filtered = filtered[filtered["region"] == region]
    if tier != "All" and "tier" in filtered.columns:
        filtered = filtered[filtered["tier"] == tier]

    if (region != "All" or tier != "All") and "partner_id" in filtered.columns:
        partners = _load_datasets()["ms_partners"][["partner_id", "region", "tier"]].drop_duplicates()
        filtered = filtered.merge(partners, on="partner_id", how="left", suffixes=("", "_partner"))
        if region != "All" and "region_partner" in filtered.columns:
            filtered = filtered[filtered["region_partner"] == region]
        if tier != "All" and "tier_partner" in filtered.columns:
            filtered = filtered[filtered["tier_partner"] == tier]
        drop_cols = [col for col in ("region_partner", "tier_partner") if col in filtered.columns]
        if drop_cols:
            filtered = filtered.drop(columns=drop_cols)

    return filtered


def _question_terms(question: str) -> set[str]:
    return {term for term in re.findall(r"[a-zA-Z0-9_]+", question.lower()) if len(term) > 2}


def _local_context(question: str, region: str, tier: str, source: str, top_k: int = 6) -> str:
    terms = _question_terms(question)
    docs: list[tuple[int, str]] = []

    for table in _candidate_tables(source):
        df = _filter_context_frame(_load_datasets()[table], table, region, tier)
        if df.empty:
            continue

        for _, row in df.head(12).iterrows():
            row_text = json.dumps(row.fillna("").to_dict(), default=str)
            score = sum(term in row_text.lower() for term in terms)
            score += sum(term in table.lower() for term in terms)
            if score == 0 and terms:
                continue
            docs.append((score, f"{table}: {row_text}"))

    if not docs:
        for table in _candidate_tables(source):
            df = _filter_context_frame(_load_datasets()[table], table, region, tier)
            if not df.empty:
                fallback = [f"{table}: {json.dumps(row.fillna('').to_dict(), default=str)}" for _, row in df.head(2).iterrows()]
                return "\n\n".join(fallback)[:2000]
        return ""

    docs.sort(key=lambda item: item[0], reverse=True)
    return "\n\n".join(text for _, text in docs[:top_k])[:2000]


def _extract_json_block(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in: {text}")
    return json.loads(match.group(0))


def ask(question: str, history: list[dict], region: str = "All", tier: str = "All", source: str = "All") -> dict:
    """
    Hybrid query: SQLite for precision plus lightweight local context for narrative help.
    """
    try:
        metadata_filters: dict[str, str] = {}
        if region != "All":
            metadata_filters["region"] = region
        if tier != "All":
            metadata_filters["tier"] = tier
        if source != "All":
            metadata_filters["source"] = source.lower()

        system_prompt = f"""
You are an analyst for Partner Command Center.

Use the SQLite tables below when a tabular answer is possible.
Return valid JSON only with this schema:
{{
  "strategy": "sql" | "rag" | "hybrid",
  "sql": "SQLite SELECT statement or empty string",
  "rag_query": "query to use for local context",
  "metadata_filters": {json.dumps(metadata_filters)}
}}

Rules:
- Prefer "sql" or "hybrid" for questions about counts, sums, rankings, trends, filters, comparisons, and tables.
- Only output SQLite-compatible SELECT statements. Never use markdown fences.
- Respect the provided filters when they can be applied.
- Use these tables:
{_schema_summary()}
""".strip()

        plan_text = _chat_completion(
            [{"role": "system", "content": system_prompt}, *history, {"role": "user", "content": question}],
            temperature=1e-8,
            max_tokens=700,
        )
        plan = _extract_json_block(plan_text)

        strategy = plan.get("strategy", "hybrid")
        sql = str(plan.get("sql", "") or "").strip()
        rag_query = str(plan.get("rag_query", "") or question)

        result_df = pd.DataFrame()
        error = ""
        sql_warning = ""

        if strategy in {"sql", "hybrid"} and sql and "SELECT" in sql.upper():
            result_df, sql_error = run_sql(sql)
            if sql_error:
                sql_warning = sql_error
                strategy = "rag"

        rag_context = ""
        if strategy in {"rag", "hybrid"}:
            rag_context = _local_context(rag_query, region, tier, source)

        if sql_warning:
            if rag_context:
                rag_context = f"SQL fallback reason: {sql_warning}\n\n{rag_context}"
            else:
                error = sql_warning

        if strategy == "hybrid" and not result_df.empty and rag_context:
            summary_prompt = (
                "Summarize the SQL result and context in 4 short bullet points.\n\n"
                f"Question: {question}\n\n"
                f"SQL result:\n{result_df.head(12).to_string(index=False)}\n\n"
                f"Local context:\n{rag_context}"
            )
            try:
                rag_context = _chat_completion(
                    [{"role": "user", "content": summary_prompt}],
                    temperature=0.2,
                    max_tokens=400,
                )
            except Exception:
                pass

        chart_spec = {"chart_type": "none", "x": None, "y": None, "color": None}
        if not result_df.empty and len(result_df.columns) >= 2:
            chart_spec = {
                "chart_type": "bar" if len(result_df) < 15 else "line",
                "x": result_df.columns[0],
                "y": result_df.columns[1],
                "color": result_df.columns[2] if len(result_df.columns) > 2 else None,
            }

        return {
            "strategy": strategy,
            "sql": sql or "Context-only query",
            "dataframe": result_df,
            "chart_spec": chart_spec,
            "error": error,
            "rag_context": rag_context[:1200] if rag_context else "",
        }
    except Exception as exc:
        return {
            "strategy": "error",
            "sql": "",
            "dataframe": pd.DataFrame(),
            "chart_spec": {},
            "error": f"Hybrid query error: {exc}",
            "rag_context": "",
        }


def dbgpt_clear(history_state):
    return [], "", pd.DataFrame(), None, ""
