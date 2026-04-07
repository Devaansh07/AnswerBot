# AnswerBot

> A local, production-ready **Retrieval-Augmented Generation (RAG)** system — upload documents, ask questions, get grounded, cited answers powered by GPT-4o and DuckDB.

---

## Quick Setup

### Prerequisites
- Python 3.10+
- A valid OpenAI API key

### 1. Clone the Repository
```bash
git clone https://github.com/Devaansh07/AnswerBot.git
cd AnswerBot
```

### 2. Create and Activate a Virtual Environment
```bash
# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate

# Windows
python -m venv .venv
.venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Create a `.env` file in the project root:
```env
OPENAI_API_KEY=sk-your-key-here
OPENAI_BASE_URL=https://api.openai.com/v1   # optional, change for proxies
OPENAI_MODEL=gpt-4o                          # optional, defaults to gpt-4o
```

### 5. Start the Backend Server
```bash
python -m backend.main
```
The API will be available at `http://127.0.0.1:8000`.

### 6. Open the Frontend
Open `frontend/index.html` directly in your browser. No additional build step required.

### 7. Using the App
1. In the **Data Ingestion** panel, click **Choose Files** and select a PDF, DOCX, DOC, or TXT file.
2. Click **Upload**. Wait for the success confirmation and the document to appear in the Knowledge Base library.
3. Type your question in the chat input and press **Send**.
4. To extract images from a specific page, include keywords like `"show me the images from page 3"` or `"extract the diagrams on the first page"`.

> **Note for Windows users with `.doc` files:** Install `pywin32` for best results (`pip install pywin32`). The system falls back to raw text extraction if unavailable.

---

## Technical Report

### 1. Project Overview

AnswerBot is a **Retrieval-Augmented Generation (RAG)** system that allows users to upload documents (PDF, DOCX, DOC, TXT) and ask natural-language questions against them. The system retrieves the most semantically relevant chunks from a local DuckDB database and passes them as grounded context to a GPT-4o language model, which then generates a cited, document-backed answer. The architecture is strictly non-vector-based — it uses BM25 full-text search and fuzzy matching for retrieval.

---

### 2. Technology Stack

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

### 3. Project Structure

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

### 4. Python Packages

#### `fastapi`
The core web framework. Provides HTTP routing, request/response models, dependency injection (`Depends`), and middleware support. Used for all API endpoints: `/upload`, `/query`, `/documents`, `/api/download`.

#### `uvicorn`
ASGI server that runs the FastAPI application. Launched via `python -m backend.main`.

#### `sqlalchemy`
ORM used to define `Document` and `DocumentChunk` models as Python classes and map them to DuckDB tables. Also used to execute raw SQL queries via `text()` and `session.execute()`.

#### `duckdb` + `duckdb-engine`
- `duckdb` is the embedded analytical database engine. It stores all document and chunk data in a single local file (`answerbot.duckdb`).
- `duckdb-engine` is the SQLAlchemy dialect adapter that bridges SQLAlchemy's ORM and DuckDB.
- DuckDB's built-in **FTS extension** (`PRAGMA create_fts_index`) powers the native BM25 full-text search.

#### `PyMuPDF` (`fitz`)
Used for PDF processing. Superior to pypdf for image extraction because it accesses low-level **XREF objects** in the PDF's cross-reference table. Each image on a page is extracted as raw bytes with its native format (`.png`, `.jpeg`, etc.) and saved to `backend/app/static/images/`.

#### `python-docx`
Extracts text from `.docx` files by iterating over all paragraphs in the document object. Returns content as a single-page chunk.

#### `rapidfuzz`
Provides `fuzz.token_set_ratio()` — a fuzzy string matching algorithm that compares query tokens against chunk content regardless of token order. Used as a fallback when BM25 returns no results. Results below a 0.20 score threshold are discarded.

#### `openai`
The official OpenAI Python SDK. Used to call `client.chat.completions.create()` with a structured message array containing a system prompt, previous chat history (sliding window of 6 messages), and the current user query.

