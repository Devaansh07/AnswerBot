-- List documents
SELECT id, file_name, upload_time
FROM documents
ORDER BY upload_time DESC;

-- List chunks for a document
SELECT id, document_id, page_number, content, image_path
FROM document_chunks
WHERE document_id = ?
ORDER BY page_number, id;

-- Stage 1: strict BM25 on full query string
SELECT
    dc.id,
    dc.document_id,
    d.file_name,
    dc.page_number,
    dc.content,
    fts_main_document_chunks.match_bm25(dc.id, ?) AS score
FROM document_chunks dc
JOIN documents d ON d.id = dc.document_id
WHERE fts_main_document_chunks.match_bm25(dc.id, ?) IS NOT NULL
ORDER BY score DESC
LIMIT 20;

-- Stage 2: relaxed BM25 on one token (run per token)
SELECT
    dc.id,
    dc.document_id,
    d.file_name,
    dc.page_number,
    dc.content,
    fts_main_document_chunks.match_bm25(dc.id, ?) AS score
FROM document_chunks dc
JOIN documents d ON d.id = dc.document_id
WHERE fts_main_document_chunks.match_bm25(dc.id, ?) IS NOT NULL
ORDER BY score DESC
LIMIT 10;

-- Lead chunks (global/summary queries)
SELECT
    dc.content,
    d.file_name,
    dc.page_number
FROM document_chunks dc
JOIN documents d ON dc.document_id = d.id
WHERE dc.page_number <= 1
ORDER BY d.id, dc.id
LIMIT 6;

-- Delete a document and its chunks
DELETE FROM document_chunks WHERE document_id = ?;
DELETE FROM documents WHERE id = ?;

-- Rebuild FTS after inserts/updates/deletes
PRAGMA create_fts_index('document_chunks', 'id', 'content', overwrite=1);
