import os
from typing import List, Dict, Any
import openai

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

def generate_answer(query: str, chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
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
    
    # Construct context string
    context = "\n---\n".join([f"Source: {c['file_name']} (Page {c['page_number']})\nContent: {c['content']}" for c in chunks])
    
    prompt = f"""You are a high-performance QA system. You have been provided with CONTEXT from one or more documents.
Your goal is to answer the USER QUERY based ONLY on the provided CONTEXT.

GUIDELINES:
- If the user asks for a summary or what a document is about, synthesize the main points from the provided context (which includes document introductions).
- When mentioning specific information, always cite the source (e.g., 'According to [Document Name]...', 'Page [X] of [Document Name] states...').
- If the query mentions a specific document by name, focus your answer on the context belonging to that document.
- If the answer cannot be found in the provided context, states: 'Answer not found in provided documents'.
- Maintain a professional, objective tone.

CONTEXT:
{context}

USER QUERY:
{query}

ANSWER:"""
    
    try:
        # Use the configured model
        print(f"LLM DEBUG: Requesting generation with model '{openai_model}'...")
        
        response = client.chat.completions.create(
            model=openai_model,
            messages=[{"role": "user", "content": prompt}],
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
