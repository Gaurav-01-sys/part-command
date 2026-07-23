"""
Dependency-light LinearRAG-style retriever for the Partner Command Center.

The upstream LinearRAG project builds a relation-free graph over passages,
entities, and sentences, then retrieves by activating query entities and
aggregating passage importance. This module keeps that shape but adapts it to
the local CSV corpus without adding spaCy, torch, igraph, or embedding stores.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable

import pandas as pd

try:
    from markitdown import MarkItDown
except Exception:  # pragma: no cover - optional dependency
    MarkItDown = None


DATA = os.path.join(os.path.dirname(__file__), "..", "data")
TABLE_PATHS = {
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


STOPWORDS = {
    "about",
    "above",
    "across",
    "after",
    "again",
    "all",
    "and",
    "are",
    "between",
    "compare",
    "for",
    "from",
    "have",
    "highest",
    "into",
    "list",
    "more",
    "most",
    "partners",
    "partner",
    "per",
    "show",
    "than",
    "the",
    "their",
    "this",
    "top",
    "total",
    "what",
    "which",
    "with",
}

SYNONYMS = {
    "failed": {"error", "failure", "fail"},
    "failure": {"error", "failed", "fail"},
    "fail": {"error", "failed", "failure"},
    "expiring": {"expiry", "expires", "expire"},
    "cert": {"certification", "certifications"},
    "certs": {"certification", "certifications"},
}


@dataclass(frozen=True)
class Passage:
    id: str
    table: str
    text: str
    row: dict
    tokens: frozenset[str]
    entities: frozenset[str]


@dataclass(frozen=True)
class RetrievalHit:
    passage: Passage
    score: float
    reasons: tuple[str, ...]


_MARKITDOWN = None


def _get_markitdown():
    global _MARKITDOWN
    if MarkItDown is None:
        return None
    if _MARKITDOWN is None:
        _MARKITDOWN = MarkItDown()
    return _MARKITDOWN


def _normalize_token(token: str) -> str:
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def _tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for raw_token in re.findall(r"[a-zA-Z0-9_]+", text.lower()):
        for token in [raw_token, *raw_token.split("_")]:
            normalized = _normalize_token(token)
            if len(normalized) > 2 and normalized not in STOPWORDS:
                tokens.add(normalized)
                tokens.update(SYNONYMS.get(normalized, set()))
    return tokens


def _entity_text(value: object) -> str:
    text = str(value).strip().lower()
    return re.sub(r"\s+", " ", text)


def _fallback_markdown_table(df: pd.DataFrame, max_rows: int = 24) -> str:
    sample = df.head(max_rows).copy()
    columns = [str(col) for col in sample.columns.tolist()]
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for _, row in sample.iterrows():
        values = [str(row[col]) for col in sample.columns]
        lines.append("| " + " | ".join(values) + " |")
    if len(df) > max_rows:
        lines.append(f"\n*{len(df) - max_rows} more rows omitted from preview.*")
    return "\n".join(lines)


def _table_markdown(table: str, df: pd.DataFrame) -> str:
    converter = _get_markitdown()
    path = TABLE_PATHS.get(table)
    if converter and path and os.path.exists(path):
        try:
            result = converter.convert_local(path)
            text = getattr(result, "text_content", "") or ""
            if text.strip():
                return text.strip()
        except Exception:
            pass

    try:
        text = df.to_markdown(index=False)
        if text.strip():
            return text.strip()
    except Exception:
        pass

    return _fallback_markdown_table(df)


def _row_markdown(row: dict) -> str:
    parts = [f"- {key}: {value}" for key, value in row.items()]
    return "\n".join(parts)


def _row_entities(row: dict, table: str) -> set[str]:
    entities = {f"table:{table}"}
    for column, value in row.items():
        if pd.isna(value):
            continue
        value_text = _entity_text(value)
        if not value_text:
            continue

        column_text = _entity_text(column)
        entities.add(value_text)
        entities.add(f"{column_text}:{value_text}")
        for token in _tokens(value_text):
            entities.add(token)
            entities.add(f"{column_text}:{token}")
    return entities


def _build_passages(
    datasets: dict[str, pd.DataFrame],
    candidate_tables: Iterable[str],
    filter_frame,
    region: str,
    tier: str,
) -> list[Passage]:
    passages: list[Passage] = []
    for table in candidate_tables:
        df = filter_frame(datasets[table], region, tier)
        if df.empty:
            continue

        summary = {
            "row_count": int(len(df)),
            "columns": ", ".join(df.columns.astype(str).tolist()),
        }
        table_md = _table_markdown(table, df)
        summary_text = f"## {table}\n\n{table_md}\n\n> summary: {json.dumps(summary, default=str)}"
        passages.append(
            Passage(
                id=f"{table}:table",
                table=table,
                text=summary_text,
                row=summary,
                tokens=frozenset(_tokens(summary_text)),
                entities=frozenset({f"table:{table}", *[str(column).lower() for column in df.columns]}),
            )
        )

        for row_index, row in df.fillna("").iterrows():
            row_dict = row.to_dict()
            row_text = f"### {table} row {row_index}\n\n{_row_markdown(row_dict)}"
            passages.append(
                Passage(
                    id=f"{table}:{row_index}",
                    table=table,
                    text=row_text,
                    row=row_dict,
                    tokens=frozenset(_tokens(row_text)),
                    entities=frozenset(_row_entities(row_dict, table)),
                )
            )
    return passages


def _query_entities(query: str) -> set[str]:
    terms = _tokens(query)
    entities = set(terms)
    for phrase in re.findall(r"[a-zA-Z][a-zA-Z0-9_]*(?:\s+[a-zA-Z][a-zA-Z0-9_]*)+", query.lower()):
        cleaned = _entity_text(phrase)
        if len(_tokens(cleaned)) > 1:
            entities.add(cleaned)
    return entities


def _normalize(counter: Counter[str]) -> dict[str, float]:
    if not counter:
        return {}
    max_value = max(counter.values()) or 1
    return {key: value / max_value for key, value in counter.items()}


def retrieve(
    query: str,
    *,
    datasets: dict[str, pd.DataFrame],
    candidate_tables: Iterable[str],
    filter_frame,
    region: str = "All",
    tier: str = "All",
    top_k: int = 6,
) -> tuple[str, list[str], str, list[dict[str, object]]]:
    passages = _build_passages(datasets, candidate_tables, filter_frame, region, tier)
    if not passages:
        return "", [], "LinearRAG: no candidate passages after filters.", []

    entity_to_passages: dict[str, set[str]] = defaultdict(set)
    passage_by_id = {passage.id: passage for passage in passages}
    for passage in passages:
        for entity in passage.entities:
            entity_to_passages[entity].add(passage.id)

    query_terms = _tokens(query)
    query_entities = _query_entities(query)
    seed_entities = {
        entity
        for entity in entity_to_passages
        if entity in query_entities or bool(query_terms & _tokens(entity))
    }

    entity_scores: Counter[str] = Counter()
    passage_scores: Counter[str] = Counter()
    reasons: dict[str, set[str]] = defaultdict(set)

    for entity in seed_entities:
        score = 1.0 + len(query_terms & _tokens(entity))
        entity_scores[entity] += score
        for passage_id in entity_to_passages[entity]:
            passage_scores[passage_id] += score
            reasons[passage_id].add(f"seed_entity={entity}")

    normalized_entities = _normalize(entity_scores)
    for passage in passages:
        lexical_overlap = len(query_terms & passage.tokens)
        if lexical_overlap:
            passage_scores[passage.id] += 0.75 * lexical_overlap
            reasons[passage.id].add(f"token_overlap={lexical_overlap}")

        for column, value in passage.row.items():
            column_text = str(column).lower()
            value_overlap = query_terms & _tokens(str(value))
            if not value_overlap:
                continue
            if column_text in {"status", "run_status", "churn_risk"}:
                passage_scores[passage.id] += 12.0
                reasons[passage.id].add(f"status_match={column_text}")
            elif column_text in {"source_freshness", "overage_flag"}:
                passage_scores[passage.id] += 1.5
                reasons[passage.id].add(f"attribute_match={column_text}")

        shared_entity_bonus = sum(normalized_entities.get(entity, 0.0) for entity in passage.entities)
        if shared_entity_bonus:
            passage_scores[passage.id] += math.log1p(shared_entity_bonus)
            reasons[passage.id].add("shared_entity_propagation")

    if not passage_scores:
        for passage in passages[:top_k]:
            passage_scores[passage.id] = 0.01
            reasons[passage.id].add("fallback")

    hits = [
        RetrievalHit(passage_by_id[passage_id], score, tuple(sorted(reasons[passage_id])))
        for passage_id, score in passage_scores.items()
    ]
    hits.sort(key=lambda hit: hit.score, reverse=True)
    top_hits = hits[:top_k]

    table_names = list(dict.fromkeys(hit.passage.table for hit in top_hits))
    context = "\n\n".join(hit.passage.text for hit in top_hits)[:3200]
    hits_data = [
        {
            "passage_id": hit.passage.id,
            "label": hit.passage.id,
            "table": hit.passage.table,
            "score": round(hit.score, 3),
            "reasons": "; ".join(hit.reasons) or "none",
            "snippet": hit.passage.text[:350],
        }
        for hit in top_hits
    ]
    trace_lines = [
        "LinearRAG retrieval:",
        f"- query_terms={', '.join(sorted(query_terms)) or 'none'}",
        f"- activated_entities={', '.join(sorted(seed_entities)[:12]) or 'none'}",
        "- hits:",
    ]
    for hit in top_hits:
        trace_lines.append(
            f"  {hit.passage.id} score={hit.score:.3f} reasons={'; '.join(hit.reasons) or 'none'}"
        )

    return context, table_names, "\n".join(trace_lines), hits_data
