import os
import uuid
import json
import datetime
from typing import List, Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

import chromadb
import docx  # python-docx
import fitz  # PyMuPDF
import pytesseract
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
from pdf2image import convert_from_path
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer, CrossEncoder
import os
import uuid
import json
import datetime
from typing import List, Optional, Dict
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

import chromadb
import docx  # python-docx
import fitz  # PyMuPDF
import pytesseract
import requests

app = FastAPI(title="Document Intelligence API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Directory where uploaded documents are stored
DOCUMENTS_DIR = os.getenv("DOCUMENTS_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "documents"))

# Directory where ChromaDB persists its data
CHROMA_DIR = os.getenv("CHROMA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "chroma_db"))

# Load the embedding model once at startup (not per-request)
embedding_model = SentenceTransformer("all-MiniLM-L6-v2")

# Load the reranker model once at startup
try:
    reranker_model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
except Exception as e:
    print(f"Failed to load reranker model: {e}")
    reranker_model = None

# ChromaDB persistent client and collection, created once at startup
chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
chunks_collection = chroma_client.get_or_create_collection(name="document_chunks")

# Ollama configuration
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3:latest")

# Tesseract OCR configuration (for scanned/image-only PDF pages)
pytesseract.pytesseract.tesseract_cmd = os.getenv("TESSERACT_PATH", r"C:\Program Files\Tesseract-OCR\tesseract.exe")

# In-memory status tracking for background jobs
job_status: Dict[str, str] = {}
# In-memory conversation history
conversation_history: Dict[str, List[Dict[str, str]]] = {}

# Conservative distance threshold for L2 distance (0.0=perfect match)
DISTANCE_THRESHOLD = 1.0


def retrieve_context(query: str, filenames: Optional[List[str]] = None, top_k: int = 3) -> List[dict]:
    """Retrieves and ranks chunks from ChromaDB with a distance threshold."""
    if chunks_collection.count() == 0:
        return []

    query_embedding = embedding_model.encode([query])[0].tolist()
    # Retrieve a larger candidate set to allow for threshold filtering
    candidate_k = max(top_k * 3, 10)

    # Multi-document comparison: query each document separately so evidence
    # is guaranteed from every requested file, not just the globally closest matches.
    if filenames and len(filenames) > 1:
        documents = []
        metadatas = []
        distances = []
        for fname in filenames:
            per_doc_results = chunks_collection.query(
                query_embeddings=[query_embedding],
                n_results=candidate_k,
                where={"filename": fname},
            )
            documents.extend(per_doc_results.get("documents", [[]])[0])
            metadatas.extend(per_doc_results.get("metadatas", [[]])[0])
            distances.extend(per_doc_results.get("distances", [[]])[0])
    else:
        where_filter = {"filename": {"$in": filenames}} if filenames else None
        query_results = chunks_collection.query(
            query_embeddings=[query_embedding],
            n_results=candidate_k,
            where=where_filter,
        )
        documents = query_results.get("documents", [[]])[0]
        metadatas = query_results.get("metadatas", [[]])[0]
        distances = query_results.get("distances", [[]])[0]

    # Combine results, filter by distance threshold
    candidates = []
    seen_ids = set()

    for text, metadata, distance in zip(documents, metadatas, distances):
        if distance <= DISTANCE_THRESHOLD:
            # Main chunk
            fname = metadata.get('filename')
            pnum = metadata.get('page_number')
            idx = metadata.get('chunk_index')
            chunk_id = f"{fname}_{pnum}_{idx}"
            if chunk_id not in seen_ids:
                candidates.append({
                    "text": text,
                    "metadata": metadata or {},
                    "distance": distance,
                })
                seen_ids.add(chunk_id)

    # Fallback: specific filename(s) were requested but the distance threshold
    # filtered out every candidate. If those filenames do have indexed chunks
    # (i.e. the query above actually returned candidates), fall back to the
    # closest chunks for the selected filename(s) regardless of the threshold,
    # reusing the same query_embedding and already-fetched candidate set.
    if not candidates and filenames:
        for text, metadata, distance in zip(documents, metadatas, distances):
            fname = metadata.get('filename')
            pnum = metadata.get('page_number')
            idx = metadata.get('chunk_index')
            chunk_id = f"{fname}_{pnum}_{idx}"
            if chunk_id not in seen_ids:
                candidates.append({
                    "text": text,
                    "metadata": metadata or {},
                    "distance": distance,
                })
                seen_ids.add(chunk_id)
        candidates.sort(key=lambda x: x["distance"])

    # Reranking step
    if reranker_model and candidates:
        # Prepare pairs for reranking
        pairs = [(query, res["text"]) for res in candidates]
        scores = reranker_model.predict(pairs)
        # Add scores to results
        for i, score in enumerate(scores):
            candidates[i]["score"] = float(score)
        # Sort by rerank score (descending)
        candidates.sort(key=lambda x: x["score"], reverse=True)
    else:
        # Sort by distance (ascending) if no reranker or no results
        candidates.sort(key=lambda x: x["distance"])

    # Select final top_k results
    final_results = candidates[:top_k]

    # Context Windowing: Fetch Neighbors for top_k results
    expanded_results = list(final_results)
    expanded_seen_ids = set(f"{res['metadata'].get('filename')}_{res['metadata'].get('page_number')}_{res['metadata'].get('chunk_index')}" for res in final_results)

    for result in final_results:
        metadata = result["metadata"]
        fname = metadata.get('filename')
        pnum = metadata.get('page_number')
        idx = metadata.get('chunk_index')

        if fname and pnum is not None and idx is not None:
            # Query for neighbors by metadata, not similarity using get()
            neighbor_results = chunks_collection.get(
                where={
                    "$and": [
                        {"filename": fname},
                        {"page_number": pnum},
                        {"chunk_index": {"$in": [idx - 1, idx + 1]}}
                    ]
                }
            )
            n_docs = neighbor_results.get("documents", [])
            n_metas = neighbor_results.get("metadatas", [])

            for n_text, n_meta in zip(n_docs, n_metas):
                n_chunk_id = f"{n_meta.get('filename')}_{n_meta.get('page_number')}_{n_meta.get('chunk_index')}"
                if n_chunk_id not in expanded_seen_ids:
                    expanded_results.append({
                        "text": n_text,
                        "metadata": n_meta or {},
                        "distance": result["distance"], # Keep original chunk's distance
                        "score": result.get("score")    # Keep original chunk's score
                    })
                    expanded_seen_ids.add(n_chunk_id)

    return expanded_results


def process_and_embed_background(filename: str):
    """Wrapper to run the pipeline and update status."""
    try:
        job_status[filename] = "Processing"
        process_and_embed(filename)
        job_status[filename] = "Ready"
    except Exception as e:
        print(f"Background processing failed for {filename}: {e}")
        job_status[filename] = f"Failed: {str(e)}"

# Document-level metadata, persisted to a JSON file next to chroma_db
DOCS_META_PATH = os.path.join(CHROMA_DIR, "documents_meta.json")


def load_docs_meta():
    if os.path.isfile(DOCS_META_PATH):
        try:
            with open(DOCS_META_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_docs_meta(meta):
    os.makedirs(CHROMA_DIR, exist_ok=True)
    with open(DOCS_META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


documents_meta = load_docs_meta()

SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".txt", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif")

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif")


def extract_pages(file_path: str, filename: str):
    """Return list of {page_number, text} for pdf/docx/txt/image, routing by extension.
    PDF keeps existing PyMuPDF + OCR fallback behavior unchanged.
    """
    lower_name = filename.lower()

    if lower_name.endswith(".pdf"):
        try:
            doc = fitz.open(file_path)
        except Exception:
            raise HTTPException(status_code=400, detail="Uploaded file is not a valid PDF.")

        pages = []
        for page_number in range(len(doc)):
            page = doc.load_page(page_number)
            page_text = page.get_text()

            if not page_text or not page_text.strip():
                try:
                    ocr_images = convert_from_path(
                        file_path,
                        first_page=page_number + 1,
                        last_page=page_number + 1,
                    )
                    page_text = pytesseract.image_to_string(ocr_images[0])
                except Exception as exc:
                    doc.close()
                    raise HTTPException(
                        status_code=500,
                        detail=f"OCR failed on page {page_number + 1} of '{filename}': {exc}",
                    )

            pages.append({"page_number": page_number + 1, "text": page_text})
        doc.close()
        return pages

    elif lower_name.endswith(".docx"):
        try:
            d = docx.Document(file_path)
        except Exception:
            raise HTTPException(status_code=400, detail="Uploaded file is not a valid DOCX.")
        full_text = "\n".join(p.text for p in d.paragraphs)
        return [{"page_number": 1, "text": full_text}]

    elif lower_name.endswith(".txt"):
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                full_text = f.read()
        except Exception:
            raise HTTPException(status_code=400, detail="Uploaded file is not readable text.")
        return [{"page_number": 1, "text": full_text}]

    elif lower_name.endswith(IMAGE_EXTENSIONS):
        try:
            image = Image.open(file_path)
            page_text = pytesseract.image_to_string(image)
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"OCR failed on image '{filename}': {exc}",
            )
        return [{"page_number": 1, "text": page_text}]

    else:
        raise HTTPException(status_code=400, detail="Unsupported file type.")


def process_and_embed(filename: str, chunk_size: int = 1000, chunk_overlap: int = 200):
    """Shared pipeline: extract -> chunk -> embed -> store in ChromaDB -> save doc metadata."""
    if chunk_size <= 0 or chunk_overlap <= 0:
        raise HTTPException(status_code=400, detail="chunk_size and chunk_overlap must be positive.")

    if chunk_size <= chunk_overlap:
        raise HTTPException(status_code=400, detail="chunk_size must be greater than chunk_overlap.")

    file_path = os.path.join(DOCUMENTS_DIR, filename)

    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found.")

    pages = extract_pages(file_path, filename)

    chunks = []
    chunk_id = 1
    step = chunk_size - chunk_overlap

    for page in pages:
        page_number = page["page_number"]
        page_text = page["text"]

        if not page_text or not page_text.strip():
            continue

        start = 0
        text_length = len(page_text)

        while start < text_length:
            end = min(start + chunk_size, text_length)
            chunk_text_value = page_text[start:end]

            if chunk_text_value.strip():
                chunks.append({
                    "chunk_id": chunk_id,
                    "page_number": page_number,
                    "text": chunk_text_value,
                })
                chunk_id += 1

            if end == text_length:
                break

            start += step

    # Generate embeddings for every chunk
    if chunks:
        texts = [chunk["text"] for chunk in chunks]
        embeddings = embedding_model.encode(texts)
        for chunk, embedding in zip(chunks, embeddings):
            chunk["embedding"] = embedding.tolist()
        embedding_dimension = len(embeddings[0])
    else:
        embedding_dimension = embedding_model.get_sentence_embedding_dimension()

    # Store every chunk in ChromaDB (persistent storage)
    if chunks:
        chunks_collection.upsert(
            ids=[f"{filename}_{chunk['chunk_id']}" for chunk in chunks],
            documents=[chunk["text"] for chunk in chunks],
            embeddings=[chunk["embedding"] for chunk in chunks],
            metadatas=[
                {
                    "filename": filename,
                    "page_number": chunk["page_number"],
                    "chunk_index": chunk["chunk_id"],
                    "char_count": len(chunk["text"]),
                }
                for chunk in chunks
            ],
        )

    # Save document-level metadata
    file_type = filename.lower().rsplit(".", 1)[-1]
    total_char_count = sum(len(page["text"]) for page in pages)
    documents_meta[filename] = {
        "filename": filename,
        "file_type": file_type,
        "total_pages": len(pages),
        "total_chunks": len(chunks),
        "char_count": total_char_count,
        "embedding_dimension": embedding_dimension,
        "uploaded_at": documents_meta.get(filename, {}).get("uploaded_at", datetime.datetime.utcnow().isoformat()),
        "last_embedded_at": datetime.datetime.utcnow().isoformat(),
    }
    save_docs_meta(documents_meta)

    return chunks, embedding_dimension


class ExtractTextRequest(BaseModel):
    filename: str


class ChunkTextRequest(BaseModel):
    filename: str
    chunk_size: int = 1000
    chunk_overlap: int = 200


class EmbedTextRequest(BaseModel):
    filename: str
    chunk_size: int = 1000
    chunk_overlap: int = 200


class SearchRequest(BaseModel):
    query: str
    top_k: int = 3
    filenames: Optional[List[str]] = None


class AskRequest(BaseModel):
    query: str
    top_k: int = 3
    conversation_id: str = "default"
    filenames: Optional[List[str]] = None


@app.get("/")
def read_root():
    return {"message": "Document Intelligence API is running"}


@app.get("/documents")
def list_documents():
    return {"documents": list(documents_meta.values())}


@app.post("/upload")
async def upload_document(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    # Basic validation: content type and file extension
    original_filename = file.filename or ""
    if not original_filename.lower().endswith(SUPPORTED_EXTENSIONS):
        raise HTTPException(status_code=400, detail="Only PDF, DOCX, TXT, or image (PNG, JPG, JPEG, WEBP, BMP, TIFF) files are allowed.")

    # Read file contents
    contents = await file.read()

    # Validate PDF file signature (magic bytes) only for PDFs
    if original_filename.lower().endswith(".pdf") and not contents.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid PDF.")

    # Ensure documents directory exists
    os.makedirs(DOCUMENTS_DIR, exist_ok=True)

    # Generate a unique saved filename to avoid collisions
    saved_filename = f"{uuid.uuid4().hex}_{original_filename}"
    saved_path = os.path.join(DOCUMENTS_DIR, saved_filename)

    with open(saved_path, "wb") as f:
        f.write(contents)

    # Schedule background processing
    background_tasks.add_task(process_and_embed_background, saved_filename)
    job_status[saved_filename] = "Queued"

    return {
        "success": True,
        "original_filename": original_filename,
        "saved_filename": saved_filename,
        "file_size": len(contents),
        "message": "File uploaded and processing queued.",
    }


@app.post("/extract-text")
async def extract_text(request: ExtractTextRequest):
    filename = request.filename

    if not filename.lower().endswith(SUPPORTED_EXTENSIONS):
        raise HTTPException(status_code=400, detail="Unsupported file type.")

    file_path = os.path.join(DOCUMENTS_DIR, filename)

    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found.")

    pages = extract_pages(file_path, filename)

    return {
        "filename": filename,
        "total_pages": len(pages),
        "pages": pages,
    }


@app.post("/chunk-text")
async def chunk_text(request: ChunkTextRequest):
    filename = request.filename
    chunk_size = request.chunk_size
    chunk_overlap = request.chunk_overlap

    if not filename.lower().endswith(SUPPORTED_EXTENSIONS):
        raise HTTPException(status_code=400, detail="Unsupported file type.")

    if chunk_size <= 0 or chunk_overlap <= 0:
        raise HTTPException(status_code=400, detail="chunk_size and chunk_overlap must be positive.")

    if chunk_size <= chunk_overlap:
        raise HTTPException(status_code=400, detail="chunk_size must be greater than chunk_overlap.")

    file_path = os.path.join(DOCUMENTS_DIR, filename)

    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found.")

    pages = extract_pages(file_path, filename)

    chunks = []
    chunk_id = 1
    step = chunk_size - chunk_overlap

    for page in pages:
        page_number = page["page_number"]
        page_text = page["text"]

        if not page_text or not page_text.strip():
            continue

        start = 0
        text_length = len(page_text)

        while start < text_length:
            end = min(start + chunk_size, text_length)
            chunk_text_value = page_text[start:end]

            if chunk_text_value.strip():
                chunks.append({
                    "chunk_id": chunk_id,
                    "page_number": page_number,
                    "text": chunk_text_value,
                })
                chunk_id += 1

            if end == text_length:
                break

            start += step

    return {
        "filename": filename,
        "total_chunks": len(chunks),
        "chunks": chunks,
    }


@app.post("/embed-text")
async def embed_text(request: EmbedTextRequest):
    filename = request.filename

    if not filename.lower().endswith(SUPPORTED_EXTENSIONS):
        raise HTTPException(status_code=400, detail="Unsupported file type.")

    chunks, embedding_dimension = process_and_embed(filename, request.chunk_size, request.chunk_overlap)

    return {
        "filename": filename,
        "total_chunks": len(chunks),
        "embedding_dimension": embedding_dimension,
        "chunks": chunks,
    }


@app.post("/search")
async def search(request: SearchRequest):
    query = request.query
    top_k = request.top_k

    if not query or not query.strip():
        raise HTTPException(status_code=400, detail="query must not be empty.")

    if top_k <= 0:
        raise HTTPException(status_code=400, detail="top_k must be greater than 0.")

    results_data = retrieve_context(query, request.filenames, top_k)

    if not results_data:
        raise HTTPException(status_code=404, detail="No relevant documents found.")

    results = []
    for item in results_data:
        metadata = item["metadata"]
        results.append({
            "text": item["text"],
            "filename": metadata.get("filename"),
            "page_number": metadata.get("page_number"),
            "distance": item["distance"],
        })

    return {
        "query": query,
        "results": results,
    }


@app.post("/ask")
async def ask(request: AskRequest):
    query = request.query
    top_k = request.top_k

    if not query or not query.strip():
        raise HTTPException(status_code=400, detail="query must not be empty.")

    if top_k <= 0:
        raise HTTPException(status_code=400, detail="top_k must be greater than 0.")

    # Retrieve prior conversation turns for this conversation_id
    history = conversation_history.get(request.conversation_id, [])

    # If history exists, rewrite the query to be standalone
    search_query = query
    if history:
        history_text = "\n".join([f"User: {turn['question']}\nAssistant: {turn['answer']}" for turn in history])
        rewrite_prompt = (
            f"Given the following conversation history and a follow-up user question, "
            f"rewrite the follow-up question to be a standalone query that includes all "
            f"necessary context to retrieve relevant information from a document store. "
            f"Return ONLY the rewritten query.\n\n"
            f"History:\n{history_text}\n\n"
            f"Follow-up question: {query}\n\n"
            f"Rewritten query:"
        )
        try:
            rewrite_response = requests.post(
                OLLAMA_URL,
                json={"model": OLLAMA_MODEL, "prompt": rewrite_prompt, "stream": False},
                timeout=30,
            )
            if rewrite_response.status_code == 200:
                search_query = rewrite_response.json().get("response", query).strip()
        except Exception as e:
            print(f"Query rewrite failed, falling back to original query: {e}")

    # Build history text for the final answer generation
    if history:
        history_lines = ["Previous conversation:"]
        for turn in history:
            history_lines.append(f"User: {turn['question']}")
            history_lines.append(f"Assistant: {turn['answer']}")
        history_text = "\n".join(history_lines)
    else:
        history_text = ""

    results_data = retrieve_context(search_query, request.filenames, top_k)

    if not results_data:
        raise HTTPException(status_code=404, detail="No relevant documents found.")

    # Build a context string from the retrieved chunks
    context_parts = []
    sources = []
    seen_sources = set()
    for item in results_data:
        text = item["text"]
        metadata = item["metadata"]
        distance = item["distance"]

        source_filename = metadata.get("filename")
        source_page_number = metadata.get("page_number")
        source_chunk_index = metadata.get("chunk_index")

        source_id = f"{source_filename}_{source_page_number}_{source_chunk_index}"
        if source_id not in seen_sources:
            context_parts.append(
                f"Filename: {source_filename}\nPage: {source_page_number}\nContent: {text}"
            )
            sources.append({
                "filename": source_filename,
                "page_number": source_page_number,
                "chunk_index": source_chunk_index,
                "distance": distance,
                "text": text,
            })
            seen_sources.add(source_id)

    context = "\n\n---\n\n".join(context_parts)

    involved_filenames = sorted(set(s["filename"] for s in sources if s["filename"]))
    possible_conflict = len(involved_filenames) > 1

    conflict_instruction = (
        "The retrieved context comes from multiple different source documents. "
        "If these sources disagree or give conflicting information, explicitly "
        "point out the disagreement and mention which source says what. "
        if possible_conflict else ""
    )

    prompt = (
        "You are a professional document intelligence assistant. Using ONLY the "
        "retrieved document context below as your source of facts, write a clear, "
        "well-structured, professional answer. "
        "You are also given the previous conversation history. Use that history "
        "ONLY to understand references such as 'it', 'that sensor', or 'the "
        "previous experiment' - never as a source of facts. "
        "Do not use anything from the conversation history as a fact unless that "
        "same fact is also supported by the retrieved document context below. "
        "Do not invent or assume any information that is not present in the "
        "retrieved document context. If the retrieved context does not contain "
        "enough information to answer the question, explicitly say that the "
        "answer cannot be determined from the provided documents.\n\n"
        "Adapt your response structure naturally to best answer the question. "
        "MANDATORY ATTRIBUTION: Cite the source of every factual claim you make "
        "using ONLY the filename and page_number provided in the retrieved context below. "
        "Use brackets, e.g., [filename.pdf, Page: X]. "
        "Use strictly the provided page_number metadata; never infer, extract, or guess "
        "page numbers from section numbers, headings, chapter numbers, or any other "
        "text content. For TXT files, always cite the provided page_number. "
        "If a claim is not supported by the context, do not include it.\n\n"
        "Use a professional tone and avoid internal system terminology (e.g., retrieval, chunks, embeddings).\n"
        f"{conflict_instruction}\n\n"
        "Keep the overall answer concise and useful.\n\n"
        f"{history_text}\n\n"
        f"Retrieved document context:\n{context}\n\n"
        f"Current question: {query}\n\n"
        "Answer:"
    )

    try:
        ollama_response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
            },
            timeout=120,
        )
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to reach Ollama: {exc}")

    if ollama_response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Ollama returned status {ollama_response.status_code}: {ollama_response.text}",
        )

    ollama_data = ollama_response.json()
    answer = ollama_data.get("response")

    # Save this turn to conversation history only after a successful Ollama response
    conversation_history.setdefault(request.conversation_id, []).append({
        "question": query,
        "answer": answer,
    })
    conversation_history[request.conversation_id] = conversation_history[request.conversation_id][-10:]

    return {
        "query": query,
        "answer": answer,
        "sources": sources,
        "possible_conflict": possible_conflict,
        "involved_filenames": involved_filenames,
    }
