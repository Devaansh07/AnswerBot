from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
import os
from typing import List, Dict, Any
from backend.app.db import get_db, Document, DocumentChunk, init_db, refresh_fts_index
from backend.app.ingestion.ingestion import process_file
from backend.app.retrieval.retrieval import retrieve_top_k
from backend.app.llm.llm_client import generate_answer, transcribe_audio

app = FastAPI(title="AnswerBot RAG System")

# Mount static directory for images and frontend
app.mount("/static", StaticFiles(directory="backend/app/static"), name="static")
app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")

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
    
    if file_ext not in [".pdf", ".docx", ".doc", ".txt", ".mp3", ".wav", ".m4a", ".webm"]:
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

from fastapi.responses import FileResponse

@app.get("/api/download")
async def download_file(path: str):
    """Serve a file strictly as an attachment to automatically force OS downloads."""
    # Strip leading slash if present
    if path.startswith("/"):
        path = path[1:]
        
    full_path = os.path.join("backend", "app", path)
    if os.path.exists(full_path):
        filename = os.path.basename(full_path)
        return FileResponse(full_path, media_type="application/octet-stream", filename=filename)
    raise HTTPException(status_code=404, detail="File not found")

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
        
        # 2. Check if user explicitly asked for an image
        image_keywords = ["image", "picture", "diagram", "chart", "graph", "figure", "plot", "photo"]
        wants_image = any(kw in query.lower() for kw in image_keywords)
        
        import re
        word_to_num = {
            "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
            "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
            "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5
        }
        
        req_page_nums = []
        page_matches = re.finditer(r'(?:page(?:s)?\s*(\d+))|((first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|1st|2nd|3rd|4th|5th)\s*page)', query.lower())
        for m in page_matches:
            if m.group(1):
                req_page_nums.append(int(m.group(1)))
            elif m.group(2):
                req_page_nums.append(word_to_num[m.group(2)])
        
        images_to_return = []
        if wants_image:
            for c in retrieved_chunks:
                # Strictly enforce page check if any pages were requested
                if req_page_nums and c["page_number"] not in req_page_nums:
                     c["image_path"] = None
                     continue
                
                if c.get("image_path"):
                    paths = c["image_path"].split(",")
                    for p in paths:
                        if p and p not in images_to_return:
                            images_to_return.append(p)
                    c["content"] += f"\n[SYSTEM NOTE: The related images from {c['file_name']} (Page {c['page_number']}) are currently displayed to the user. You can refer to them.]"
        else:
            # Mask image paths to ensure UI stays clean
            for c in retrieved_chunks:
                c["image_path"] = None
        
        # 3. Generate answer
        print(f"DEBUG: Calling LLM for generation...")
        result = generate_answer(query, retrieved_chunks, history_list)
        print(f"DEBUG: Answer generated successfully.")
        
        # 4. Construct response
        return {
            "query": query,
            "retrieved_results": retrieved_chunks,
            "answer": result["answer"],
            "sources": result["sources"],
            "images": images_to_return
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/transcribe-live")
async def transcribe_live(audio: UploadFile = File(...)):
    """Transcribes live audio blobs using Whisper for maximum accuracy."""
    import tempfile
    
    file_ext = os.path.splitext(audio.filename)[1].lower() if audio.filename else ".webm"
    if not file_ext: file_ext = ".webm"

    with tempfile.NamedTemporaryFile(suffix=file_ext, delete=False) as tf:
        content = await audio.read()
        tf.write(content)
        temp_path = tf.name
    
    try:
        text = transcribe_audio(temp_path)
        return {"text": text}
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
