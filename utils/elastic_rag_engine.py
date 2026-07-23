"""
utils/elastic_rag_engine.py
----------------------------
Elasticsearch-backed retriever for the Partner Command Center.

Drop-in replacement for linear_rag_engine.retrieve().
Same function signature — swap the import in linear_query_engine.py to enable.

HOW IT WORKS
------------
1. Index phase  (run once, or on a schedule via index_euler_data()):
   - Pulls live partner data from EULER REST API (euler_api.py)
   - Serialises each row to a text passage + metadata document
   - Bulk-indexes into Elasticsearch index "euler-partners"

2. Retrieve phase  (called per user question):
   - Runs a BM25 multi_match query against the question
   - Applies region / tier / source filters as ES filter clauses
   - Returns top-k passages as context string  (same shape as LinearRAG)

SETUP
-----
Option A – local Docker (free, no account):
    docker run -d --name es -p 9200:9200 \
        -e "discovery.type=single-node" \
        -e "xpack.security.enabled=false" \
        docker.elastic.co/elasticsearch/elasticsearch:8.13.0

Option B – Elastic Cloud (managed):
    https://cloud.elastic.co  →  create deployment  →  copy Cloud ID + API key

Add to .env:
    ES_URL=http://localhost:9200          # or your Cloud endpoint
    ES_API_KEY=                           # leave blank for local no-auth
    ES_INDEX=euler-partners               # index name (default shown)

Then call:
    from utils.elastic_rag_engine import index_euler_data
    index_euler_data()   # run once to populate the index
"""

from __future__ import annotations

import json
import os
from typing import Iterable

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

ES_URL     = os.getenv("ES_URL",   "http://localhost:9200")
ES_API_KEY = os.getenv("ES_API_KEY", "")
ES_INDEX   = os.getenv("ES_INDEX", "euler-partners")

# ── Lazy ES client (avoids hard import error if elasticsearch not installed) ──

_es_client = None


def _get_client():
    """Return a cached Elasticsearch client, or raise a clear error."""
    global _es_client
    if _es_client is not None:
        return _es_client

    try:
        from elasticsearch import Elasticsearch
    except ImportError as exc:
        raise RuntimeError(
            "elasticsearch-py is not installed. "
            "Run:  uv pip install 'elasticsearch>=8,<9'"
        ) from exc

    kwargs: dict = {"hosts": [ES_URL]}
    if ES_API_KEY:
        kwargs["api_key"] = ES_API_KEY

    _es_client = Elasticsearch(**kwargs)

    # Verify connectivity
    if not _es_client.ping():
        raise RuntimeError(
            f"Could not connect to Elasticsearch at {ES_URL}. "
            "Check that ES is running and ES_URL is correct in .env."
        )
    return _es_client


# ── Index helpers ─────────────────────────────────────────────────────────────

_INDEX_MAPPING = {
    "mappings": {
        "properties": {
            "text":       {"type": "text",    "analyzer": "english"},
            "table":      {"type": "keyword"},
            "region":     {"type": "keyword"},
            "tier":       {"type": "keyword"},
            "source":     {"type": "keyword"},
            "partner_id": {"type": "keyword"},
            "row_json":   {"type": "object",  "enabled": False},  # stored, not indexed
        }
    },
    "settings": {
        "number_of_shards":   1,
        "number_of_replicas": 0,
    },
}


def _ensure_index(es) -> None:
    """Create the ES index if it does not exist yet."""
    if not es.indices.exists(index=ES_INDEX):
        es.indices.create(index=ES_INDEX, body=_INDEX_MAPPING)
        print(f"[ElasticRAG] Created index '{ES_INDEX}'.")


def _row_to_text(row: dict, table: str) -> str:
    """Serialise a data row to a human-readable passage for BM25 indexing."""
    parts = [f"[{table}]"]
    for key, value in row.items():
        if value is not None and str(value).strip():
            parts.append(f"{key}: {value}")
    return "  |  ".join(parts)


