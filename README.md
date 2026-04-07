# AnswerBot

Welcome to **AnswerBot** — a local, server-backed Retrieval-Augmented Generation (RAG) system powered by DuckDB. 

## Features
- **FastAPI Backend**: Uses standard endpoints mapping for Document Ingestion and Queries.
- **DuckDB Retrieval**: High-speed Full-Text Search (FTS) mapped locally seamlessly through SQLAlchemy.
- **Support for Docs**: Upload standard `.pdf`, `.docx`, `.doc`, `.txt`.

## Getting Started
1. **Initialize the local virtual environment.** 
   Ensure your `.venv` is loaded.
2. **Setup your environment variables.**
   Put your `OPENAI_API_KEY` inside `.env`.
3. **Run your backend.**
   ```bash
   python main.py
   ```
4. **Access the Frontend**
   Open `frontend/index.html` in your browser.
