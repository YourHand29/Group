"""Evidence-grounded explanations for concepts extracted from a paper.

This module deliberately has no model-provider or LangGraph dependency. It
defines the contract that a future model-backed explanation node can satisfy.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..schemas import Concept, ConceptKind, Evidence


class ConceptExplanation(BaseModel):
    """A user-facing scientific concept explanation tied to source evidence."""

    concept_id: str = Field(min_length=1)
    term: str = Field(min_length=1)
    kind: ConceptKind
    definition: str = Field(min_length=1)
    use_in_paper: str = Field(min_length=1)
    supporting_evidence: list["EvidenceSupport"] = Field(default_factory=list)
    support_status: Literal["direct", "contextual", "partial", "unsupported"]
    reliability: "ReliabilityAssessment"

    # These fields preserve the original lightweight contract for callers that
    # only need a short explanation and evidence IDs.
    simple_explanation: str = Field(min_length=1)
    paper_context: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class EvidenceSupport(BaseModel):
    """A source item used to support a concept explanation."""

    evidence_id: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    excerpt: str = Field(min_length=1)
    source_location: str | None = None
    confidence: float = Field(ge=0, le=1)


class ReliabilityAssessment(BaseModel):
    """Assessment of evidential support, not a claim of scientific truth."""

    score: float = Field(ge=0, le=1)
    label: Literal["high", "moderate", "low"]
    rationale: str = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)


ConceptExplanation.model_rebuild()


_KIND_GUIDANCE = {
    "thesis": "This is the paper's main claim or proposed answer to its research question.",
    "method": "This is the approach or mechanism the authors use to address the research problem.",
    "finding": "This is an important result or implication reported by the paper.",
    "experiment": "This is how the authors test whether their approach works.",
    "metric": "This is a measurement used to judge the quality or effect of the approach.",
}

_KIND_USAGE = {
    "thesis": "The paper uses this as its central claim or proposed answer.",
    "method": "The paper uses this as its approach for addressing the research problem.",
    "finding": "The paper uses this to report or interpret an observed result.",
    "experiment": "The paper uses this as part of the procedure for evaluating its proposal.",
    "metric": "The paper uses this measurement to assess the quality or effect of its approach.",
}


def _evidence_for(concept: Concept, evidence_by_id: dict[str, Evidence]) -> list[Evidence]:
    """Return evidence for a concept and reject dangling evidence references."""

    missing = [evidence_id for evidence_id in concept.evidence_ids if evidence_id not in evidence_by_id]
    if missing:
        missing_ids = ", ".join(missing)
        raise ValueError(f"Concept '{concept.id}' references unknown evidence: {missing_ids}")
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
        evidence_summary = (
            " ".join(item.claim for item in linked_evidence)
            if linked_evidence
            else "No supporting evidence was extracted for this concept."
        )
        guidance = _KIND_GUIDANCE[concept.kind]
        use_in_paper = _KIND_USAGE[concept.kind]
        confidence = min([concept.confidence, *(item.confidence for item in linked_evidence)]) if linked_evidence else 0.0
        evidence_kinds = {item.kind for item in linked_evidence}
        direct_kinds = {"statistic", "experiment", "dataset"}
        if not linked_evidence:
            support_status = "unsupported"
        elif evidence_kinds & direct_kinds and evidence_kinds - direct_kinds:
            support_status = "partial"
        elif evidence_kinds & direct_kinds:
            support_status = "direct"
        else:
            support_status = "contextual"
        if confidence >= 0.8:
            reliability_label = "high"
        elif confidence >= 0.6:
            reliability_label = "moderate"
        else:
            reliability_label = "low"

        source_note = (
            "Source locations are recorded for the linked evidence."
            if linked_evidence and all(item.source_location for item in linked_evidence)
            else "One or more linked evidence items lack a precise source location."
        )

        explanations.append(
            ConceptExplanation(
                concept_id=concept.id,
                term=concept.label,
                kind=concept.kind,
                definition=concept.description,
                use_in_paper=use_in_paper,
                supporting_evidence=[
                    EvidenceSupport(
                        evidence_id=item.id,
                        claim=item.claim,
                        excerpt=item.excerpt,
                        source_location=item.source_location,
                        confidence=item.confidence,
                    )
                    for item in linked_evidence
                ],
                support_status=support_status,
                reliability=ReliabilityAssessment(
                    score=confidence,
                    label=reliability_label,
                    rationale=(
                        f"The explanation has {support_status} support from {len(linked_evidence)} linked evidence item(s) "
                        f"with a limiting confidence of {confidence:.0%}."
                    ),
                    limitations=(
                        ["No evidence was linked; verify this concept against the paper or cited literature.", "This assesses evidence support, not whether the paper's claim is universally true."]
                        if not linked_evidence
                        else [source_note, "This assesses evidence support, not whether the paper's claim is universally true."]
                    ),
                ),
                simple_explanation=f"{concept.description} {guidance}",
                paper_context=evidence_summary,
                evidence_ids=list(concept.evidence_ids),
                confidence=confidence,
            )
        )

    return explanations
