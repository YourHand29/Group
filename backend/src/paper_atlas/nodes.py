from __future__ import annotations

from urllib.parse import urlparse

from .agents import explain_concepts, named_entity_model_available
from .config import Settings
from .model import ResearchModel, default_model as configured_default_model, search_text
from .schemas import PaperAnalysis
from .state import ResearchState
from .tools.documents import DocumentIngestionError, chunk_text, load_document_details


def _normalise_for_match(value: str) -> str:
    """Make excerpts comparable despite PDF line wrapping and whitespace."""

    return " ".join(value.casefold().replace("…", "").split())


def _evidence_is_anchored(excerpt: str, source_text: str) -> bool:
    source = _normalise_for_match(source_text)
    candidate = _normalise_for_match(excerpt)
    if not candidate:
        return False
    if candidate in source:
        return True
    # Long excerpts are deliberately shortened for the UI. Their retained
    # prefix remains a valid citation anchor even when the ellipsis is absent
    # from the source text.
    prefix = candidate[:180].rsplit(" ", 1)[0].strip()
    return len(prefix) >= 40 and prefix in source


def validate_input(state: ResearchState) -> dict:
    source = state.get("source", "").strip()
    source_type = state.get("source_type", "")
    if not source:
        return {"errors": ["source must not be empty"], "status": "failed", "trace": ["Input rejected"]}
    if source_type == "url":
        parsed = urlparse(source)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return {"errors": ["source must be a valid http(s) URL"], "status": "failed", "trace": ["Input rejected"]}
    return {"errors": [], "status": "validated", "trace": ["Input validated"]}


def ingest_document(state: ResearchState, settings: Settings) -> dict:
    try:
        document = load_document_details(
            state["source_type"],
            state["source"],
            settings.max_document_chars,
        )
        chunks = chunk_text(document.text, settings.max_chunk_chars)
        trace = [f"Document read as {document.format} into {len(chunks)} paper-text chunk(s)"]
        if document.format == "pdf" and state["source_type"] == "url":
            trace.append("Preferred the linked PDF for analysis")
        if document.format == "html":
            trace.append("No usable linked PDF was found; used the paper-content portion of the page")
        if document.ocr_used:
            trace.append("Used OCR for image-only or low-text PDF pages")
        return {
            "raw_text": document.text,
            "source_url": document.source_url,
            "chunks": chunks,
            "document_format": document.format,
            "ocr_used": document.ocr_used,
            "status": "ingested",
            "trace": trace,
            "warnings": list(document.warnings),
            "errors": [],
        }
    except DocumentIngestionError as exc:
        return {"errors": [str(exc)], "status": "failed", "trace": ["Document ingestion failed"]}


def extract_structure(state: ResearchState, model: ResearchModel) -> dict:
    analysis = model.extract(state["raw_text"], state.get("source_url"), state.get("query"))
    warnings = [] if named_entity_model_available() else [
        "Named-entity concepts were unavailable; install spaCy's en_core_web_sm model."
    ]
    return {
        "paper": analysis,
        "thesis": analysis.thesis,
        "concepts": analysis.concepts,
        "evidence": analysis.evidence,
        "query_matches": search_text(state["raw_text"], state.get("query")),
        "status": "structured",
        "trace": [f"Extracted {len(analysis.concepts)} concepts and {len(analysis.evidence)} evidence items"],
        "warnings": warnings,
        "errors": [],
    }


def validate_output(state: ResearchState) -> dict:
    try:
        analysis = PaperAnalysis.model_validate(state["paper"])
        evidence_ids = {item.id for item in analysis.evidence}
        concept_ids = {concept.id for concept in analysis.concepts}
        if len(evidence_ids) != len(analysis.evidence):
            raise ValueError("evidence IDs must be unique")
        if len(concept_ids) != len(analysis.concepts):
            raise ValueError("concept IDs must be unique")
        missing = sorted({evidence_id for concept in analysis.concepts for evidence_id in concept.evidence_ids if evidence_id not in evidence_ids})
        if missing:
            raise ValueError(f"concepts reference missing evidence: {', '.join(missing)}")
        unlinked = sorted(concept.id for concept in analysis.concepts if not concept.evidence_ids)
        if unlinked:
            raise ValueError(f"concepts without evidence: {', '.join(unlinked)}")
        unanchored = sorted(
            item.id
            for item in analysis.evidence
            if not _evidence_is_anchored(item.excerpt, state.get("raw_text", ""))
        )
        if unanchored:
            raise ValueError(f"evidence excerpts not found in the ingested paper text: {', '.join(unanchored)}")
        return {"errors": [], "status": "validated", "trace": ["Structured output passed validation"]}
    except (KeyError, ValueError, TypeError) as exc:
        retry_count = state.get("retry_count", 0) + 1
        return {
            "errors": [f"Structured output validation failed: {exc}"],
            "retry_count": retry_count,
            "status": "retrying" if retry_count <= state.get("max_retries", 0) else "failed",
            "trace": [f"Validation failed; retry {retry_count}"],
        }


def explain_concept_nodes(state: ResearchState) -> dict:
    """Turn extracted concepts into evidence-grounded UI explanations."""

    explanations = explain_concepts(state["concepts"], state["evidence"])
    return {
        "concept_explanations": [explanation.model_dump() for explanation in explanations],
        "status": "explained",
        "trace": [f"Generated {len(explanations)} evidence-grounded concept explanations"],
    }


def summarise_paper(state: ResearchState, model: ResearchModel) -> dict:
    summary, relevance = model.summarise(state["paper"])
    return {"summary": summary, "relevance": relevance, "status": "summarised", "trace": ["Summary and relevance signal generated"]}


def compare_papers(state: ResearchState, model: ResearchModel) -> dict:
    relationships = model.compare(state["paper"], state.get("existing_papers", []))
    return {"relationships": relationships, "status": "completed", "trace": [f"Compared against {len(state.get('existing_papers', []))} existing paper(s)"]}


def fail_workflow(state: ResearchState) -> dict:
    return {"status": "failed", "trace": ["Workflow stopped after bounded retries or an ingestion error"]}


def route_after_input(state: ResearchState) -> str:
    return "fail" if state.get("errors") else "ingest_document"


def route_after_ingestion(state: ResearchState) -> str:
    return "fail" if state.get("errors") else "extract_structure"


def route_after_validation(state: ResearchState) -> str:
    if not state.get("errors"):
        return "explain_concepts"
    if state.get("retry_count", 0) <= state.get("max_retries", 0):
        return "extract_structure"
    return "fail"


def default_model(settings: Settings | None = None) -> ResearchModel:
    return configured_default_model(settings)
