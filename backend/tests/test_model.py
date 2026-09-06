import pytest

from paper_atlas.config import Settings
from paper_atlas.model import BedrockResearchModel, DemoResearchModel, _json_from_model_output, _provider_text


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
    assert all("line" in (evidence.source_location or "") for evidence in analysis.evidence)


def test_provider_response_helpers_accept_common_bedrock_shapes() -> None:
    assert _provider_text({"content": [{"type": "text", "text": "answer"}]}) == "answer"
    assert _provider_text({"output": {"message": {"content": [{"text": "nova answer"}]}}}) == "nova answer"
    assert _json_from_model_output('```json\n{"metadata": {"title": "Paper"}}\n```')["metadata"]["title"] == "Paper"


def test_bedrock_mode_requires_a_model_id() -> None:
    with pytest.raises(RuntimeError, match="BEDROCK_MODEL_ID"):
        BedrockResearchModel(Settings(model_mode="bedrock", bedrock_model_id=""))
