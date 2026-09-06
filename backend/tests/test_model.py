from paper_atlas.model import DemoResearchModel


def test_demo_model_grounds_structural_signals_in_the_submitted_paper(monkeypatch) -> None:
    monkeypatch.setattr("paper_atlas.model.extract_named_concepts", lambda text: [])
    text = """Quantum spin resonance in engineered proteins for multimodal sensing
Abstract
We present a quantum spin resonance method for sensing molecular interactions.
Methods
We evaluate the approach on engineered protein samples.
Results
The method improves detection accuracy by 18 percent compared with the baseline.
References
This reference list must not become a finding.
"""

    analysis = DemoResearchModel().extract(text)

    assert analysis.thesis.startswith("We present a quantum spin resonance method")
    assert analysis.concepts[1].label == "Quantum spin resonance method"
    assert analysis.concepts[2].label == "Detection accuracy by 18 percent"
    assert analysis.concepts[3].label == "Engineered protein samples"
    assert "reference list" not in " ".join(evidence.excerpt for evidence in analysis.evidence).lower()
    assert len({evidence.excerpt for evidence in analysis.evidence}) >= 3
