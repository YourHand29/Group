from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
import re
from typing import Protocol

from .agents import (
    ScannedDocument,
    explain_concepts,
    extract_named_concepts,
    scan_text_document,
)
from .schemas import PaperAnalysis, PaperRecord, Relationship


class ResearchModel(Protocol):
    """Provider boundary that adapts scanned documents for model agents."""

    def extract(self, text: str, source_url: str | None = None, query: str | None = None) -> PaperAnalysis:
        scanned_documents = self.scan_documents(text)
        return self.extract_scanned_documents(scanned_documents, source_url, query)

    @staticmethod
    def scan_documents(text: str) -> list[ScannedDocument]:
        """Create document records for text that has already passed ingestion."""
        return [scan_text_document(text)] if text.strip() else []

    @staticmethod
    def scanned_documents_to_text(documents: list[ScannedDocument]) -> str:
        """Adapt scanned paragraphs to the string input expected by recognition."""
        return "\n\n".join(
            paragraph.text
            for document in documents
            for paragraph in document.paragraphs
        )

    @staticmethod
    def recognize_scanned_documents(documents: list[ScannedDocument]):
        """Run the unchanged recognition agent against normalized paragraph text."""
        return extract_named_concepts(ResearchModel.scanned_documents_to_text(documents))

    @staticmethod
    def explain_analysis(analysis: PaperAnalysis):
        """Run the unchanged explanation agent after concepts and evidence exist."""
        return explain_concepts(analysis.concepts, analysis.evidence)

    @abstractmethod
    def extract_scanned_documents(
        self,
        scanned_documents: list[ScannedDocument],
        source_url: str | None = None,
        query: str | None = None,
    ) -> PaperAnalysis:
        """Produce an analysis from normalized scanned documents."""
        ...

    def summarise(self, analysis: PaperAnalysis) -> tuple[str, int]:
        ...

    def compare(self, analysis: PaperAnalysis, existing_papers: list[PaperRecord]) -> list[Relationship]:
        ...


def _first_line(text: str) -> str:
    for line in text.splitlines():
        candidate = line.strip(" #\t")
        if 4 <= len(candidate) <= 140:
            return candidate
    return "Imported research paper"


def search_text(text: str, query: str | None) -> list[str]:
    """Find short excerpts containing a user-requested concept or phrase."""
    if not query or not query.strip():
        return []
    clean_query = query.strip()
    lower_text = text.lower()
    terms = re.findall(r"[a-z0-9][a-z0-9-]{2,}", clean_query.lower())
    positions: list[int] = []
    phrase_position = lower_text.find(clean_query.lower())
    if phrase_position >= 0:
        positions.append(phrase_position)
    for term in terms:
        position = lower_text.find(term)
        if position >= 0:
            positions.append(position)
    matches: list[str] = []
    for position in positions:
        excerpt = " ".join(text[max(0, position - 120): position + 240].split())
        if excerpt and excerpt not in matches:
            matches.append(excerpt)
    return matches[:3]


