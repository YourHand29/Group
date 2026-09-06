from __future__ import annotations

from datetime import datetime, timezone
import time
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from .config import Settings, get_settings
from .model import ResearchModel
from .nodes import (
    compare_papers,
    default_model,
    extract_structure,
    explain_concept_nodes,
    fail_workflow,
    ingest_document,
    route_after_ingestion,
    route_after_input,
    route_after_validation,
    summarise_paper,
    validate_input,
    validate_output,
)
from .schemas import AnalysisRequest, AnalysisResponse
from .state import ResearchState
from .store import safe_save_path


def build_graph(model: ResearchModel | None = None, settings: Settings | None = None):
    settings = settings or get_settings()
    model = model or default_model(settings)

    builder = StateGraph(ResearchState)
    builder.add_node("validate_input", validate_input)
    builder.add_node("ingest_document", lambda state: ingest_document(state, settings))
    builder.add_node("extract_structure", lambda state: extract_structure(state, model))
    builder.add_node("validate_output", validate_output)
    builder.add_node("explain_concepts", explain_concept_nodes)
    builder.add_node("summarise_paper", lambda state: summarise_paper(state, model))
    builder.add_node("compare_papers", lambda state: compare_papers(state, model))
    builder.add_node("fail", fail_workflow)

    builder.add_edge(START, "validate_input")
    builder.add_conditional_edges("validate_input", route_after_input)
    builder.add_conditional_edges("ingest_document", route_after_ingestion)
    builder.add_edge("extract_structure", "validate_output")
    builder.add_conditional_edges("validate_output", route_after_validation)
    builder.add_edge("explain_concepts", "summarise_paper")
    builder.add_edge("summarise_paper", "compare_papers")
    builder.add_edge("compare_papers", END)
    builder.add_edge("fail", END)
    return builder.compile()


def initial_state(request: AnalysisRequest, settings: Settings) -> ResearchState:
    return ResearchState(
        run_id=str(uuid4()),
        source_type=request.source_type,
        source=request.source,
        query=request.query,
        source_url=None,
        chunks=[],
        existing_papers=request.existing_papers,
        errors=[],
        warnings=[],
        retry_count=0,
        max_retries=settings.max_retries,
        status="queued",
        trace=[f"Run created at {datetime.now(timezone.utc).isoformat()}"],
    )


def response_from_state(state: ResearchState) -> AnalysisResponse:
    analysis = state.get("paper")
    if not analysis:
        return AnalysisResponse(
            run_id=state["run_id"],
            status="failed",
            document_format=state.get("document_format"),
            ocr_used=state.get("ocr_used", False),
            warnings=state.get("warnings", []) + state.get("errors", []),
            trace=state.get("trace", []),
            usage={
                "input_characters": len(state.get("raw_text", "")),
                "chunk_count": len(state.get("chunks", [])),
                "retries": state.get("retry_count", 0),
            },
        )
    concepts = state.get("concepts", analysis.concepts)
    evidence = state.get("evidence", analysis.evidence)
    quality = {
        "schema_valid": 1.0,
        "citation_coverage": sum(bool(concept.evidence_ids) for concept in concepts) / max(1, len(concepts)),
        "evidence_location_coverage": sum(bool(item.source_location) for item in evidence) / max(1, len(evidence)),
        "retry_count": float(state.get("retry_count", 0)),
    }
    return AnalysisResponse(
        run_id=state["run_id"],
        status="completed" if state.get("status") == "completed" else "failed",
        paper=analysis.metadata,
        document_format=state.get("document_format"),
        ocr_used=state.get("ocr_used", False),
        thesis=state.get("thesis", analysis.thesis),
        summary=state.get("summary", analysis.plain_language_summary),
        relevance=state.get("relevance", analysis.relevance),
        concepts=concepts,
        concept_explanations=state.get("concept_explanations", []),
        evidence=evidence,
        relationships=state.get("relationships", []),
        warnings=state.get("warnings", []) + state.get("errors", []),
        trace=state.get("trace", []),
        usage={},
        quality=quality,
        query=state.get("query"),
        query_matches=state.get("query_matches", []),
    )


def run_analysis(request: AnalysisRequest) -> AnalysisResponse:
    started = time.perf_counter()
    settings = get_settings()
    graph = build_graph(settings=settings)
    result = graph.invoke(initial_state(request, settings), {"recursion_limit": 20})
    response = response_from_state(result)
    response.quality["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
    response.usage.update({
        "input_characters": len(result.get("raw_text", "")),
        "chunk_count": len(result.get("chunks", [])),
        "retries": result.get("retry_count", 0),
    })
    persistence_warning = safe_save_path(settings.run_store_path, response)
    if persistence_warning:
        response.warnings.append(persistence_warning)
    return response


def stream_analysis(request: AnalysisRequest):
    """Yield workflow updates suitable for an SSE or websocket adapter."""

    started = time.perf_counter()
    settings = get_settings()
    graph = build_graph(settings=settings)
    state = initial_state(request, settings)
    yield {"event": "progress", "node": "queued", "status": state["status"], "trace": state["trace"]}
    for update in graph.stream(state, {"recursion_limit": 20}, stream_mode="updates"):
        for node, values in update.items():
            if not isinstance(values, dict):
                continue
            for key, value in values.items():
                if key == "trace":
                    state[key] = [*state.get(key, []), *value] if isinstance(value, list) else state.get(key, [])
                else:
                    state[key] = value
            yield {
                "event": "progress",
                "node": node,
                "status": state.get("status", "running"),
                "trace": values.get("trace", []),
            }
    response = response_from_state(state)
    response.quality["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
    response.usage.update({
        "input_characters": len(state.get("raw_text", "")),
        "chunk_count": len(state.get("chunks", [])),
        "retries": state.get("retry_count", 0),
    })
    persistence_warning = safe_save_path(settings.run_store_path, response)
    if persistence_warning:
        response.warnings.append(persistence_warning)
    yield {"event": "complete", "status": response.status, "response": response.model_dump(mode="json")}