def _df_to_docs(df: pd.DataFrame, table: str, source: str) -> list[dict]:
    """Convert a DataFrame to a list of ES documents."""
    docs = []
    df = df.fillna("")
    row_dict_list = df.to_dict(orient="records")
    for i, row in enumerate(row_dict_list):
        text = _row_to_text(row, table)
        doc = {
            "_index": ES_INDEX,
            "_id":    f"{table}:{i}",
            "_source": {
                "text":       text,
                "table":      table,
                "source":     source,
                "region":     str(row.get("region", "")).strip() or "All",
                "tier":       str(row.get("tier",   "")).strip() or "All",
                "partner_id": str(row.get("partner_id", "")),
                "row_json":   row,
            },
        }
        docs.append(doc)
    return docs


def index_euler_data(
    *,
    partners_df:  pd.DataFrame | None = None,
    deals_df:     pd.DataFrame | None = None,
    certs_df:     pd.DataFrame | None = None,
    extra_tables: dict[str, pd.DataFrame] | None = None,
) -> dict[str, int]:
    """
    Index EULER data into Elasticsearch.

    Pass DataFrames directly, or leave all None to auto-fetch from euler_api.py
    (requires EULER_API_KEY to be set in .env).

    Returns a dict of {table_name: docs_indexed}.

    Usage:
        from utils.elastic_rag_engine import index_euler_data
        index_euler_data()                         # auto-fetch from EULER API
        index_euler_data(partners_df=my_df)        # supply your own DataFrame
    """
    try:
        from elasticsearch.helpers import bulk
    except ImportError as exc:
        raise RuntimeError(
            "elasticsearch-py is not installed. "
            "Run:  uv pip install 'elasticsearch>=8,<9'"
        ) from exc

    es = _get_client()
    _ensure_index(es)

    # ── Auto-fetch from EULER REST API if no DataFrames supplied ──────────────
    if partners_df is None and deals_df is None and certs_df is None:
        try:
            from utils.euler_api import fetch_partners, fetch_deals, fetch_certifications, EULER_CONFIGURED
            if not EULER_CONFIGURED:
                raise RuntimeError(
                    "EULER_API_KEY is not set. Either set it in .env or pass "
                    "DataFrames directly to index_euler_data()."
                )
            print("[ElasticRAG] Fetching live data from EULER API…")
            partners_df = fetch_partners()
            deals_df    = fetch_deals()
            certs_df    = fetch_certifications()
        except Exception as exc:
            raise RuntimeError(f"[ElasticRAG] Failed to fetch EULER data: {exc}") from exc

    table_map: dict[str, tuple[pd.DataFrame | None, str]] = {
        "ms_partners": (partners_df, "microsoft"),
        "ms_deals":    (deals_df,    "microsoft"),
        "ms_certs":    (certs_df,    "microsoft"),
    }
    if extra_tables:
        for name, df in extra_tables.items():
            table_map[name] = (df, name.split("_")[0])

    counts: dict[str, int] = {}
    all_docs: list[dict] = []

    for table, (df, source) in table_map.items():
        if df is None or df.empty:
            continue
        docs = _df_to_docs(df, table, source)
        all_docs.extend(docs)
        counts[table] = len(docs)

    if all_docs:
        success, errors = bulk(es, all_docs, raise_on_error=False)
        if errors:
            print(f"[ElasticRAG] Bulk index: {success} ok, {len(errors)} errors.")
            for err in errors[:5]:
                print(f"  {err}")
        else:
            total = sum(counts.values())
            print(f"[ElasticRAG] Indexed {total} docs across {list(counts.keys())}.")

    es.indices.refresh(index=ES_INDEX)
    return counts


# ── Retrieval ─────────────────────────────────────────────────────────────────