#### `python-dotenv`
Loads `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `OPENAI_MODEL` from the `.env` file at startup via `load_dotenv()`.

#### `python-multipart`
Required by FastAPI to handle `multipart/form-data` file uploads and `Form(...)` fields in the `/upload` and `/query` endpoints.

---

### 5. Database Design

#### Engine Configuration

```python
engine = create_engine(
    f"duckdb:///{db_path}",
    connect_args={"preload_extensions": ["fts"]}
)
```

DuckDB is initialized with the FTS extension preloaded. The database file is stored at the project root as `answerbot.duckdb`. DuckDB enforces **single-writer locking** — only one process can hold a write connection at a time.

---

#### Table: `documents`

Stores one record per uploaded file.

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER (PK) | Manually assigned sequential ID |
| `file_name` | TEXT | Original filename as uploaded |
| `upload_time` | TEXT | ISO 8601 UTC timestamp of upload |

The `cascade="all, delete-orphan"` relationship ensures all child chunks are automatically deleted when a document is removed.

---

#### Table: `document_chunks`

Stores all text segments and associated image paths for every document.

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER (PK) | Manually assigned sequential ID |
| `document_id` | INTEGER (FK) | References `documents.id`, cascades on DELETE |
| `page_number` | INTEGER | Page the chunk came from (1-indexed) |
| `section` | TEXT (nullable) | Reserved for future section-level metadata |
| `content` | TEXT | The text content, prefixed with `[File: X - Page N]` header |
| `image_path` | TEXT (nullable) | Comma-separated relative paths to extracted images for this page |

---

#### Table Relations

```
documents (1) ──────< document_chunks (many)
    id ──────────────── document_id (FK, CASCADE DELETE)
```

One document maps to many chunks. Deleting a document cascades and deletes all its associated chunks automatically.

---

#### FTS Index

```sql
PRAGMA create_fts_index('document_chunks', 'id', 'content');
```

Builds a native BM25 inverted index over the `content` column of `document_chunks`. Re-created after every upload or deletion via `refresh_fts_index()`. The `match_bm25(id, query)` function scores each chunk by relevance.

---

### 6. Ingestion Pipeline

**File:** `backend/app/ingestion/ingestion.py`

#### Flow
```
Upload → Detect extension → Extract text + images → Chunk text → Store chunks
```

#### PDF Extraction (PyMuPDF)
1. Open the PDF as a `fitz.Document` stream.
2. For each page, call `page.get_text()` to extract full text.
3. Call `page.get_images(full=True)` to get all embedded image references.
4. For each image, read its XREF number → call `doc.extract_image(xref)` → get raw bytes and extension.
5. Save to `backend/app/static/images/doc_{id}_pg_{N}_img_{idx}.{ext}`.
6. Collect all image paths for that page as a comma-separated string.

#### Text Chunking
Splits text into word-level windows of ~400 words with a 50-word overlap between consecutive chunks.

#### Chunk Storage
Each chunk has a metadata header prepended:
```
[File: Water-Filling-Algorithm.pdf - Page 3]
<actual chunk text>
```
This allows BM25 to match document-specific queries like "summarize the water filling pdf" against page-level metadata. The **first chunk** per page carries the `image_path`; subsequent chunks on the same page have `image_path = None` to prevent duplication.

---

### 7. Retrieval Pipeline

**File:** `backend/app/retrieval/retrieval.py`

#### `retrieve_top_k(db, query, k=20)` — 4-Stage Cascade

**Stage 1 — Lead Chunk Injection (Global Queries)**
Detects summary-style queries (`"summarize"`, `"what is this about"`, `"overview"`). Fetches page-1 chunks from matching documents to bootstrap high-level context.

**Stage 2 — Strict BM25**
```sql
SELECT dc.content, d.file_name, dc.page_number, dc.image_path,
       fts_main_document_chunks.match_bm25(dc.id, :query) AS score
