import re
from typing import Any, Dict, List

from rapidfuzz import fuzz
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.db import Document


def _normalize(text_value: str) -> str:
    return re.sub(r"\s+", " ", (text_value or "").strip().lower())


def _tokenize(query: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 2]


def is_global_query(query: str) -> bool:
    """Detects if the user is asking for a general overview or summary."""
    keywords = [
        "about",
        "summarize",
        "summary",
        "overview",
        "what is",
        "documents",
        "content",
        "library",
        "explain",
    ]
    q = query.lower()
    if len(q.split()) <= 12 and any(k in q for k in keywords):
        return True
    return False


def get_lead_chunks(db: Session, query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Fetches introductory chunks from matching documents or all documents."""
    q = _normalize(query)
    query_tokens = _tokenize(query)

    lead_sql = """
        SELECT
            dc.content,
            d.file_name,
            dc.page_number,
            dc.image_path,
            1.0 AS score,
            'lead_chunk' AS method
        FROM document_chunks dc
        JOIN documents d ON dc.document_id = d.id
        WHERE dc.page_number <= 1
    """

    params: Dict[str, Any] = {"limit": limit}
    matched_doc_ids: List[int] = []

    all_docs = db.query(Document.id, Document.file_name).all()
    for doc_id, file_name in all_docs:
        name_part = _normalize(file_name.rsplit(".", 1)[0].replace("-", " ").replace("_", " "))
        if (q and (name_part in q or q in name_part)) or any(token in name_part for token in query_tokens):
            matched_doc_ids.append(doc_id)

    if matched_doc_ids:
        placeholders = ", ".join([f":doc_id_{i}" for i in range(len(matched_doc_ids))])
        lead_sql += f" AND d.id IN ({placeholders})"
        params.update({f"doc_id_{i}": doc_id for i, doc_id in enumerate(matched_doc_ids)})

    lead_sql += " ORDER BY d.id, dc.id ASC LIMIT :limit"
    rows = db.execute(text(lead_sql), params).mappings().all()
    return [dict(row) for row in rows]


def _run_bm25_query(db: Session, query: str, limit: int, method: str) -> List[Dict[str, Any]]:
    bm25_sql = """
        SELECT
            dc.content,
            d.file_name,
            dc.page_number,
            dc.image_path,
            fts_main_document_chunks.match_bm25(dc.id, :query) AS score,
            :method AS method
        FROM document_chunks dc
        JOIN documents d ON dc.document_id = d.id
        WHERE fts_main_document_chunks.match_bm25(dc.id, :query) IS NOT NULL
        ORDER BY score DESC
        LIMIT :limit
    """
    try:
        rows = db.execute(
            text(bm25_sql),
            {"query": query, "limit": limit, "method": method},
        ).mappings().all()
        return [dict(row) for row in rows]
    except Exception as exc:
        print(f"DEBUG: BM25 query failed ({method}): {exc}")
        return []


def _run_fuzzy_fallback(db: Session, query: str, limit: int) -> List[Dict[str, Any]]:
    rows = db.execute(
        text(
            """
            SELECT
                dc.content,
                d.file_name,
                dc.page_number,
                dc.image_path
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            """
        )
    ).mappings().all()

    scored = []
    for row in rows:
        score = fuzz.token_set_ratio(query, row["content"]) / 100.0
        if score < 0.20:
            continue
        scored.append(
            {
                "content": row["content"],
                "file_name": row["file_name"],
                "page_number": row["page_number"],
                "image_path": row["image_path"],
                "score": float(score),
                "method": "fuzzy_rapidfuzz",
            }
        )
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:limit]


def retrieve_top_k(db: Session, query: str, k: int = 20) -> List[Dict[str, Any]]:
    """
    DuckDB retrieval strategy:
    1. Lead chunks for global summary queries.
    2. Strict BM25 full-query search.
    3. Relaxed BM25 term-by-term search when strict returns nothing.
    4. Python fuzzy fallback (rapidfuzz) if needed.
    """
    all_results: List[Dict[str, Any]] = []
    seen_keys = set()
    doc_match_counts: Dict[str, int] = {}

    if is_global_query(query):
        lead_chunks = get_lead_chunks(db, query, limit=6)
        for chunk in lead_chunks:
            row_key = (chunk["file_name"], chunk["page_number"], chunk["content"])
            if row_key in seen_keys:
                continue
            all_results.append(chunk)
            seen_keys.add(row_key)
            doc_match_counts[chunk["file_name"]] = doc_match_counts.get(chunk["file_name"], 0) + 1

    strict_results = _run_bm25_query(db, query, limit=k, method="bm25_strict")

    relaxed_results: List[Dict[str, Any]] = []
    if not strict_results:
        terms = _tokenize(query)
        for term in terms[:8]:
            relaxed_results.extend(_run_bm25_query(db, term, limit=8, method="bm25_relaxed"))
        relaxed_results.sort(key=lambda item: float(item["score"]), reverse=True)

    fuzzy_results: List[Dict[str, Any]] = []
    if len(strict_results) + len(relaxed_results) < k:
        fuzzy_results = _run_fuzzy_fallback(
            db,
            query,
            limit=max(k - len(strict_results) - len(relaxed_results), 1),
        )

    stage_ordered_rows = list(strict_results) + list(relaxed_results) + list(fuzzy_results)

    for row in stage_ordered_rows:
        row_key = (row["file_name"], row["page_number"], row["content"])
        if row_key in seen_keys:
            continue

        doc_name = row["file_name"]
        current_doc_count = doc_match_counts.get(doc_name, 0)
        if current_doc_count >= 5 and len(doc_match_counts) > 1:
            continue

        all_results.append(
            {
                "content": row["content"],
                "file_name": row["file_name"],
                "page_number": row["page_number"],
                "image_path": row["image_path"],
                "score": float(row["score"]),
                "method": row["method"],
            }
        )
        seen_keys.add(row_key)
        doc_match_counts[doc_name] = current_doc_count + 1

        if len(all_results) >= k:
            break

    return all_results
