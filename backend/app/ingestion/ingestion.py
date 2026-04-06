import os
from io import BytesIO
from typing import List, Dict, Any
from pypdf import PdfReader
import docx
from sqlalchemy import func
from sqlalchemy.orm import Session
from backend.app.db import Document, DocumentChunk, refresh_fts_index

def extract_text_from_pdf(file_content: bytes, doc_id: int) -> List[Dict[str, Any]]:
    """Extracts text, page numbers, and images from a PDF."""
    reader = PdfReader(BytesIO(file_content))
    pages_data = []
    
    # Ensure static directory exists
    static_dir = os.path.join("backend", "app", "static", "images")
    os.makedirs(static_dir, exist_ok=True)

    for i, page in enumerate(reader.pages):
        page_num = i + 1
        text = page.extract_text()
        
        # Image extraction
        image_path = None
        if len(page.images) > 0:
            try:
                # Save the first image of the page as a representative image
                image = page.images[0]
                img_name = f"doc_{doc_id}_pg_{page_num}.png"
                img_path = os.path.join(static_dir, img_name)
                with open(img_path, "wb") as f:
                    f.write(image.data)
                image_path = f"/static/images/{img_name}"
            except Exception as e:
                print(f"Error extracting image from page {page_num}: {e}")

        if text or image_path:
            pages_data.append({
                "page_number": page_num,
                "content": text.strip() if text else "",
                "image_path": image_path
            })
    return pages_data

def extract_text_from_docx(file_content: bytes) -> List[Dict[str, Any]]:
    """Extracts text from a DOCX."""
    doc = docx.Document(BytesIO(file_content))
    full_text = []
    for para in doc.paragraphs:
        full_text.append(para.text)
    
    # Since DOCX doesn't have reliable page numbers without extra libs, 
    # we treat it as a single page or chunk it differently.
    return [{
        "page_number": 1,
        "content": "\n".join(full_text).strip()
    }]

def extract_text_from_txt(file_content: bytes) -> List[Dict[str, Any]]:
    """Extracts text from a TXT file."""
    text = file_content.decode("utf-8")
    return [{
        "page_number": 1,
        "content": text.strip()
    }]

def extract_text_from_doc(file_content: bytes) -> List[Dict[str, Any]]:
    """Extracts text from a .doc file using macOS textutil."""
    import subprocess
    import tempfile
    
    with tempfile.NamedTemporaryFile(suffix=".doc", delete=False) as tf:
        tf.write(file_content)
        temp_path = tf.name
    
    try:
        # textutil -convert txt -stdout <path>
        result = subprocess.run(
            ["textutil", "-convert", "txt", "-stdout", temp_path],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            return [{
                "page_number": 1,
                "content": result.stdout.strip()
            }]
        else:
            print(f"textutil error: {result.stderr}")
            return []
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

def chunk_text(text: str, chunk_size=400, overlap=50) -> List[str]:
    """Chunks text into segments of approximately chunk_size words."""
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size - overlap):
        chunk = " ".join(words[i : i + chunk_size])
        if chunk:
            chunks.append(chunk)
    return chunks


def _next_id(db: Session, model) -> int:
    current_max = db.query(func.max(model.id)).scalar()
    return 1 if current_max is None else int(current_max) + 1

def process_file(db: Session, file_name: str, file_content: bytes, file_ext: str):
    """Main ingestion pipeline."""
    # 1. Insert into documents table
    db_doc = Document(id=_next_id(db, Document), file_name=file_name)
    db.add(db_doc)
    db.commit()
    db.refresh(db_doc)
    next_chunk_id = _next_id(db, DocumentChunk)
    
    # 2. Extract text based on extension
    if file_ext == ".pdf":
        pages = extract_text_from_pdf(file_content, db_doc.id)
    elif file_ext == ".docx":
        pages = extract_text_from_docx(file_content)
    elif file_ext == ".doc":
        pages = extract_text_from_doc(file_content)
    elif file_ext == ".txt":
        pages = extract_text_from_txt(file_content)
    else:
        return None

    # 3. Chunk and store
    for page in pages:
        content_text = page["content"]
        image_path = page.get("image_path")
        
        # If there's an image but no text, create a placeholder chunk to ensure the image is indexed
        if not content_text.strip() and image_path:
            db_chunk = DocumentChunk(
                id=next_chunk_id,
                document_id=db_doc.id,
                page_number=page["page_number"],
                content="[Document Image Data]", # Placeholder for retrieval
                image_path=image_path
            )
            db.add(db_chunk)
            next_chunk_id += 1
            continue

        chunks = chunk_text(content_text)
        for chunk in chunks:
            if not chunk.strip():
                continue
            db_chunk = DocumentChunk(
                id=next_chunk_id,
                document_id=db_doc.id,
                page_number=page["page_number"],
                content=chunk,
                image_path=image_path if content_text == chunk else None # Attaching image to first chunk only
            )
            db.add(db_chunk)
            next_chunk_id += 1
    
    # Force associate image to the first chunk if multiple chunks exist
    # This prevents the image from being duplicated across all chunks of the same page
    db.commit()
    refresh_fts_index()
    return db_doc.id
