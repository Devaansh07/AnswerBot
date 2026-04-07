# AnswerBot — Technical Report

## 1. Project Overview

AnswerBot is a **Retrieval-Augmented Generation (RAG)** system that allows users to upload documents (PDF, DOCX, DOC, TXT) and ask natural-language questions against them. The system retrieves the most semantically relevant chunks from a local DuckDB database and passes them as grounded context to a GPT-4o language model, which then generates a cited, document-backed answer. The architecture is strictly non-vector-based — it uses BM25 full-text search and fuzzy matching for retrieval.

---

## 2. Technology Stack

| Layer | Technology |
|---|---|
| **Backend API** | Python · FastAPI · Uvicorn |
| **Database** | DuckDB (embedded, file-based) |
| **ORM** | SQLAlchemy + duckdb-engine |
| **PDF Parsing** | PyMuPDF (`fitz`) |
| **DOCX Parsing** | python-docx |
| **DOC Parsing** | macOS `textutil` / Windows COM / Linux `antiword` |
| **Text Matching** | DuckDB native BM25 FTS + RapidFuzz |
| **LLM** | OpenAI GPT-4o (configurable via `.env`) |
| **Frontend** | Vanilla HTML · CSS · JavaScript |
| **Environment** | python-dotenv |
| **File Uploads** | python-multipart |

---

## 3. Project Structure

```
newanswerbot/
├── backend/
│   ├── main.py                    # FastAPI application, all API routes
│   └── app/
│       ├── db.py                  # Database models, engine, FTS index management
│       ├── ingestion/
│       │   └── ingestion.py       # Document parsing and chunk storage
│       ├── retrieval/
│       │   └── retrieval.py       # BM25 + fuzzy retrieval pipeline
│       ├── llm/
│       │   └── llm_client.py      # OpenAI GPT-4o answer generation
│       └── static/
│           └── images/            # Extracted PDF images served statically
├── frontend/
│   ├── index.html                 # Main UI
│   ├── script.js                  # Chat logic, session management, API calls
│   └── style.css                  # Full UI styling
├── requirements.txt
├── .env                           # API keys and model config (not committed)
└── answerbot.duckdb               # Embedded database file
```

---

## 4. Python Packages

### `fastapi`
The core web framework. Provides the HTTP routing layer, request/response models, dependency injection (`Depends`), and middleware support. Used for all API endpoints: `/upload`, `/query`, `/documents`, `/api/download`.

### `uvicorn`
ASGI server that runs the FastAPI application. Launched via `python -m backend.main`.

### `sqlalchemy`
ORM used to define `Document` and `DocumentChunk` models as Python classes and map them to DuckDB tables. Also used to execute raw SQL queries via `text()` and `session.execute()`.

### `duckdb` + `duckdb-engine`
- `duckdb` is the embedded analytical database engine. It stores all document and chunk data in a single local file (`answerbot.duckdb`).
- `duckdb-engine` is the SQLAlchemy dialect adapter that bridges SQLAlchemy's ORM and query builder with DuckDB.
- DuckDB's built-in **FTS extension** (`PRAGMA create_fts_index`) powers the native BM25 full-text search.

### `PyMuPDF` (`fitz`)
Used exclusively for PDF processing. Superior to pypdf for image extraction because it accesses low-level **XREF objects** in the PDF's cross-reference table. Each image on a page is extracted as raw bytes with its native format (`.png`, `.jpeg`, etc.) and saved to `backend/app/static/images/`.

### `python-docx`
Extracts text from `.docx` files by iterating over all paragraphs in the document object. Returns content as a single-page chunk.

### `rapidfuzz`
Provides `fuzz.token_set_ratio()` — a fuzzy string matching algorithm that compares query tokens against chunk content regardless of token order. Used as a fallback when BM25 returns no results. Results below a 0.20 score threshold are discarded.

### `openai`
The official OpenAI Python SDK. Used to call `client.chat.completions.create()` with a structured message array containing the system prompt, previous chat history (sliding window of 6 messages), and the current user query.

