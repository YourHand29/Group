from types import SimpleNamespace

import paper_atlas.agents.recognize_concepts as recognize_concepts


def test_pattern_extraction_finds_eponymic_law_without_sentence_tail():
    text = "Newton's third law of motion explains action and reaction."
    candidates = recognize_concepts._extract_candidates(text, SimpleNamespace(ents=[], noun_chunks=[]))

    assert any(candidate["term"] == "Newton's third law of motion" for candidate in candidates)
    assert all("explains" not in candidate["term"] for candidate in candidates)


def test_linked_concept_preserves_canonical_and_authority_sources(monkeypatch):
    candidate = {
        "term": "Newton's third law of motion",
        "entity_type": "NAMED_CONCEPT",
        "mention_spans": {(0, 32)},
        "start_char": 0,
        "excerpt": "Newton's third law of motion explains action and reaction.",
        "signals": {"pattern"},
    }
    monkeypatch.setattr(
        recognize_concepts,
        "_wikipedia_lookup",
        lambda term: recognize_concepts.WikipediaMatch(
            title="Newton's laws of motion",
            page_id=40924,
            url="https://en.wikipedia.org/wiki/Newton%27s_laws_of_motion",
            wikidata_id="Q38433",
            description="Laws in physics about force and motion",
        ),
    )
    monkeypatch.setattr(
        recognize_concepts,
        "_wikidata_lookup",
        lambda wikidata_id: recognize_concepts.WikidataMatch(
            wikidata_id="Q38433",
            label="Newton's laws of motion",
            description="classical formulation of mechanics",
            concept_type="scientific law",
            reference_urls=("https://doi.org/10.0000/example",),
        ),
    )
    monkeypatch.setattr(
        recognize_concepts,
        "_wikipedia_authority_urls",
        lambda title: ("https://www.feynmanlectures.caltech.edu/I_09.html",),
    )

    concept = recognize_concepts._link_candidate(candidate)

    assert concept is not None
    assert concept.wikipedia_title == "Newton's laws of motion"
    assert concept.wikidata_id == "Q38433"
    assert concept.concept_type == "scientific law"
    assert concept.recognition_status == "source_supported"
    assert "https://www.feynmanlectures.caltech.edu/I_09.html" in concept.source_urls
