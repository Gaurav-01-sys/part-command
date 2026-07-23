"""
utils/bm25_rag_engine.py
-------------------------
Pure-Python BM25 retriever for the Partner Command Center.

Drop-in replacement for elastic_rag_engine / linear_rag_engine.
No server. No Docker. No external infra. Works on Render free tier.

HOW IT WORKS
------------
1.  index_euler_data() converts EULER DataFrames into text passages and
    builds an in-memory BM25 index using the bm25s library.
2.  retrieve() runs a BM25 search, applies region / tier / source filters
    post-hoc, and returns the same 4-tuple that linear_rag_engine returns.
3.  The index is cached in module globals — it survives the lifetime of the
    Dash worker process and is rebuilt only when index_euler_data() is called.

SETUP (already done if you ran `uv pip install bm25s PyStemmer`)
-----
    uv pip install bm25s PyStemmer

No .env changes needed.

USAGE
-----
    from utils.bm25_rag_engine import index_euler_data, retrieve

    # Index once at app start (or whenever data refreshes)
    index_euler_data(partners_df=df1, deals_df=df2)

    # Retrieve at query time (same interface as linear_rag_engine.retrieve)
    context, tables, trace, hits = retrieve("active referrals", region="EMEA")

CLI
---
    python -m utils.bm25_rag_engine index    # index from EULER API
    python -m utils.bm25_rag_engine search "active partners in EMEA"
    python -m utils.bm25_rag_engine status   # show index size
"""

from __future__ import annotations

import os
import sys
from typing import Any

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# ── Module-level index state ──────────────────────────────────────────────────

_corpus:    list[str]  = []   # passage text, one per document
_metadata:  list[dict] = []   # {table, region, tier, source, row_preview}
_retriever: Any        = None  # bm25s.BM25 instance (lazy-imported)
_stemmer:   Any        = None  # Stemmer.Stemmer (optional, for better recall)

_INDEX_BUILT = False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_stemmer():
    global _stemmer
    if _stemmer is not None:
        return _stemmer
    try:
        import Stemmer
        _stemmer = Stemmer.Stemmer("english")
    except ImportError:
        _stemmer = None   # bm25s works without stemming too
    return _stemmer


def _row_to_text(row: dict, table: str) -> str:
    """Serialise a data row into a BM25-indexable text passage."""
    parts = [f"[{table}]"]
    for key, value in row.items():
        if value is not None and str(value).strip() not in ("", "nan", "None"):
            parts.append(f"{key}: {value}")
    return "  |  ".join(parts)


def _df_to_passages(
    df: pd.DataFrame,
    table: str,
    source: str,
) -> tuple[list[str], list[dict]]:
    """Return (texts, metadatas) for a DataFrame."""
    texts: list[str]   = []
    metas: list[dict]  = []

    df = df.fillna("")
    for _, row in df.iterrows():
        row_dict = row.to_dict()
        text = _row_to_text(row_dict, table)
        meta = {
            "table":      table,
            "source":     source,
            "region":     str(row_dict.get("region", "")).strip() or "All",
            "tier":       str(row_dict.get("tier",   "")).strip() or "All",
            "partner_id": str(row_dict.get("partner_id", "")),
            "snippet":    text[:350],
            "row":        row_dict,
        }
        texts.append(text)
        metas.append(meta)
    return texts, metas


# ── Public: index ─────────────────────────────────────────────────────────────

def index_euler_data(
    *,
    partners_df:  pd.DataFrame | None = None,
    deals_df:     pd.DataFrame | None = None,
    certs_df:     pd.DataFrame | None = None,
    extra_tables: dict[str, pd.DataFrame] | None = None,
) -> dict[str, int]:
    """
    Build the in-memory BM25 index from EULER DataFrames.

    Pass DataFrames directly, or leave all None to auto-fetch from euler_api.py
    (requires EULER_API_KEY in .env).

    Returns {table_name: doc_count}.
    """
    global _corpus, _metadata, _retriever, _INDEX_BUILT

    try:
        import bm25s
    except ImportError as exc:
        raise RuntimeError(
            "bm25s is not installed. Run:  uv pip install bm25s PyStemmer"
        ) from exc

    # ── Auto-fetch if no DataFrames supplied ──────────────────────────────────
    if partners_df is None and deals_df is None and certs_df is None:
        try:
            from utils.euler_api import (
                fetch_certifications,
                fetch_deals,
                fetch_partners,
                EULER_CONFIGURED,
            )
            if not EULER_CONFIGURED:
                raise RuntimeError(
                    "EULER_API_KEY is not set. Either set it in .env or pass "
                    "DataFrames directly to index_euler_data()."
                )
            print("[BM25RAG] Fetching live data from EULER API…")
            partners_df = fetch_partners()
            deals_df    = fetch_deals()
            certs_df    = fetch_certifications()
        except Exception as exc:
            raise RuntimeError(f"[BM25RAG] Failed to fetch EULER data: {exc}") from exc

    table_map: dict[str, tuple[pd.DataFrame | None, str]] = {
        "ms_partners": (partners_df, "microsoft"),
        "ms_deals":    (deals_df,    "microsoft"),
        "ms_certs":    (certs_df,    "microsoft"),
    }
    if extra_tables:
        for name, df in extra_tables.items():
            table_map[name] = (df, name.split("_")[0])

    all_texts:  list[str]  = []
    all_metas:  list[dict] = []
    counts:     dict[str, int] = {}

    for table, (df, source) in table_map.items():
        if df is None or df.empty:
            continue
        texts, metas = _df_to_passages(df, table, source)
        all_texts.extend(texts)
        all_metas.extend(metas)
        counts[table] = len(texts)

    if not all_texts:
        print("[BM25RAG] Warning: no documents to index.")
        return counts

    stemmer = _get_stemmer()
    tokenized = bm25s.tokenize(
        all_texts,
        stopwords="en",
        stemmer=stemmer,
        show_progress=False,
    )

    retriever = bm25s.BM25()
    retriever.index(tokenized)

    _corpus    = all_texts
    _metadata  = all_metas
    _retriever = retriever
    _INDEX_BUILT = True

    total = sum(counts.values())
    print(f"[BM25RAG] Indexed {total} passages: {counts}")
    return counts


