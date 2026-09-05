from paper_atlas.agents import explain_concepts
from paper_atlas.schemas import Concept, Evidence


def test_explains_supported_and_unsupported_concepts():
    concepts = [
        Concept(
            id="method",
            label="Attention mechanism",
            kind="method",
            description="A mechanism for weighting relevant parts of an input.",
            evidence_ids=["evidence-method"],
            confidence=0.9,
        ),
        Concept(
            id="background-concept",
            label="Positional encoding",
            kind="method",
            description="A way to represent token order.",
            evidence_ids=[],
            confidence=0.7,
        ),
    ]
    evidence = [
        Evidence(
            id="evidence-method",
            claim="The method weights relevant parts of the input.",
            kind="experiment",
            excerpt="The model assigns higher weights to relevant input elements.",
            source_location="Methods, page 3",
            confidence=0.85,
        )
    ]

    results = explain_concepts(concepts, evidence)

    assert len(results) == 2
    assert results[0].support_status == "direct"
    assert results[0].definition == concepts[0].description
    assert results[0].supporting_evidence[0].evidence_id == "evidence-method"
    assert results[0].reliability.label == "high"
    assert results[1].support_status == "unsupported"
    assert results[1].supporting_evidence == []
    assert results[1].reliability.label == "low"
    assert "verify" in results[1].reliability.limitations[0].lower()
