# DocuMind — Document Intelligence Platform

DocuMind is a local document intelligence application that helps users upload documents, ask questions about their contents, retrieve relevant information, and receive AI-generated answers with source references.

## Features

- **Multi-format uploads:** PDF, DOCX, TXT, and supported images.
- **Text extraction and OCR:** Extract text from documents, including scanned files and images.
- **Semantic search:** Retrieve relevant document chunks based on meaning rather than exact keyword matches.
- **Multi-document analysis:** Query multiple selected documents together.
- **AI-powered answers:** Generate responses using a locally running Llama 3 model through Ollama.
- **Evidence and source attribution:** Display document and page references alongside answers.
- **Conversational interface:** Ask follow-up questions through a chat-based frontend.
- **Local data storage:** Store document embeddings in a persistent ChromaDB collection.

## Architecture

```text
Document Upload
      |
      v
FastAPI Backend
      |
      v
Text Extraction / OCR
      |
      v
Chunking and Embeddings
      |
      v
ChromaDB Vector Store
      |
      v
Semantic Retrieval
      |
      v
Ollama + Llama 3
      |
      v
AI Answer + Source References
```

## Tech Stack

| Component | Technology |
|---|---|
| Frontend | HTML, CSS, JavaScript |
| Backend | Python, FastAPI |
| PDF Processing | PyMuPDF |
| DOCX Processing | python-docx |
| OCR | Tesseract OCR, Pillow |
| Embeddings | Sentence Transformers |
| Vector Database | ChromaDB |
| Language Model | Llama 3 through Ollama |

## Project Structure

```text
DocuMind/
├── backend/
│   ├── main.py
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── index.html
│   ├── css/
│   └── js/
├── .gitignore
└── README.md
```

## Prerequisites

- Python 3.11 or a compatible Python version
- Ollama installed and running
- The `llama3:latest` model available in Ollama
- Tesseract OCR installed and configured for OCR functionality

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/charukesh2621/DocuMind.git
cd DocuMind
```

### 2. Set up the Python environment

```bash
cd backend
python -m venv .venv
```

Activate the environment on Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install the dependencies:

```bash
pip install -r requirements.txt
```

### 3. Configure Ollama

Make sure Ollama is running and the required model is available:

```bash
ollama pull llama3:latest
```

Check the Ollama configuration in `backend/.env.example` and adjust local paths if needed. Keep credentials and machine-specific secrets out of version control.

### 4. Start the backend

From the `backend` directory:

```bash
uvicorn main:app --reload
```

The API should be available at:

`http://127.0.0.1:8000`

Interactive API documentation is available at:

`http://127.0.0.1:8000/docs`

### 5. Open the frontend

Open `frontend/index.html` in your browser. If your browser or configuration requires a local web server, serve the frontend directory locally instead.

## How It Works

1. Upload a supported document.
2. Extract text using document-processing tools or OCR.
3. Split the extracted text into chunks.
4. Generate embeddings and store them in ChromaDB.
5. Convert a user's question into an embedding.
6. Retrieve relevant chunks from the selected documents.
7. Pass the retrieved context to the local language model.
8. Display the generated answer with available source references.

## Privacy

DocuMind is designed to run locally using Ollama and a local vector database. Uploaded documents and stored embeddings remain on the local machine unless the user moves or shares them separately.

The application may still expose information if users upload sensitive documents to an external service or publish those files themselves. Review your data and configuration before sharing.

## Current Limitations

- Answer quality depends on document extraction, retrieval relevance, and the local language model.
- OCR accuracy depends on image quality and document layout.
- Source references depend on the metadata available during document processing.
- The local backend and Ollama model must be running for the application to answer questions.

## Future Improvements

- Progressive response streaming
- More robust evaluation of retrieval and answer quality
- Improved document management and export options
- Additional document formats and extraction strategies

## Author

**Charukesh Addugula**

GitHub: [@charukesh2621](https://github.com/charukesh2621)

---

Built as a document intelligence project exploring retrieval-augmented generation, semantic search, OCR, and locally hosted language models.
