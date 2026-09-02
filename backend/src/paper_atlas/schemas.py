from typing import Literal

from pydantic import BaseModel, Field, field_validator


SourceType = Literal["text", "url"]
ConceptKind = Literal["thesis", "method", "finding", "experiment", "metric"]
EvidenceKind = Literal["statistic", "experiment", "quote", "dataset", "context"]
RelationshipType = Literal["supports", "measures", "extends", "contradicts", "similar"]


class AnalysisRequest(BaseModel):
    source_type: SourceType
    source: str = Field(min_length=1, max_length=2_000_000)
    existing_papers: list["PaperRecord"] = Field(default_factory=list)
    query: str | None = Field(default=None, max_length=500)

    @field_validator("source")
    @classmethod
    def source_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source must contain text or a URL")
        return value.strip()


class DocumentChunk(BaseModel):
    id: str
    text: str = Field(min_length=1)
    index: int = Field(ge=0)
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)


class PaperRecord(BaseModel):
    id: str
    title: str
    abstract: str | None = None
    concepts: list[str] = Field(default_factory=list)


class PaperMetadata(BaseModel):
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = Field(default=None, ge=1000, le=2200)
    source_url: str | None = None


class Evidence(BaseModel):
    id: str
    claim: str = Field(min_length=1)
    kind: EvidenceKind
    excerpt: str = Field(min_length=1)
    source_location: str | None = None
    confidence: float = Field(ge=0, le=1)


class Concept(BaseModel):
    id: str
    label: str = Field(min_length=1)
    kind: ConceptKind
    description: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class Relationship(BaseModel):
    source_id: str
    target_id: str
    relationship_type: RelationshipType
    explanation: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    paper_ids: list[str] = Field(default_factory=list)


class PaperAnalysis(BaseModel):
    metadata: PaperMetadata
    thesis: str = Field(min_length=1)
    plain_language_summary: str = Field(min_length=1)
    relevance: int = Field(ge=0, le=100)
    concepts: list[Concept] = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)


class AnalysisResponse(BaseModel):
    run_id: str
    status: Literal["completed", "failed"]
    paper: PaperMetadata | None = None
    thesis: str = ""
    summary: str = ""
    relevance: int = Field(default=0, ge=0, le=100)
    concepts: list[Concept] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)
    usage: dict[str, int] = Field(default_factory=dict)
    query: str | None = None
    query_matches: list[str] = Field(default_factory=list)
