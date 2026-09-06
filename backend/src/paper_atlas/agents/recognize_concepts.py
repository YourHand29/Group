"""High-precision extraction and verification of paper concepts.

spaCy supplies the local language understanding layer. Wikipedia is used to
link a mention to a canonical article, and Wikidata supplies the semantic type
used to reject ordinary people, organizations, places, and languages when the
paper is actually referring to a law, theory, theorem, method, model, or
related scientific concept.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import html
import os
import re
from typing import Any
from urllib.parse import quote, urlparse

import httpx

try:
    import spacy
except ImportError:  # pragma: no cover - exercised when optional deps are absent
    spacy = None  # type: ignore[assignment]


_DEFAULT_MODEL = "en_core_web_sm"
_MAX_TEXT_CHARS = 200_000
_MAX_CANDIDATES = 24
_WIKIPEDIA_SEARCH_URL = "https://en.wikipedia.org/w/rest.php/v1/search/page"
_WIKIPEDIA_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/"
_WIKIPEDIA_HTML_URL = "https://en.wikipedia.org/api/rest_v1/page/html/"
_WIKIDATA_ENTITY_URL = "https://www.wikidata.org/wiki/Special:EntityData/"
_WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"
_WIKIPEDIA_USER_AGENT = os.getenv(
    "PAPER_ATLAS_WIKIPEDIA_USER_AGENT",
    "PaperAtlas/0.1 (https://github.com/YourHand29/Group; contact via repository)",
)

# These are Wikidata classes, not merely words found in an article title.
# P31 (instance of) and P279 (subclass of) values are checked against them.
_ALLOWED_TYPE_IDS = {
    "Q408891": "scientific law",
    "Q214070": "physical law",
    "Q1571031": "scientific principle",
    "Q3239681": "scientific theory",
    "Q65943": "theorem",
    "Q8366": "algorithm",
    "Q486902": "mathematical model",
    "Q11345": "equation",
    "Q1293220": "physical phenomenon",
    "Q46857": "scientific method",
}
_ALLOWED_TYPE_LABEL = re.compile(
    r"\b(?:scientific|physical|mathematical|programming|computational)\s+"
    r"(?:law|principle|theory|model|equation|method|effect|phenomenon)\b"
    r"|\btheorem\b|\balgorithm\b|\b(?:software|system) architecture\b|\bprotocol\b"
    r"|\b(?:dataset|benchmark|database|statistical method|measurement|metric)\b"
    r"|\b(?:scientific instrument|technology|software|programming language)\b"
    r"|\b(?:biological process|protein|gene|organism|chemical compound|material)\b"
    r"|\b(?:scientist|researcher)\b",
    re.IGNORECASE,
)
_ALLOWED_ENTITY_LABELS = {
    "EVENT",
    "FAC",
    "GPE",
    "LANGUAGE",
    "LAW",
    "LOC",
    "NORP",
    "ORG",
    "PERSON",
    "PRODUCT",
    "WORK_OF_ART",
}
_CONCEPT_CUE_WORDS = {
    "algorithm",
    "architecture",
    "benchmark",
    "database",
    "dataset",
    "effect",
    "equation",
    "framework",
    "hypothesis",
    "law",
    "method",
    "methods",
    "model",
    "models",
    "metric",
    "measurement",
    "organism",
    "paradox",
    "phenomenon",
    "principle",
    "protocol",
    "software",
    "technology",
    "theorem",
    "theorems",
    "theory",
    "theories",
}
_PATTERN_STOP_WORDS = {
    "and",
    "can",
    "describes",
    "explains",
    "is",
    "provides",
    "shows",
    "states",
    "tests",
    "uses",
}
_CONCEPT_PATTERN = re.compile(
    r"\b(?P<term>(?:(?:[A-Za-z0-9][A-Za-z0-9'’./-]*|and|of|in|for|the)\s+){0,4}"
    r"(?:law|laws|theorem|theorems|principle|principles|theory|theories|hypothesis|hypotheses|"
    r"model|models|equation|equations|algorithm|algorithms|effect|effects|phenomenon|phenomena|"
    r"paradox|protocol|architecture|framework|method|methods|dataset|datasets|benchmark|benchmarks|"
    r"database|databases|metric|metrics|measurement|measurements|software|technology|protein|gene|"
    r"organism|material|materials|compound|compounds)"
    r"(?:\s+(?:of|in|for|on|from|the)\s+[A-Za-z0-9][A-Za-z0-9'’./-]*(?:\s+[A-Za-z0-9][A-Za-z0-9'’./-]*){0,4})?)\b",
    re.IGNORECASE,
)
_AUTHORITY_DOMAINS = {
    "acm.org",
    "annualreviews.org",
    "aps.org",
    "arxiv.org",
    "britannica.com",
    "cambridge.org",
    "cern.ch",
    "doi.org",
    "ieee.org",
    "jstor.org",
    "nature.com",
    "ncbi.nlm.nih.gov",
    "nih.gov",
    "nasa.gov",
    "oup.com",
    "plos.org",
    "royalsocietypublishing.org",
    "science.org",
    "sciencedirect.com",
    "sciencemag.org",
    "springer.com",
    "wiley.com",
}
_GENERIC_TERMS = {"abstract", "article", "paper", "study", "the authors"}


@dataclass(frozen=True)
class WikipediaMatch:
    title: str
    page_id: int | None
    url: str
    wikidata_id: str
    description: str


@dataclass(frozen=True)
class WikidataMatch:
    wikidata_id: str
    label: str
    description: str
    concept_type: str
    reference_urls: tuple[str, ...]


@dataclass(frozen=True)
class NamedConcept:
    """A paper mention linked to a typed, publicly documented concept."""

    term: str
    entity_type: str
    mentions: int
    start_char: int
    excerpt: str
    concept_type: str
    knowledge_description: str
    wikipedia_title: str
    wikipedia_url: str
    wikidata_id: str
    source_urls: tuple[str, ...]
    recognition_status: str
    confidence: float


def _model_name() -> str:
    return os.getenv("PAPER_ATLAS_SPACY_MODEL", _DEFAULT_MODEL)


@lru_cache(maxsize=2)
def _load_pipeline(model_name: str) -> Any:
    if spacy is None:
        return None
    try:
        return spacy.load(model_name)
    except OSError:
        return None


def named_entity_model_available() -> bool:
    """Return whether the configured spaCy pipeline can be loaded."""

    return _load_pipeline(_model_name()) is not None


def _clean_term(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip(" \t\r\n,.;:()[]{}")
    return re.sub(r"^(?:the|a|an)\s+", "", cleaned, flags=re.IGNORECASE)


def _excerpt(text: str, start: int, end: int) -> str:
    excerpt_start = max(0, start - 180)
    excerpt_end = min(len(text), end + 220)
    return " ".join(text[excerpt_start:excerpt_end].split())


def _is_concept_cue(token: str) -> bool:
    return token.casefold().strip(".,;:()[]{}") in _CONCEPT_CUE_WORDS or token.casefold().rstrip("s").strip(".,;:()[]{}") in _CONCEPT_CUE_WORDS


def _trim_pattern_term(value: str) -> str:
    """Keep an eponymic phrase while dropping the sentence after it."""

    tokens = value.split()
    cue_indices = [index for index, token in enumerate(tokens) if _is_concept_cue(token)]
    if not cue_indices:
        return value
    cue_index = cue_indices[-1]
    trimmed = tokens[: cue_index + 1]
    remainder = tokens[cue_index + 1 :]
    if remainder and remainder[0].casefold() in {"of", "in", "for", "on", "from"}:
        trimmed.append(remainder.pop(0))
        for token in remainder[:3]:
            if token.casefold().strip(".,;:()[]{}") in _PATTERN_STOP_WORDS:
                break
            trimmed.append(token)
    return " ".join(trimmed)


def _add_candidate(
    candidates: dict[str, dict[str, Any]],
    text: str,
    term: str,
    entity_type: str,
    signal: str,
    start_char: int,
    end_char: int,
) -> None:
    cleaned_term = _clean_term(term)
    if len(cleaned_term) < 2 or not re.search(r"[A-Za-z]", cleaned_term):
        return
    if cleaned_term.casefold() in _GENERIC_TERMS:
        return

    key = cleaned_term.casefold()
    candidate = candidates.get(key)
    if candidate is None:
        candidate = {
            "term": cleaned_term,
            "entity_type": entity_type,
            "mention_spans": set(),
            "start_char": start_char,
            "excerpt": _excerpt(text, start_char, end_char),
            "signals": set(),
        }
        candidates[key] = candidate
    candidate["mention_spans"].add((start_char, end_char))
    candidate["signals"].add(signal)


def _extract_candidates(text: str, document: Any) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    for entity in document.ents:
        if entity.label_ in _ALLOWED_ENTITY_LABELS:
            _add_candidate(
                candidates,
                text,
                entity.text,
                entity.label_,
                "ner",
                entity.start_char,
                entity.end_char,
            )

    # Noun phrases broaden recall for terms such as "self-attention mechanism"
    # while requiring a repeated, hyphenated, acronym-like, or cue-bearing
    # phrase before it can enter the external verification pipeline.
    for chunk in getattr(document, "noun_chunks", ()):
        phrase = _clean_term(chunk.text)
        words = phrase.split()
        lower_phrase = phrase.casefold()
        repeated = text.casefold().count(lower_phrase) >= 2
        acronym_like = any(len(word) >= 2 and word.isupper() for word in words)
        hyphenated = "-" in phrase or "–" in phrase
        cue_bearing = any(word in _CONCEPT_CUE_WORDS for word in lower_phrase.split())
        if len(words) >= 2 and (repeated or acronym_like or hyphenated or cue_bearing):
            _add_candidate(
                candidates,
                text,
                phrase,
                "NOUN_PHRASE",
                "noun_phrase",
                chunk.start_char,
                chunk.end_char,
            )

    # Explicit eponymic forms are important for laws and theories that a
    # general NER model does not label as an entity, e.g. Newton's third law.
    for match in _CONCEPT_PATTERN.finditer(text):
        term = _trim_pattern_term(match.group("term"))
        if any(_is_concept_cue(cue) for cue in term.split()):
            _add_candidate(
                candidates,
                text,
                term,
                "NAMED_CONCEPT",
                "pattern",
                match.start("term"),
                match.end("term"),
            )

    return sorted(
        candidates.values(),
        key=lambda candidate: (
            -(3 if "pattern" in candidate["signals"] else 0)
            - (2 if "ner" in candidate["signals"] else 0)
            - (1 if "noun_phrase" in candidate["signals"] else 0),
            -len(candidate["mention_spans"]),
            candidate["start_char"],
        ),
    )


@lru_cache(maxsize=512)
def _wikipedia_search(term: str) -> tuple[dict[str, Any], ...]:
    try:
        response = httpx.get(
            _WIKIPEDIA_SEARCH_URL,
            params={"q": term, "limit": 5},
            headers={"User-Agent": _WIKIPEDIA_USER_AGENT},
            timeout=4.0,
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError, TypeError):
        return ()

    pages = payload.get("pages", []) if isinstance(payload, dict) else []
    if not isinstance(pages, list):
        return ()

    term_tokens = set(re.findall(r"[a-z0-9]+", term.casefold()))

    def relevance(page: dict[str, Any]) -> tuple[int, int, int]:
        title = str(page.get("title", ""))
        title_tokens = set(re.findall(r"[a-z0-9]+", title.casefold()))
        exact = int(title.casefold() == term.casefold())
        return exact, len(term_tokens & title_tokens), -pages.index(page)

    valid_pages = [page for page in pages if isinstance(page, dict) and page.get("title")]
    return tuple(sorted(valid_pages, key=relevance, reverse=True))


@lru_cache(maxsize=512)
def _wikipedia_lookup(term: str) -> WikipediaMatch | None:
    for result in _wikipedia_search(term):
        title = str(result["title"])
        page_title = quote(title.replace(" ", "_"), safe="")
        try:
            response = httpx.get(
                f"{_WIKIPEDIA_SUMMARY_URL}{page_title}",
                headers={"User-Agent": _WIKIPEDIA_USER_AGENT},
                timeout=4.0,
                follow_redirects=True,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError, TypeError):
            continue

        if not isinstance(payload, dict):
            continue
        if payload.get("type") == "disambiguation":
            continue
        wikidata_id = payload.get("wikibase_item")
        if not isinstance(wikidata_id, str) or not wikidata_id:
            continue
        titles = payload.get("titles", {})
        canonical_title = titles.get("canonical") if isinstance(titles, dict) else None
        canonical_title = canonical_title if isinstance(canonical_title, str) else title
        content_urls = payload.get("content_urls", {})
        desktop = content_urls.get("desktop", {}) if isinstance(content_urls, dict) else {}
        page_url = desktop.get("page") if isinstance(desktop, dict) else None
        if not isinstance(page_url, str) or not page_url:
            page_url = f"https://en.wikipedia.org/wiki/{quote(canonical_title.replace(' ', '_'), safe='')}"
        return WikipediaMatch(
            title=canonical_title,
            page_id=payload.get("pageid") if isinstance(payload.get("pageid"), int) else None,
            url=page_url,
            wikidata_id=wikidata_id,
            description=str(payload.get("description") or ""),
        )
    return None


def _claim_item_ids(entity: dict[str, Any], property_id: str) -> set[str]:
    ids: set[str] = set()
    for claim in entity.get("claims", {}).get(property_id, []):
        if not isinstance(claim, dict):
            continue
        value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(value, dict) and isinstance(value.get("id"), str):
            ids.add(value["id"])
    return ids


@lru_cache(maxsize=512)
def _wikidata_type_labels(type_ids: tuple[str, ...]) -> dict[str, str]:
    if not type_ids:
        return {}
    try:
        response = httpx.get(
            _WIKIDATA_API_URL,
            params={
                "action": "wbgetentities",
                "ids": "|".join(type_ids),
                "props": "labels",
                "languages": "en",
                "format": "json",
                "formatversion": "2",
            },
            headers={"User-Agent": _WIKIPEDIA_USER_AGENT},
            timeout=4.0,
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError, TypeError):
        return {}

    entities = payload.get("entities", {}) if isinstance(payload, dict) else {}
    labels: dict[str, str] = {}
    for type_id, entity in entities.items() if isinstance(entities, dict) else ():
        label = entity.get("labels", {}).get("en", {}).get("value") if isinstance(entity, dict) else None
        if isinstance(label, str):
            labels[type_id] = label
    return labels


def _reference_urls(entity: dict[str, Any]) -> tuple[str, ...]:
    urls: list[str] = []
    claims = entity.get("claims", {})
    if not isinstance(claims, dict):
        return ()
    for claim_list in claims.values():
        if not isinstance(claim_list, list):
            continue
        for claim in claim_list:
            if not isinstance(claim, dict):
                continue
            for reference in claim.get("references", []):
                snaks = reference.get("snaks", {}) if isinstance(reference, dict) else {}
                for snak in snaks.get("P854", []) if isinstance(snaks, dict) else []:
                    value = snak.get("datavalue", {}).get("value") if isinstance(snak, dict) else None
                    if isinstance(value, str) and value.startswith("http"):
                        urls.append(value)
            mainsnak = claim.get("mainsnak", {})
            value = mainsnak.get("datavalue", {}).get("value") if isinstance(mainsnak, dict) else None
            if isinstance(value, str) and mainsnak.get("property") == "P356":
                urls.append(f"https://doi.org/{value}")
    return tuple(dict.fromkeys(urls))[:3]


@lru_cache(maxsize=512)
def _wikidata_lookup(wikidata_id: str) -> WikidataMatch | None:
    try:
        response = httpx.get(
            f"{_WIKIDATA_ENTITY_URL}{wikidata_id}.json",
            headers={"User-Agent": _WIKIPEDIA_USER_AGENT},
            timeout=4.0,
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError, TypeError):
        return None

    entities = payload.get("entities", {}) if isinstance(payload, dict) else {}
    entity = entities.get(wikidata_id) if isinstance(entities, dict) else None
    if not isinstance(entity, dict):
        return None

    type_ids = sorted(_claim_item_ids(entity, "P31") | _claim_item_ids(entity, "P279"))
    type_labels = {**_ALLOWED_TYPE_IDS, **_wikidata_type_labels(tuple(type_ids))}
    matching_types = [
        (type_id, type_labels.get(type_id, ""))
        for type_id in type_ids
        if type_id in _ALLOWED_TYPE_IDS or _ALLOWED_TYPE_LABEL.search(type_labels.get(type_id, ""))
    ]
    if not matching_types:
        return None

    labels = entity.get("labels", {})
    descriptions = entity.get("descriptions", {})
    label = labels.get("en", {}).get("value", "") if isinstance(labels, dict) else ""
    description = descriptions.get("en", {}).get("value", "") if isinstance(descriptions, dict) else ""
    concept_type = matching_types[0][1] or _ALLOWED_TYPE_IDS.get(matching_types[0][0], "scientific concept")
    return WikidataMatch(
        wikidata_id=wikidata_id,
        label=str(label),
        description=str(description),
        concept_type=concept_type,
        reference_urls=_reference_urls(entity),
    )


def _is_authority_url(url: str) -> bool:
    hostname = (urlparse(url).hostname or "").casefold().removeprefix("www.")
    return (
        hostname.endswith(".edu")
        or hostname.endswith(".gov")
        or hostname.endswith(".ac.uk")
        or any(hostname == domain or hostname.endswith(f".{domain}") for domain in _AUTHORITY_DOMAINS)
    )


@lru_cache(maxsize=256)
def _wikipedia_authority_urls(title: str) -> tuple[str, ...]:
    page_title = quote(title.replace(" ", "_"), safe="")
    try:
        response = httpx.get(
            f"{_WIKIPEDIA_HTML_URL}{page_title}",
            headers={"User-Agent": _WIKIPEDIA_USER_AGENT},
            timeout=4.0,
            follow_redirects=True,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        return ()

    urls: list[str] = []
    for raw_url in re.findall(r"href=[\"'](https?://[^\"']+)[\"']", response.text):
        url = html.unescape(raw_url)
        if _is_authority_url(url):
            urls.append(url)
    return tuple(dict.fromkeys(urls))[:3]


def _link_candidate(candidate: dict[str, Any]) -> NamedConcept | None:
    wikipedia = _wikipedia_lookup(candidate["term"])
    if wikipedia is None:
        return None
    wikidata = _wikidata_lookup(wikipedia.wikidata_id)
    if wikidata is None:
        return None

    wikipedia_sources = _wikipedia_authority_urls(wikipedia.title)
    source_urls = tuple(
        dict.fromkeys(
            [
                wikipedia.url,
                f"https://www.wikidata.org/wiki/{wikidata.wikidata_id}",
                *wikidata.reference_urls,
                *wikipedia_sources,
            ]
        )
    )[:6]
    authority_sources = tuple(
        dict.fromkeys(
            [
                *wikipedia_sources,
                *(url for url in wikidata.reference_urls if _is_authority_url(url)),
            ]
        )
    )
    recognition_status = "source_supported" if authority_sources else "classified"
    signal_count = len(candidate["signals"])
    confidence = min(0.92, 0.72 + signal_count * 0.05 + (0.08 if recognition_status == "source_supported" else 0))
    return NamedConcept(
        term=candidate["term"],
        entity_type=candidate["entity_type"],
        mentions=len(candidate["mention_spans"]),
        start_char=candidate["start_char"],
        excerpt=candidate["excerpt"],
        concept_type=wikidata.concept_type,
        knowledge_description=wikidata.description,
        wikipedia_title=wikipedia.title,
        wikipedia_url=wikipedia.url,
        wikidata_id=wikidata.wikidata_id,
        source_urls=source_urls,
        recognition_status=recognition_status,
        confidence=confidence,
    )


def extract_named_concepts(text: str, max_concepts: int = 8) -> list[NamedConcept]:
    """Extract concepts that are detected, canonically linked, and semantically typed."""

    if not text.strip() or max_concepts <= 0:
        return []

    pipeline = _load_pipeline(_model_name())
    if pipeline is None:
        return []

    bounded_text = text[:_MAX_TEXT_CHARS]
    document = pipeline(bounded_text)
    candidates = _extract_candidates(bounded_text, document)[:_MAX_CANDIDATES]
    linked: list[NamedConcept] = []
    seen_wikidata_ids: set[str] = set()
    for candidate in candidates:
        concept = _link_candidate(candidate)
        if concept is None or concept.wikidata_id in seen_wikidata_ids:
            continue
        seen_wikidata_ids.add(concept.wikidata_id)
        linked.append(concept)
        if len(linked) >= max_concepts:
            break
    return linked