FROM document_chunks dc
JOIN documents d ON dc.document_id = d.id
WHERE fts_main_document_chunks.match_bm25(dc.id, :query) IS NOT NULL
ORDER BY score DESC LIMIT :limit
```

**Stage 3 — Relaxed BM25 (Term-by-Term)**
If strict BM25 returns nothing, the query is tokenized and each term is searched independently. Results are merged and re-sorted by score.

**Stage 4 — RapidFuzz Fallback**
All chunks are fetched and scored using `fuzz.token_set_ratio()`. Chunks below 0.20 score are discarded.

#### Deduplication & Balancing
A `seen_keys` set prevents duplicate `(file_name, page_number, content)` triples. A `doc_match_counts` dict caps any single document at 5 chunks when multiple documents are present.

---

### 8. LLM Answer Generation

**File:** `backend/app/llm/llm_client.py`

The system prompt instructs the model to:
- Answer **only from the provided chunks**.
- Never claim it cannot display images (the UI handles rendering).
- Cite sources by document name and page number.
- Return `"Answer not found in provided documents"` when context is insufficient.

A sliding window of **last 6 messages** from the session is injected before the current query for multi-turn conversational awareness.

---

### 9. API Routes

| Method | Route | Description |
|---|---|---|
| `GET` | `/` | Health check |
| `POST` | `/upload` | Upload and ingest a document |
| `GET` | `/documents` | List all ingested documents |
| `DELETE` | `/documents/{id}` | Delete a document and its chunks |
| `GET` | `/api/download?path=` | Force-download an image as an OS attachment |
| `POST` | `/query` | Submit a query; returns answer, sources, and images |
| `GET` | `/static/images/*` | Serve extracted images |

---

### 10. Frontend Architecture

Chat sessions are persisted in `localStorage` under `answerbot_chat_sessions`. Each session stores an isolated message array, a title, and a timestamp. The sidebar lists all sessions sorted by recency; individual sessions can be created, switched, or deleted.

Image responses are rendered as flex-wrap galleries. Each image card has a hover-reveal **download button** that routes through `/api/download`, which returns the file as `application/octet-stream` — triggering a native OS file save dialog.

---

### 11. Image Extraction & Conditional Rendering

- Images are extracted at **ingestion time** via PyMuPDF's XREF scanner and stored on disk.
- At **query time**, image keywords (`image`, `chart`, `diagram`, `graph`, `photo`, etc.) toggle image delivery.
- A regex parser (`"page 1"`, `"first page"`, `"3rd page"`) filters images to only the requested page(s).
- The LLM receives a `[SYSTEM NOTE]` in chunk content confirming images are visible to the user.

---

### 12. Cross-Platform Compatibility

| Platform | `.doc` Tool |
|---|---|
| macOS | `textutil -convert txt -stdout` |
| Windows | `win32com.client` Word COM → binary scrape fallback |
| Linux | `antiword` |

All other components (FastAPI, DuckDB, PyMuPDF, OpenAI SDK) are natively cross-platform.

---

### 13. Deep Code Explanation (Module Logic)

This section provides a high-level walkthrough of the internal logic within each major module:

#### `backend/main.py` (The Orchestrator)
This is the entry point of the FastAPI application.
- **Lifespan/Startup**: Initializes the database and FTS index.
- **`/upload`**: Reads the file stream, determines extension, and hands off to `ingestion.py`.
- **`/query`**: 
    - It first parses the `chat_history` from the form data.
    - It triggers the **Retrieval Pipeline** (`retrieval.py`) to get context.
    - **Logic Spike**: It checks the query for "image" keywords and "page number" regexes. It then filters the retrieved chunks' `image_path` metadata so the LLM only "sees" images that match the user's specific page request.
    - Finally, it calls the **LLM Client** (`llm_client.py`) to generate the prose answer.
- **`/api/download`**: A specialized route that uses `FileResponse` with `Content-Disposition: attachment`. This bypasses browser "preview" modes and forces a local file save on the user's machine.

#### `backend/app/ingestion/ingestion.py` (The Parser)
- **`process_file`**: Routes different file types to their specific extractors.
- **PDF Logic**: Uses `fitz` (PyMuPDF) to iterate pages. It extracts text and performs an **XREF-based image sweep**. This is more robust than standard PDF parsers because it extracts the raw image objects directly from the PDF structure.
- **Chunking**: Uses a sliding window approach (words) with overlap. *Crucially*, it prepends a header `[File: name - Page X]` to every text chunk. This "injects" metadata into the text index, allowing the search engine to find "Page 1" even if the page text itself doesn't contain the word "one".

#### `backend/app/retrieval/retrieval.py` (The Search Engine)
- **`retrieve_top_k`**: Implements a cascading search strategy to ensure high recall:
    1. **Lead Chunks**: If a query is global ("summarize this"), it automatically pulls page-1 chunks.
    2. **BM25 Strict**: Uses DuckDB's native full-text search index to find exact keyword matches.
    3. **BM25 Relaxed**: If strict fails (returns 0 chunks), it breaks the query into tokens and searches for any token match.
    4. **Fuzzy Fallback**: Uses `rapidfuzz` to calculate string similarity scores for every chunk in the DB. This handles typos and synonyms that the keyword index might miss.

#### `backend/app/llm/llm_client.py` (The Brain)
- **Prompt Engineering**: Uses a sophisticated system prompt that defines the bot as a "context-only" assistant.
- **Image Awareness**: The prompt explicitly tells GPT-4o that images ARE being shown by the UI, preventing the model from saying "I cannot see images."
- **Context Injection**: It formats the retrieved DuckDB chunks into a serialized "Source/Content" block for the model to digest.

#### `backend/app/db.py` (The Persistence)
- Defines the SQLAlchemy models for `Document` and `DocumentChunk`.
- **`refresh_fts_index`**: Manages the life-cycle of the DuckDB FTS index. It drops and recreates the index on every change (upload/delete) to ensure the search results are always fresh and consistent.

#### `frontend/script.js` (The Interface)
- **Session Logic**: Uses a `UUID`-based keyed object in `localStorage` to keep chats separate.
- **Rendering**: Implements a custom Markdown-lite renderer for chat bubbles and a dynamic gallery for images.
- **Download Hook**: Instead of simple links, it points to the backend's `/api/download` route to ensure native local file saving works across all browsers.
