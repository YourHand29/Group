from __future__ import annotations

import json

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .graph import run_analysis
from .schemas import AnalysisRequest, AnalysisResponse, PaperRecord
from .tools.documents import DocumentIngestionError, extract_uploaded_file_details

settings = get_settings()
app = FastAPI(title="Paper Atlas Agent API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "model_mode": settings.model_mode}


@app.post("/analyze", response_model=AnalysisResponse)
def analyze(request: AnalysisRequest) -> AnalysisResponse:
    try:
        response = run_analysis(request)
    except Exception as exc:  # keep API failures actionable for the frontend
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if response.status == "failed":
        raise HTTPException(status_code=422, detail=response.warnings or "Analysis failed")
    return response


@app.post("/analyze-file", response_model=AnalysisResponse)
async def analyze_file(
    file: UploadFile = File(...),
    existing_papers: str = Form("[]"),
    instruction: str = Form(""),
) -> AnalysisResponse:
    """Analyze a local PDF/TXT/Markdown upload without fetching a URL."""
    try:
        papers = [PaperRecord.model_validate(item) for item in json.loads(existing_papers)]
        content = await file.read()
        document = extract_uploaded_file_details(
            file.filename or "upload",
            file.content_type or "application/octet-stream",
            content,
            settings.max_document_chars,
        )
        response = run_analysis(AnalysisRequest(source_type="text", source=document.text, existing_papers=papers, query=instruction.strip() or None))
        response.document_format = document.format
        response.ocr_used = document.ocr_used
        # DocumentRead stores immutable warnings as a tuple, while the API
        # schema exposes warnings as a list. Normalize before combining them.
        response.warnings = list(document.warnings) + response.warnings
    except (json.JSONDecodeError, TypeError, ValueError, DocumentIngestionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if response.status == "failed":
        raise HTTPException(status_code=422, detail=response.warnings or "Analysis failed")
    return response


def run() -> None:
    uvicorn.run("paper_atlas.api:app", host="0.0.0.0", port=8080, reload=True)


if __name__ == "__main__":
    run()
