# AnswerBot System Report

A detailed overview of the AnswerBot RAG system architecture, methodologies, and performance characteristics.

## 🔍 Retrieval Method

AnswerBot now utilizes **DuckDB-backed retrieval** with a hybrid lexical + fuzzy ranking strategy.

- **Storage**: Documents and chunks are persisted in a local DuckDB database file.
- **Search Logic**: Queries are matched in stages: DuckDB FTS BM25 strict query, BM25 relaxed term-wise fallback, then Python fuzzy matching (`rapidfuzz`).
- **Ranking**: Candidate chunks are scored by BM25 first, with fuzzy scores as a final fallback.
- **Diversity**: Result blending limits over-concentration from a single document so answers cite broader evidence when available.

## 🧠 Prompt Engineering

The system uses a **Strict Grounding Prompt** to prevent hallucinations:

```text
You are a QA system. Answer ONLY from the provided context.
If the answer is not present, say:
'Answer not found in provided documents'

CONTEXT:
{context}

USER QUERY:
{query}

ANSWER:
```

### Key Rationale:
- **Zero-Shot Grounding**: Ensures the LLM stays within the boundaries of the retrieved chunks.
- **Explicit Fallback**: Handles out-of-domain queries gracefully by forcing a "not found" response.

## ⚠️ Failure Case Analysis

### Case: Semantic Mismatch
**Scenario**: A user asks "How do I increase revenue?" but the document uses terms like "earnings growth" or "top-line expansion."
**Why it fails**: Keyword-first retrieval may miss semantically related content when synonyms are used and shared terms are sparse, causing low scores and weaker context coverage.

## 🚀 Future Improvements

1. **Hybrid Search**: Add vector embeddings for semantic retrieval and blend them with current lexical scoring.
2. **Re-Ranking**: Use a smaller, faster Cross-Encoder model to re-rank the top 20 lexical/fuzzy candidates before passing top chunks to the LLM.
3. **Multi-Modal Support**: Enhance image extraction to use OCR (Optical Character Recognition) for scanned PDFs or diagrams, making them searchable as well.
4. **Metadata Filtering**: Allow users to filter searches by date, author, or document category for more precise retrieval.
