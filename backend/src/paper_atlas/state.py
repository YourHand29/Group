import operator
from typing import Annotated, TypedDict

from .schemas import Concept, DocumentChunk, Evidence, PaperRecord, PaperAnalysis, Relationship


class ResearchState(TypedDict, total=False):
    """Shared state passed between the backbone workflow nodes."""

    run_id: str
    source_type: str
    source: str
    query: str | None
    source_url: str | None
    raw_text: str
    chunks: list[DocumentChunk]
    paper: PaperAnalysis
    concepts: list[Concept]
    evidence: list[Evidence]
    concept_explanations: list[dict[str, object]]
    query_matches: list[str]
    relationships: list[Relationship]
    thesis: str
    summary: str
    relevance: int
    existing_papers: list[PaperRecord]
    errors: list[str]
    warnings: list[str]
    retry_count: int
    max_retries: int
    status: str
    trace: Annotated[list[str], operator.add]