### `python-dotenv`
Loads `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `OPENAI_MODEL` from the `.env` file at startup via `load_dotenv()`.

### `python-multipart`
Required by FastAPI to handle `multipart/form-data` file uploads and `Form(...)` fields in the `/upload` and `/query` endpoints.

---

## 5. Database Design

### Engine Configuration

```python
engine = create_engine(
    f"duckdb:///{db_path}",
    connect_args={"preload_extensions": ["fts"]}
)
```

DuckDB is initialized with the FTS extension preloaded. The database file is stored at the project root as `answerbot.duckdb`. DuckDB enforces **single-writer locking** — only one process can hold a write connection at a time.

---

### Table: `documents`

Stores one record per uploaded file.

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER (PK) | Manually assigned sequential ID (no autoincrement) |
| `file_name` | TEXT | Original filename as uploaded |
| `upload_time` | TEXT | ISO 8601 UTC timestamp of upload |

**ORM Model:**
```python
class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True, autoincrement=False)
    file_name = Column(Text, nullable=False)
    upload_time = Column(Text, nullable=False, default=_utcnow_iso)
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")
```

The `cascade="all, delete-orphan"` ensures all child chunks are automatically deleted when a document is removed.

---

### Table: `document_chunks`

Stores all text segments and associated image paths for every document.

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER (PK) | Manually assigned sequential ID |
| `document_id` | INTEGER (FK) | References `documents.id`, cascades on DELETE |
| `page_number` | INTEGER | Page the chunk came from (1-indexed) |
| `section` | TEXT (nullable) | Reserved for future section-level metadata |
| `content` | TEXT | The text content, prefixed with `[File: X - Page N]` header |
| `image_path` | TEXT (nullable) | Comma-separated relative paths to extracted images for this page |

**ORM Model:**
```python
class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id = Column(Integer, primary_key=True, autoincrement=False)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"))
    page_number = Column(Integer)
    section = Column(Text, nullable=True)
    content = Column(Text, nullable=False)
    image_path = Column(Text, nullable=True)
    document = relationship("Document", back_populates="chunks")
```

---

### Table Relations

```
documents (1) ──────< document_chunks (many)
    id ──────────────── document_id (FK, CASCADE DELETE)
```

One document maps to many chunks. Deleting a document cascades and deletes all its associated chunks automatically.

---

### FTS Index

```sql
PRAGMA create_fts_index('document_chunks', 'id', 'content');
```

Builds a native BM25 inverted index over the `content` column of `document_chunks`. This index is re-created after every upload or deletion via `refresh_fts_index()`. The `match_bm25(id, query)` function is then used in retrieval queries to score each chunk by relevance.

---

## 6. Ingestion Pipeline

**File:** `backend/app/ingestion/ingestion.py`

### Flow

```
Upload → Detect extension → Extract text + images → Chunk text → Store chunks
```

### PDF Extraction (PyMuPDF)

1. Open the PDF as a `fitz.Document` stream.
2. For each page, call `page.get_text()` to extract full text.
3. Call `page.get_images(full=True)` to get a list of all embedded image references.
4. For each image, read its XREF number → call `doc.extract_image(xref)` → get raw bytes and extension.
5. Save the image to `backend/app/static/images/doc_{id}_pg_{N}_img_{idx}.{ext}`.
6. Collect all image paths for that page as a comma-separated string.

### Text Chunking

```python
def chunk_text(text: str, chunk_size=400, overlap=50):
```

Splits text into word-level windows of ~400 words with a 50-word overlap between consecutive chunks. The overlap preserves cross-boundary semantic context.

### Chunk Storage

Each chunk is stored with a **metadata header** prepended to the content:

```
[File: Water-Filling-Algorithm.pdf - Page 3]
<actual chunk text>
```

This ensures DuckDB's BM25 index can match document-specific queries like "summarize the water filling pdf" against page-level metadata, not just content words.

- The **first chunk** per page gets the `image_path` attached.
- Subsequent chunks on the same page have `image_path = None` to prevent duplication.
- If a page has images but no extractable text, a placeholder chunk `[File: X - Page N | Document Image Data]` is inserted to ensure the image is still indexed and retrievable.

---

## 7. Retrieval Pipeline

**File:** `backend/app/retrieval/retrieval.py`

### `retrieve_top_k(db, query, k=20)`

A 4-stage cascading retrieval strategy:

#### Stage 1 — Lead Chunk Injection (Global Queries)

```python
def is_global_query(query):
```

Detects summary-style queries (e.g. "what is this document about", "summarize", "overview"). If matched, it fetches page-1 chunks from all documents whose filename matches tokens in the query. This bootstraps the context for high-level questions.

#### Stage 2 — Strict BM25

```sql
SELECT dc.content, d.file_name, dc.page_number, dc.image_path,
       fts_main_document_chunks.match_bm25(dc.id, :query) AS score
