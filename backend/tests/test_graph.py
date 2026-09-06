from paper_atlas.agents import ScannedDocument
from paper_atlas.model import ResearchModel
from paper_atlas.graph import run_analysis
from paper_atlas.schemas import AnalysisRequest, PaperRecord


def test_analysis_workflow_returns_validated_map(monkeypatch) -> None:
    monkeypatch.setattr("paper_atlas.model.extract_named_concepts", lambda text: [])
    response = run_analysis(AnalysisRequest(
        source_type="text",
        source="Attention is all you need. This paper evaluates a transformer model on translation benchmarks.",
        existing_papers=[PaperRecord(id="paper-02", title="Efficient attention methods", concepts=["attention", "transformer"])],
    ))

    assert response.status == "completed"
    assert response.paper.title.startswith("Attention")
    assert len(response.concepts) == 5
    assert len(response.evidence) >= 3
    assert response.relationships[0].relationship_type == "similar"
    assert any("validated" in step.lower() for step in response.trace)


def test_invalid_url_is_rejected_before_ingestion() -> None:
    response = run_analysis(AnalysisRequest(source_type="url", source="not-a-url"))

    assert response.status == "failed"
    assert any("valid http(s) URL" in warning for warning in response.warnings)


def test_scanned_document_adapter_preserves_paragraph_order() -> None:
    document = ScannedDocument.model_validate({
        "text": "First paragraph.\n\nSecond paragraph.",
        "paragraphs": [
            {"id": "paragraph-0000", "text": "First paragraph.", "index": 0, "start_char": 0, "end_char": 16},
            {"id": "paragraph-0001", "text": "Second paragraph.", "index": 1, "start_char": 18, "end_char": 35},
        ],
    })

    assert ResearchModel.scanned_documents_to_text([document]) == "First paragraph.\n\nSecond paragraph."