# ── Public: retrieve ──────────────────────────────────────────────────────────

def retrieve(
    query: str,
    *,
    region: str = "All",
    tier:   str = "All",
    source: str = "All",
    top_k:  int = 6,
    # Ignored kwargs for compatibility with linear_rag_engine.retrieve()
    datasets=None,
    candidate_tables=None,
    filter_frame=None,
) -> tuple[str, list[str], str, list[dict]]:
    """
    BM25 search over the in-memory EULER index.

    Returns the same 4-tuple as linear_rag_engine.retrieve():
        (context_str, table_names, trace_str, hits_data)
    """
    global _retriever, _corpus, _metadata, _INDEX_BUILT

    if not _INDEX_BUILT or _retriever is None:
        return (
            "",
            [],
            "BM25RAG: index not built. Call index_euler_data() first.",
            [],
        )

    if not query.strip():
        return "", [], "BM25RAG: empty query.", []

    try:
        import bm25s
    except ImportError:
        return "", [], "BM25RAG: bm25s not installed.", []

    stemmer = _get_stemmer()

    # ── BM25 search: fetch more than top_k so we have room to post-filter ─────
    fetch_k = min(top_k * 8, len(_corpus))
    query_tokens = bm25s.tokenize(
        [query],
        stopwords="en",
        stemmer=stemmer,
        show_progress=False,
    )

    try:
        raw_results, raw_scores = _retriever.retrieve(
            query_tokens,
            corpus=_corpus,
            k=fetch_k,
        )
    except Exception as exc:
        return "", [], f"BM25RAG: search error — {exc}", []

    # raw_results / raw_scores shape: (1, fetch_k)
    result_texts:  list[str]   = raw_results[0].tolist()
    result_scores: list[float] = raw_scores[0].tolist()

    # Map text back to metadata (texts are unique per row by design)
    text_to_meta: dict[str, dict] = {t: m for t, m in zip(_corpus, _metadata)}

    # ── Apply region / tier / source filters ───────────────────────────────────
    filtered: list[tuple[str, float, dict]] = []
    for text, score in zip(result_texts, result_scores):
        meta = text_to_meta.get(text, {})
        if region and region != "All" and meta.get("region", "All") not in ("All", region):
            continue
        if tier and tier != "All" and meta.get("tier", "All") not in ("All", tier):
            continue
        if source and source != "All" and meta.get("source", "").lower() != source.lower():
            continue
        filtered.append((text, score, meta))
        if len(filtered) >= top_k:
            break

    # Fallback: if filters remove everything, return unfiltered top_k
    if not filtered:
        for text, score in zip(result_texts[:top_k], result_scores[:top_k]):
            meta = text_to_meta.get(text, {})
            filtered.append((text, score, meta))

    # ── Build output ──────────────────────────────────────────────────────────
    passage_texts: list[str]  = []
    table_names:   list[str]  = []
    hits_data:     list[dict] = []
    trace_lines = ["BM25RAG retrieval:"]

    for i, (text, score, meta) in enumerate(filtered):
        table   = meta.get("table", "unknown")
        doc_id  = f"{table}:{meta.get('partner_id', i)}"
        snippet = meta.get("snippet", text[:350])

        passage_texts.append(text)
        if table not in table_names:
            table_names.append(table)

        hits_data.append({
            "passage_id": doc_id,
            "label":      doc_id,
            "table":      table,
            "score":      round(float(score), 3),
            "reasons":    f"bm25 score={score:.3f}",
            "snippet":    snippet,
        })
        trace_lines.append(
            f"  {doc_id}  score={score:.3f}  table={table}"
        )

    context = "\n\n".join(passage_texts)[:3200]
    trace   = "\n".join(trace_lines)

    return context, table_names, trace, hits_data


# ── Status ────────────────────────────────────────────────────────────────────

def index_status() -> dict:
    """Return current index stats."""
    return {
        "built":    _INDEX_BUILT,
        "doc_count": len(_corpus),
        "tables":   list({m.get("table") for m in _metadata}),
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"

    if cmd == "index":
        index_euler_data()

    elif cmd == "search":
        q = " ".join(sys.argv[2:]) or "active partners"
        if not _INDEX_BUILT:
            print("[BM25RAG] Index not built — attempting auto-index from the live EULER API...")
            try:
                index_euler_data()
            except Exception as e:
                print(f"  Error: {e}")
                sys.exit(1)
        ctx, tables, trace, hits = retrieve(q)
        print(trace)
        print(f"\nTop tables: {tables}")
        print(f"\nContext preview (first 600 chars):\n{ctx[:600]}")

    elif cmd == "status":
        s = index_status()
        print(f"Index built: {s['built']}")
        print(f"Documents:   {s['doc_count']}")
        print(f"Tables:      {s['tables']}")

    else:
        print(
            "Usage:\n"
            "  python -m utils.bm25_rag_engine index              # index EULER API data\n"
            "  python -m utils.bm25_rag_engine search <question>  # test retrieval\n"
            "  python -m utils.bm25_rag_engine status             # show index stats\n"
        )