class DemoResearchModel(ResearchModel):
    """Deterministic stand-in that keeps the workflow runnable without an API key."""

    def extract_scanned_documents(
        self,
        scanned_documents: list[ScannedDocument],
        source_url: str | None = None,
        query: str | None = None,
    ) -> PaperAnalysis:
        text = self.scanned_documents_to_text(scanned_documents)
        lower_text = text.lower()
        title = _first_line(text)
        year_match = re.search(r"\b(19|20)\d{2}\b", text)
        year = int(year_match.group(0)) if year_match else None
        query_matches = search_text(text, query)

        if any(term in lower_text for term in ("attention", "transformer", "sequence")):
            thesis = "The paper argues that attention-based representations make long-range relationships easier to model in parallel."
            method = "Attention-based representation"
            finding = "Parallel context mixing"
            experiment = "Benchmark comparison"
            metric = "Reported quality improvement"
        else:
            thesis = "The paper proposes a focused method and evaluates it against measurable outcomes."
            method = "Proposed method"
            finding = "Primary finding"
            experiment = "Experimental evaluation"
            metric = "Reported result"

        evidence = [
            {"id": "evidence-1", "claim": "The paper establishes a central research question.", "kind": "context", "excerpt": text[: min(420, len(text))], "source_location": "opening text", "confidence": 0.82},
            {"id": "evidence-2", "claim": "The paper describes a method for addressing the question.", "kind": "experiment", "excerpt": text[: min(420, len(text))], "source_location": "extracted text", "confidence": 0.74},
            {"id": "evidence-3", "claim": "The paper reports an outcome that can be compared.", "kind": "statistic", "excerpt": text[: min(420, len(text))], "source_location": "extracted text", "confidence": 0.68},
        ]
        if query_matches:
            evidence.append({"id": "evidence-query", "claim": f"The requested concept '{query.strip()}' appears in the extracted paper text.", "kind": "quote", "excerpt": query_matches[0], "source_location": "query match", "confidence": 0.9})
            finding = f"Query match: {query.strip()[:32]}"
        concepts = [
            {"id": "thesis", "label": title[:48], "kind": "thesis", "description": thesis, "evidence_ids": ["evidence-1"], "confidence": 0.82, "recognition_status": "structural"},
            {"id": "method", "label": method, "kind": "method", "description": "The central mechanism or approach used by the authors.", "evidence_ids": ["evidence-2"], "confidence": 0.76, "recognition_status": "structural"},
            {"id": "finding", "label": finding, "kind": "finding", "description": "The main implication reported by the study.", "evidence_ids": ["evidence-3"], "confidence": 0.71, "recognition_status": "structural"},
            {"id": "experiment", "label": experiment, "kind": "experiment", "description": "The evaluation setup used to test the proposal.", "evidence_ids": ["evidence-2"], "confidence": 0.68, "recognition_status": "structural"},
            {"id": "metric", "label": metric, "kind": "metric", "description": "The result signal to inspect before reading deeply.", "evidence_ids": ["evidence-3"], "confidence": 0.64, "recognition_status": "structural"},
        ]

        # Keep the stable structural concepts above for the map, then append
        # paper-specific entities recognized by spaCy's NER pipeline.
        for index, entity in enumerate(self.recognize_scanned_documents(scanned_documents), start=1):
            evidence_id = f"evidence-entity-{index}"
            evidence.append({
                "id": evidence_id,
                "claim": f"The paper mentions {entity.term}.",
                "kind": "quote",
                "excerpt": entity.excerpt,
                "source_location": f"character {entity.start_char}",
                "confidence": 0.72,
            })
            concepts.append({
                "id": f"entity-{index}",
                "label": entity.term,
                "kind": "concept",
                "description": (
                    f"{entity.concept_type.title()} documented as {entity.term}. "
                    f"{entity.knowledge_description} "
                    f"Recognized in the paper as a {entity.entity_type.lower()} mention "
                    f"({entity.mentions} occurrence(s))."
                ),
                "evidence_ids": [evidence_id],
                "confidence": entity.confidence,
                "concept_type": entity.concept_type,
                "wikipedia_url": entity.wikipedia_url,
                "wikidata_id": entity.wikidata_id,
                "source_urls": list(entity.source_urls),
                "recognition_status": entity.recognition_status,
            })

        return PaperAnalysis(
            metadata={"title": title, "authors": ["Imported document"], "year": year, "source_url": source_url},
            thesis=thesis,
            plain_language_summary=(
                f"The requested concept '{query.strip()}' was found in the extracted text. The document has also been reduced into a thesis, method, finding, experiment, and result signal."
                if query_matches and query else
                "The document has been reduced into a thesis, method, finding, experiment, and result signal."
            ),
            relevance=80 if query_matches else 70,
            concepts=concepts,
            evidence=evidence,
        )

    def summarise(self, analysis: PaperAnalysis) -> tuple[str, int]:
        summary = f"{analysis.thesis} The strongest next check is the evidence behind {analysis.concepts[2].label.lower()}."
        return summary, analysis.relevance

    def compare(self, analysis: PaperAnalysis, existing_papers: list[PaperRecord]) -> list[Relationship]:
        current_terms = set(re.findall(r"[a-z]{4,}", " ".join([analysis.metadata.title, analysis.thesis, *(concept.label for concept in analysis.concepts)]).lower()))
        relationships: list[Relationship] = []
        for paper in existing_papers:
            other_terms = set(re.findall(r"[a-z]{4,}", " ".join([paper.title, paper.abstract or "", *paper.concepts]).lower()))
            overlap = current_terms & other_terms
            if overlap:
                confidence = min(0.95, 0.5 + len(overlap) * 0.08)
                relationships.append(Relationship(
                    source_id="current-paper",
                    target_id=paper.id,
                    relationship_type="similar",
                    explanation=f"Shared concepts: {', '.join(sorted(overlap)[:5])}.",
                    confidence=confidence,
                    paper_ids=[paper.id],
                ))
        return relationships