FROM document_chunks dc
JOIN documents d ON dc.document_id = d.id
WHERE fts_main_document_chunks.match_bm25(dc.id, :query) IS NOT NULL
ORDER BY score DESC LIMIT :limit
```

Performs exact BM25 scoring against the full query string. Results are ordered by descending relevance.

#### Stage 3 — Relaxed BM25 (Term-by-Term)

If strict BM25 returns nothing, the query is tokenized into individual terms (e.g. `["water", "filling", "algorithm"]`) and each term is searched independently. Results are merged and re-sorted by score.

#### Stage 4 — RapidFuzz Fallback

```python
fuzz.token_set_ratio(query, row["content"]) / 100.0
```

If BM25 returns insufficient results, all chunks are fetched and scored using fuzzy token-set ratio. Chunks scoring below 0.20 are discarded. This ensures the system always returns something relevant even for misspelled or paraphrased queries.

### Deduplication & Per-Document Balancing

A `seen_keys` set prevents duplicate `(file_name, page_number, content)` triples. A `doc_match_counts` dictionary caps any single document at 5 chunks when multiple documents are present — this ensures fair multi-document coverage.

---

## 8. LLM Answer Generation

**File:** `backend/app/llm/llm_client.py`

### System Prompt

The system prompt explicitly instructs the model:
- To answer **only from the provided chunks** (grounded generation).
- Never to say it cannot display images — the UI handles image rendering.
- To cite sources by document name and page number.
- To return "Answer not found in provided documents" when context is insufficient.

### Chat History

A sliding window of the **last 6 messages** from the session's chat history is injected into the message array before the current query. This gives the model multi-turn conversational awareness without exceeding token limits.

```python
messages = [{"role": "system", "content": system_prompt}]
for msg in chat_history[-6:]:
    role = "assistant" if msg.get("role") == "bot" else "user"
    messages.append({"role": role, "content": msg.get("content", "")})
messages.append({"role": "user", "content": f"USER QUERY:\n{query}\n\nANSWER:"})
```

---

## 9. API Routes

**File:** `backend/main.py`

| Method | Route | Description |
|---|---|---|
| `GET` | `/` | Health check |
| `POST` | `/upload` | Upload and ingest a document |
| `GET` | `/documents` | List all ingested documents |
| `DELETE` | `/documents/{id}` | Delete a document and its chunks |
| `GET` | `/api/download?path=` | Force-download an image as an OS attachment |
| `POST` | `/query` | Submit a query; returns answer, sources, and images |
| `GET` | `/static/images/*` | Serve extracted images via StaticFiles mount |

### `/query` Logic

1. Retrieve top-k chunks from DuckDB.
2. Detect image keywords (`image`, `chart`, `diagram`, `graph`, `photo`, etc.).
3. Detect page targeting via regex (`"page 1"`, `"first page"`, `"3rd page"`, etc.).
4. If images are requested: filter `image_path` values to only those matching the requested page(s), append a `[SYSTEM NOTE]` to each matched chunk's content.
5. If no image request: wipe all `image_path` values before passing to LLM.
6. Call `generate_answer()` with chunks and chat history.
7. Return JSON: `{ answer, sources, retrieved_results, images }`.

---

## 10. Frontend Architecture

**Files:** `frontend/index.html`, `frontend/script.js`, `frontend/style.css`

### Session Management

Chat sessions are persisted in `localStorage` under the key `answerbot_chat_sessions` as a JSON object:

```json
{
  "chat_abc123": {
    "title": "What is the water filling algorithm?",
    "messages": [...],
    "updatedAt": 1712345678901
  }
}
```

Each chat has an isolated message array. The sidebar renders all sessions sorted by `updatedAt` descending. Switching sessions loads the corresponding message array. Each session can be individually deleted.

### Message Rendering

- **User messages**: Rendered right-aligned with timestamp.
- **Bot messages**: Rendered left-aligned with timestamp, source pills, and optionally an image gallery.
- **Image gallery**: A flex-wrap container of `.chat-img-wrapper` elements, each holding a thumbnail and an overlaid download button (visible on hover).
- **Download**: Clicking the download icon navigates to `/api/download?path=...`, which returns the file as `application/octet-stream` — triggering a native OS file download.

### API Communication

Query submissions use `FormData` with `query` and `chat_history` (serialized JSON string of the last N messages). The `API_BASE` constant points to `http://127.0.0.1:8000`.

---

## 11. Image Extraction & Conditional Rendering

Images are extracted at **ingestion time** using PyMuPDF's XREF scanner and stored on disk. At **query time**:

- If the query contains an image keyword → images are returned in the API response.
- If the query specifies a page number → only images from that page are returned (others are filtered out server-side).
- The LLM is told via a `[SYSTEM NOTE]` in the chunk content that images are visible in the UI.
- The frontend renders each image as a hoverable card with a one-click download button backed by the `/api/download` endpoint.

---

## 12. Environment Variables (`.env`)

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | API key for OpenAI (required) |
| `OPENAI_BASE_URL` | Override endpoint (default: `https://api.openai.com/v1`) |
| `OPENAI_MODEL` | Model to use (default: `gpt-4o`) |

---

## 13. Cross-Platform Compatibility

The `.doc` extraction function uses `sys.platform` to select the appropriate tool:

| Platform | Tool |
|---|---|
| macOS (`darwin`) | `textutil -convert txt -stdout` |
| Windows (`win32`) | `win32com.client` Word COM → raw binary scrape fallback |
| Linux | `antiword` |

All other components (FastAPI, DuckDB, PyMuPDF, OpenAI SDK) are natively cross-platform.