def retrieve(
    query: str,
    *,
    region: str = "All",
    tier: str   = "All",
    source: str = "All",
    top_k: int  = 6,
    # The following kwargs are accepted but ignored for compatibility with the
    # linear_rag_engine.retrieve() signature used in linear_query_engine.py
    datasets=None,
    candidate_tables=None,
    filter_frame=None,
) -> tuple[str, list[str], str, list[dict]]:
    """
    Search Elasticsearch for passages relevant to *query*.

    Returns the same 4-tuple as linear_rag_engine.retrieve():
        (context_str, table_names, trace_str, hits_data)

    *context_str*   — concatenated passage texts (up to 3 200 chars)
    *table_names*   — deduplicated list of ES 'table' field values in hit order
    *trace_str*     — human-readable retrieval trace for the debug panel
    *hits_data*     — list of dicts compatible with the existing chart/table UI
    """
    es = _get_client()

    # ── Build filter clauses ──────────────────────────────────────────────────
    filters: list[dict] = []
    if region and region != "All":
        filters.append({"term": {"region": region}})
    if tier and tier != "All":
        filters.append({"term": {"tier": tier}})
    if source and source != "All":
        filters.append({"term": {"source": source.lower()}})

    # ── BM25 multi_match over the full-text 'text' field ─────────────────────
    es_query: dict = {
        "query": {
            "bool": {
                "must": {
                    "multi_match": {
                        "query":  query,
                        "fields": ["text^2", "table"],
                        "type":   "best_fields",
                        "fuzziness": "AUTO",
                    }
                },
                "filter": filters,
            }
        },
        "size": top_k,
        "_source": True,
        "highlight": {
            "fields": {"text": {"fragment_size": 200, "number_of_fragments": 1}}
        },
    }

    try:
        resp = es.search(index=ES_INDEX, body=es_query)
    except Exception as exc:
        return (
            "",
            [],
            f"ElasticRAG: search failed — {exc}",
            [],
        )

    raw_hits = resp.get("hits", {}).get("hits", [])
    if not raw_hits:
        return "", [], "ElasticRAG: no results found.", []

    # ── Build output in the shape linear_rag_engine returns ──────────────────
    passage_texts: list[str]   = []
    table_names:   list[str]   = []
    hits_data:     list[dict]  = []
    trace_lines =  ["ElasticRAG retrieval:"]

    for hit in raw_hits:
        src   = hit["_source"]
        score = round(hit["_score"], 3)
        text  = src.get("text", "")
        table = src.get("table", "unknown")
        doc_id = hit["_id"]

        # Snippet: prefer ES highlight, fall back to first 350 chars of text
        highlights = hit.get("highlight", {}).get("text", [])
        snippet = highlights[0] if highlights else text[:350]

        passage_texts.append(text)
        if table not in table_names:
            table_names.append(table)

        hits_data.append({
            "passage_id": doc_id,
            "label":      doc_id,
            "table":      table,
            "score":      score,
            "reasons":    f"bm25 score={score}",
            "snippet":    snippet,
        })
        trace_lines.append(f"  {doc_id}  score={score}  table={table}")

    context = "\n\n".join(passage_texts)[:3200]
    trace   = "\n".join(trace_lines)

    return context, table_names, trace, hits_data


# ── CLI convenience ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"

    if cmd == "index":
        index_euler_data()

    elif cmd == "search":
        q = " ".join(sys.argv[2:]) or "active partners"
        ctx, tables, trace, hits = retrieve(q)
        print(trace)
        print(f"\nTop tables: {tables}")
        print(f"\nContext preview:\n{ctx[:800]}")

    elif cmd == "ping":
        try:
            es = _get_client()
            info = es.info()
            print(f"Connected to Elasticsearch {info['version']['number']} at {ES_URL}")
        except Exception as exc:
            print(f"ERROR: {exc}")

    else:
        print(
            "Usage:\n"
            "  python -m utils.elastic_rag_engine ping              # test connection\n"
            "  python -m utils.elastic_rag_engine index             # index EULER data\n"
            "  python -m utils.elastic_rag_engine search <question> # test retrieval\n"
        )
