-- =====================================================
-- AnswerBot — DuckDB Query Reference
-- Engine: DuckDB (embedded, file-based)
-- FTS:    Native BM25 via DuckDB fts extension
-- Note:   All queries use DuckDB syntax exclusively.
--         Positional parameters use $1, $2, etc.
-- =====================================================


-- ─────────────────────────────────────────────────────
-- DOCUMENTS
-- ─────────────────────────────────────────────────────

-- List all ingested documents (newest first)
SELECT id, file_name, upload_time
FROM documents
ORDER BY upload_time DESC;

-- Get a specific document by ID
SELECT id, file_name, upload_time
FROM documents
WHERE id = $1;


-- ─────────────────────────────────────────────────────
-- DOCUMENT CHUNKS
-- ─────────────────────────────────────────────────────

-- List all chunks for a given document
SELECT id, document_id, page_number, content, image_path
FROM document_chunks
WHERE document_id = $1
ORDER BY page_number, id;

-- Get chunks for a specific page of a document
SELECT id, page_number, content, image_path
FROM document_chunks
WHERE document_id = $1
  AND page_number = $2
ORDER BY id;


-- ─────────────────────────────────────────────────────
-- RETRIEVAL — BM25 Full-Text Search (DuckDB FTS)
-- ─────────────────────────────────────────────────────

-- Stage 1: Strict BM25 on full query string
SELECT
    dc.id,
    dc.document_id,
    d.file_name,
    dc.page_number,
    dc.image_path,
    dc.content,
    fts_main_document_chunks.match_bm25(dc.id, $1) AS score
FROM document_chunks dc
JOIN documents d ON d.id = dc.document_id
WHERE fts_main_document_chunks.match_bm25(dc.id, $1) IS NOT NULL
ORDER BY score DESC
LIMIT 20;

-- Stage 2: Relaxed BM25 — run once per query token
SELECT
    dc.id,
    dc.document_id,
    d.file_name,
    dc.page_number,
    dc.image_path,
    dc.content,
    fts_main_document_chunks.match_bm25(dc.id, $1) AS score
FROM document_chunks dc
JOIN documents d ON d.id = dc.document_id
WHERE fts_main_document_chunks.match_bm25(dc.id, $1) IS NOT NULL
ORDER BY score DESC
LIMIT 10;

-- Stage 3: Lead chunks for global / summary queries (page 1 of matching docs)
SELECT
    dc.content,
    d.file_name,
    dc.page_number,
    dc.image_path
FROM document_chunks dc
JOIN documents d ON dc.document_id = d.id
WHERE dc.page_number <= 1
ORDER BY d.id, dc.id ASC
LIMIT 6;

-- Stage 4: Full scan for RapidFuzz fallback (Python-side scoring)
SELECT
    dc.content,
    d.file_name,
    dc.page_number,
    dc.image_path
FROM document_chunks dc
JOIN documents d ON dc.document_id = d.id;


-- ─────────────────────────────────────────────────────
-- DELETE
-- ─────────────────────────────────────────────────────

-- Delete all chunks for a document (cascade handled by ORM, but manual form):
DELETE FROM document_chunks WHERE document_id = $1;

-- Delete the document record itself:
DELETE FROM documents WHERE id = $1;


-- ─────────────────────────────────────────────────────
-- FTS INDEX MANAGEMENT (DuckDB-specific PRAGMAs)
-- ─────────────────────────────────────────────────────

-- Initial FTS index creation:
PRAGMA create_fts_index('document_chunks', 'id', 'content');

-- Rebuild / overwrite FTS index after inserts, updates, or deletes:
PRAGMA create_fts_index('document_chunks', 'id', 'content', overwrite=1);

-- Drop FTS index (if needed before rebuild):
PRAGMA drop_fts_index('document_chunks');
