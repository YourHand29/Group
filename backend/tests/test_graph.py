from paper_atlas.graph import run_analysis
from paper_atlas.schemas import AnalysisRequest, PaperRecord


def test_analysis_workflow_returns_validated_map() -> None:
    response = run_analysis(AnalysisRequest(
        source_type="text",
        source="Attention is all you need. This paper evaluates a transformer model on translation benchmarks.",
        existing_papers=[PaperRecord(id="paper-02", title="Efficient attention methods", concepts=["attention", "transformer"])],
    ))

    assert response.status == "completed"
    assert response.paper.title.startswith("Attention")
    assert len(response.concepts) == 5
    assert len(response.evidence) == 3
    assert response.relationships[0].relationship_type == "similar"
    assert any("validated" in step.lower() for step in response.trace)


def test_invalid_url_is_rejected_before_ingestion() -> None:
    response = run_analysis(AnalysisRequest(source_type="url", source="not-a-url"))

    assert response.status == "failed"
    assert any("valid http(s) URL" in warning for warning in response.warnings)
