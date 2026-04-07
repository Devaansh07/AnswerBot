from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
import os
from typing import List, Dict, Any
from backend.app.db import get_db, Document, DocumentChunk, init_db, refresh_fts_index
from backend.app.ingestion.ingestion import process_file
from backend.app.retrieval.retrieval import retrieve_top_k
from backend.app.llm.llm_client import generate_answer

app = FastAPI(title="AnswerBot RAG System")

# Mount static directory for images
app.mount("/static", StaticFiles(directory="backend/app/static"), name="static")

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup_event():
    init_db()

@app.get("/")
async def root():
    return {"message": "Welcome to AnswerBot RAG System"}

@app.post("/upload")
async def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Handles document upload and ingestion."""
    content = await file.read()
    file_name = file.filename
    file_ext = os.path.splitext(file_name)[1].lower()
    
    if file_ext not in [".pdf", ".docx", ".doc", ".txt"]:
        raise HTTPException(status_code=400, detail="Unsupported file format")
        
    try:
        doc_id = process_file(db, file_name, content, file_ext)
        if doc_id:
            return {"status": "success", "document_id": doc_id, "file_name": file_name}
        else:
            raise HTTPException(status_code=500, detail="Ingestion failed")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/documents")
async def list_documents(db: Session = Depends(get_db)):
    """Returns a list of all ingested documents."""
    docs = db.query(Document).order_by(Document.upload_time.desc()).all()
    return [{"id": d.id, "file_name": d.file_name, "upload_time": d.upload_time} for d in docs]

@app.delete("/documents/{doc_id}")
async def delete_document(doc_id: int, db: Session = Depends(get_db)):
    """Deletes a document and its chunks."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Chunks are deleted automatically due to cascade="all, delete-orphan" in db.py
    db.delete(doc)
    db.commit()
    refresh_fts_index()
    return {"status": "success", "message": f"Document {doc_id} deleted"}

import json

@app.post("/query")
async def query_documents(query: str = Form(...), chat_history: str = Form("[]"), db: Session = Depends(get_db)):
    """Handles query retrieval and generation."""
    print(f"\n--- New Query Received: '{query}' ---")
    try:
        history_list = json.loads(chat_history)
    except Exception:
        history_list = []
        
    try:
        # 1. Retrieve top 5 chunks
        print(f"DEBUG: Starting retrieval for '{query}'...")
        retrieved_chunks = retrieve_top_k(db, query)
        print(f"DEBUG: Retrieved {len(retrieved_chunks)} chunks.")
        
        # 2. Generate answer
        print(f"DEBUG: Calling LLM for generation...")
        result = generate_answer(query, retrieved_chunks, history_list)
        print(f"DEBUG: Answer generated successfully.")
        
        # 3. Construct response
        return {
            "query": query,
            "retrieved_results": retrieved_chunks,
            "answer": result["answer"],
            "sources": result["sources"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
