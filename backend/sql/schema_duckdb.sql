INSTALL fts;
LOAD fts;

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    file_name TEXT,
    upload_time TEXT
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id INTEGER PRIMARY KEY,
    document_id INTEGER,
    page_number INTEGER,
    section TEXT,
    content TEXT,
    image_path TEXT
);

PRAGMA create_fts_index('document_chunks', 'id', 'content', overwrite=1);
