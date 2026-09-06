from paper_atlas.schemas import AnalysisResponse
from paper_atlas.store import RunStore


def test_run_store_round_trips_response(tmp_path) -> None:
    store = RunStore(str(tmp_path / "runs.sqlite3"))
    response = AnalysisResponse(run_id="run-1", status="failed", warnings=["example"])

    store.save(response)

    restored = store.get("run-1")
    assert restored is not None
    assert restored.run_id == response.run_id
    assert restored.warnings == ["example"]
