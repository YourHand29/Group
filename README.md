# Paper Atlas

Paper Atlas is a visual research workspace for quickly deciding whether a research paper is relevant enough to read deeply. A user submits a paper link, abstract, or text file. The system extracts the paper's central thesis, methods, findings, experiments, and evidence, then presents those relationships as a concept map. When multiple papers are present, the system highlights similar, supporting, extending, or conflicting ideas.

## Problem statement

Researchers and students screening a new literature area need a faster way to understand a paper's central claim, supporting evidence, and relationship to existing work because reading full papers sequentially makes early-stage literature triage slow and difficult to compare.

## Proposed solution

Paper Atlas uses a Python agentic workflow to turn unstructured research documents into evidence-backed, comparable structures:

1. Ingest a paper from text or an HTTP(S) URL.
2. Extract bounded text chunks for focused processing.
3. Identify the thesis, methods, findings, experiments, metrics, and supporting evidence.
4. Validate the structured result and retry a bounded number of times if it is invalid.
5. Produce a concise summary and relevance signal.
6. Compare the paper with existing papers and create relationship edges.
7. Return typed JSON to the web interface for deterministic graph rendering.

The agentic element is the controlled workflow: it maintains shared state, uses document tools, validates intermediate output, retries failures, and adapts its comparison step based on the papers already in the workspace. The graph renderer itself is deterministic frontend code, not another autonomous agent.

## Current repository structure

```text
Group/
├─ README.md
├─ site/                         # React/Vinext frontend
│  ├─ app/page.tsx               # Paper Atlas workspace UI
│  ├─ app/globals.css            # Visual system and responsive layout
│  ├─ app/layout.tsx             # Metadata and root layout
│  └─ lib/                       # Existing frontend demo data
└─ backend/                      # Python workflow backbone
   ├─ pyproject.toml             # Python dependencies and scripts
   ├─ .env.example               # Runtime configuration template
   ├─ src/paper_atlas/
   │  ├─ api.py                  # FastAPI /health and /analyze endpoints
   │  ├─ config.py               # Environment-backed settings
   │  ├─ graph.py                # LangGraph workflow and response adapter
   │  ├─ model.py                # Model provider boundary and demo model
   │  ├─ nodes.py                # Workflow node functions and routing
   │  ├─ schemas.py              # Pydantic request, state payload, and output models
   │  ├─ state.py                # Shared LangGraph state definition
   │  └─ tools/documents.py      # URL/text/PDF ingestion and chunking
   └─ tests/test_graph.py        # Backbone smoke tests
```

## Architecture

```text
site/ frontend
   │ POST /analyze
   ▼
FastAPI API
   ▼
LangGraph stateful workflow
   ├─ validate_input
   ├─ ingest_document
   ├─ extract_structure
   ├─ validate_output ── retry (bounded)
   ├─ summarise_paper
   └─ compare_papers
   ▼
Validated AnalysisResponse JSON
```

The backbone deliberately starts with an explicit graph rather than a free-form supervisor. LangGraph gives us typed state, node boundaries, conditional routing, bounded loops, and a future path to streaming and persistence. The model is isolated behind `ResearchModel`, so the deterministic demo implementation can later be replaced with a real provider without rewriting the workflow.

## Local setup

The frontend currently runs independently:

```powershell
cd site
npm install
npm run dev
```

The Python backend uses Python 3.11 or newer. With standard Python tooling:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
paper-atlas-api
```

The backend listens on `http://localhost:8080`.

Check it:

```powershell
Invoke-WebRequest http://localhost:8080/health
```

Run the workflow tests:

```powershell
pytest
```

Example request:

```powershell
$body = @{ source_type = "text"; source = "This paper proposes a method and evaluates it on a benchmark." } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8080/analyze -ContentType "application/json" -Body $body
```

For a local PDF, TXT, or Markdown file, use the multipart endpoint. The web UI uses this endpoint automatically when a file is selected:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8080/analyze-file -Form @{ file = Get-Item ".\paper.pdf"; existing_papers = "[]" }
```

## What is intentionally not finished yet

- The model provider is still a deterministic demo model; no API key is required. The frontend now calls the Python `/analyze` endpoint, so URL/text submissions execute the backend graph.
- File uploads now use a multipart `/analyze-file` endpoint for PDF, TXT, and Markdown files. This path works without internet access.
- Scanned/image-only PDFs still need OCR; text-based PDFs are supported by `pypdf`.
- Similarity currently uses simple token overlap; embeddings should come later.
- Analysis runs are not persisted yet.
- Streaming progress, citations in the UI, and human review are future steps.

## Next implementation order

1. Connect the frontend input to `POST /analyze`.
2. Replace `DemoResearchModel` with one provider-backed implementation.
3. Add source-location-aware extraction and citation display.
4. Add real `.txt`, `.md`, and PDF upload handling.
5. Add a two-paper comparison fixture and improve relationships.
6. Add embeddings only after the concept and relationship schema is stable.
7. Add persistence/checkpointing and streaming progress.
8. Measure schema pass rate, citation coverage, relevance agreement, latency, retries, and token cost.
