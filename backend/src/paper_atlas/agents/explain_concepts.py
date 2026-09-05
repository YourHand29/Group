"""Evidence-grounded explanations for concepts extracted from a paper.

This module deliberately has no model-provider or LangGraph dependency. It
defines the contract that a future model-backed explanation node can satisfy.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..schemas import Concept, Evidence


class ConceptExplanation(BaseModel):
    """A user-facing explanation tied to evidence in the source paper."""

    concept_id: str = Field(min_length=1)
    term: str = Field(min_length=1)
    simple_explanation: str = Field(min_length=1)
    paper_context: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


_KIND_GUIDANCE = {
    "thesis": "This is the paper's main claim or proposed answer to its research question.",
    "method": "This is the approach or mechanism the authors use to address the research problem.",
    "finding": "This is an important result or implication reported by the paper.",
    "experiment": "This is how the authors test whether their approach works.",
    "metric": "This is a measurement used to judge the quality or effect of the approach.",
}


def _evidence_for(concept: Concept, evidence_by_id: dict[str, Evidence]) -> list[Evidence]:
    """Return evidence for a concept and reject dangling evidence references."""

    missing = [evidence_id for evidence_id in concept.evidence_ids if evidence_id not in evidence_by_id]
    if missing:
        missing_ids = ", ".join(missing)
        raise ValueError(f"Concept '{concept.id}' references unknown evidence: {missing_ids}")
    if not concept.evidence_ids:
        raise ValueError(f"Concept '{concept.id}' must reference at least one evidence item")
    return [evidence_by_id[evidence_id] for evidence_id in concept.evidence_ids]


def explain_concepts(concepts: list[Concept], evidence: list[Evidence]) -> list[ConceptExplanation]:
    """Create concise, evidence-grounded explanations for extracted concepts.

    The current implementation is deterministic so the contract can be used
    before a model provider is selected. A future LLM implementation should
    preserve the same output model and evidence validation rules.
    """

    evidence_by_id = {item.id: item for item in evidence}
    if len(evidence_by_id) != len(evidence):
        raise ValueError("Evidence IDs must be unique")

    explanations: list[ConceptExplanation] = []
    for concept in concepts:
        linked_evidence = _evidence_for(concept, evidence_by_id)
        evidence_summary = " ".join(item.claim for item in linked_evidence)
        guidance = _KIND_GUIDANCE[concept.kind]
        confidence = min([concept.confidence, *(item.confidence for item in linked_evidence)])

        explanations.append(
            ConceptExplanation(
                concept_id=concept.id,
                term=concept.label,
                simple_explanation=f"{concept.description} {guidance}",
                paper_context=evidence_summary,
                evidence_ids=list(concept.evidence_ids),
                confidence=confidence,
            )
        )

    return explanations
