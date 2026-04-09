import os
from typing import List, Dict, Any
import openai
from dotenv import load_dotenv

load_dotenv()

# OpenAI Client Initialization:
api_key = os.getenv("OPENAI_API_KEY")
base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
openai_model = os.getenv("OPENAI_MODEL", "gpt-4o")

if not api_key:
    print("LLM WARNING: OPENAI_API_KEY is not set in the environment.")
    client = None
else:
    client = openai.OpenAI(
        api_key=api_key,
        base_url=base_url
    )

def generate_answer(query: str, chunks: List[Dict[str, Any]], chat_history: List[Dict[str, str]] = None) -> Dict[str, Any]:
    """Generates an answer using OpenAI GPT-4o."""
    if client is None:
        return {
            "answer": "OPENAI_API_KEY is not set. Configure it to enable answer generation.",
            "sources": []
        }
    
    if not chunks:
        print("LLM DEBUG: No context chunks provided. Returning early.")
        return {
            "answer": "Answer not found in provided documents",
            "sources": []
        }
    
    if chat_history is None:
        chat_history = []
        
    # Construct context string
    context = "\n---\n".join([f"Source: {c['file_name']} (Page {c['page_number']})\nContent: {c['content']}" for c in chunks])
    
    system_prompt = f"""You are a high-performance QA system. You have been provided with CONTEXT from one or more documents.
Your goal is to answer the USER QUERY based ONLY on the provided CONTEXT.

IMPORTANT ABOUT IMAGES:
- You are part of a system where images are rendered DIRECTLY in the chat UI by the application itself.
- If the CONTEXT contains a [SYSTEM NOTE] stating that images are displayed to the user, those images ARE already visible to them in the chat interface - do NOT say you cannot show or display images.
- Simply acknowledge the images are shown and describe or reference them based on the surrounding context.

GUIDELINES:
- RESPONSE LANGUAGE: Always generate your final response in **English**, regardless of the language of the provided CONTEXT or the USER QUERY.
- If the user asks for a summary or what a document is about, synthesize the main points from the provided context.
- When mentioning specific information, always cite the source (e.g., 'According to [Document Name]...', 'Page [X] of [Document Name] states...').
- If the query mentions a specific document by name, focus your answer on the context belonging to that document.
- If the answer cannot be found in the provided context, state: 'Answer not found in provided documents'.
- Maintain a professional, objective tone.

CONTEXT:
{context}"""

    messages = [{"role": "system", "content": system_prompt}]
    
    # Map previous history
    # Only keep last 6 messages to avoid context bloat
    for msg in chat_history[-6:]:
        # Our frontend history uses "bot" for assistant
        role = "assistant" if msg.get("role") == "bot" else "user"
        content = msg.get("content", "")
        if content:
            messages.append({"role": role, "content": content})
            
    messages.append({"role": "user", "content": f"USER QUERY:\n{query}\n\nANSWER:"})

    try:
        # Use the configured model
        print(f"LLM DEBUG: Requesting generation with model '{openai_model}'...")
        
        response = client.chat.completions.create(
            model=openai_model,
            messages=messages,
            temperature=0,
            timeout=45.0 # 45 second timeout for complex GPT generations
        )
        
        answer = response.choices[0].message.content.strip()
        print(f"LLM DEBUG: Received response ({len(answer)} chars).")
        
    except Exception as e:
        print(f"LLM ERROR: {str(e)}")
        return {
            "answer": f"Connection Error: {str(e)}. Please check your .env configuration.",
            "sources": []
        }
    
    # Extract unique sources
    unique_sources = []
    seen = set()
    for c in chunks:
        source_str = f"{c['file_name']} (Page {c['page_number']})"
        if source_str not in seen:
            unique_sources.append(source_str)
            seen.add(source_str)
            
    return {
        "answer": answer,
        "sources": unique_sources
    }

def transcribe_audio(audio_file_path: str) -> str:
    """Uses OpenAI Whisper-1 to transcribe audio files."""
    if client is None:
        return "Error: OpenAI client not initialized. Check API key."
    
    try:
        with open(audio_file_path, "rb") as audio_file:
            print(f"WHISPER DEBUG: Transcribing {audio_file_path}...")
            transcription = client.audio.transcriptions.create(
                model="whisper-1", 
                file=audio_file,
                response_format="text"
            )
            return transcription.strip()
    except Exception as e:
        print(f"WHISPER ERROR: {str(e)}")
        return f"Transcription Error: {str(e)}"
