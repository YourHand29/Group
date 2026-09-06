from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
import json
import re
from typing import Any, Protocol

from .agents import (
    ScannedDocument,
    explain_concepts,
    extract_named_concepts,
    scan_text_document,
)
from .config import Settings
from .schemas import PaperAnalysis, PaperRecord, Relationship


class ResearchModel(Protocol):
    """Provider boundary that adapts scanned documents for model agents."""

    def extract(self, text: str, source_url: str | None = None, query: str | None = None) -> PaperAnalysis:
        scanned_documents = self.scan_documents(text)
        return self.extract_scanned_documents(scanned_documents, source_url, query)

    @staticmethod
    def scan_documents(text: str) -> list[ScannedDocument]:
        """Create document records for text that has already passed ingestion."""
        return [scan_text_document(text)] if text.strip() else []

    @staticmethod
    def scanned_documents_to_text(documents: list[ScannedDocument]) -> str:
        """Adapt scanned documents while retaining useful section line breaks."""
        return "\n\n".join(
            document.source_text.strip()
            if document.source_text and document.source_text.strip()
            else "\n\n".join(paragraph.text for paragraph in document.paragraphs)
            for document in documents
            if (document.source_text and document.source_text.strip()) or document.paragraphs
        )

    @staticmethod
    def recognize_scanned_documents(documents: list[ScannedDocument]):
        """Run the unchanged recognition agent against normalized paragraph text."""
        return extract_named_concepts(ResearchModel.scanned_documents_to_text(documents))

    @staticmethod
    def explain_analysis(analysis: PaperAnalysis):
        """Run the unchanged explanation agent after concepts and evidence exist."""
        return explain_concepts(analysis.concepts, analysis.evidence)

    @abstractmethod
    def extract_scanned_documents(
        self,
        scanned_documents: list[ScannedDocument],
        source_url: str | None = None,
        query: str | None = None,
    ) -> PaperAnalysis:
        """Produce an analysis from normalized scanned documents."""
        ...

    def summarise(self, analysis: PaperAnalysis) -> tuple[str, int]:
        ...

    def compare(self, analysis: PaperAnalysis, existing_papers: list[PaperRecord]) -> list[Relationship]:
        ...


def _first_line(text: str) -> str:
    for line in text.splitlines():
        candidate = line.strip(" #\t")
        if 4 <= len(candidate) <= 140:
            return candidate
    return "Imported research paper"


def search_text(text: str, query: str | None) -> list[str]:
    """Find short excerpts containing a user-requested concept or phrase."""
    if not query or not query.strip():
        return []
    clean_query = query.strip()
    lower_text = text.lower()
    terms = re.findall(r"[a-z0-9][a-z0-9-]{2,}", clean_query.lower())
    positions: list[int] = []
    phrase_position = lower_text.find(clean_query.lower())
    if phrase_position >= 0:
        positions.append(phrase_position)
    for term in terms:
        position = lower_text.find(term)
        if position >= 0:
            positions.append(position)
    matches: list[str] = []
    for position in positions:
        excerpt = " ".join(text[max(0, position - 120): position + 240].split())
        if excerpt and excerpt not in matches:
            matches.append(excerpt)
    return matches[:3]


_SECTION_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*[\s.)-]+)?"
    r"(?P<section>abstract|introduction|background|related work|literature review|"
    r"method|methods|methodology|approach|materials and methods|experiments?|evaluation|"
    r"results?|findings?|discussion|conclusion|limitations?)\s*:?[\s.]*$",
    re.IGNORECASE,
)
_METHOD_CUES = ("propose", "present", "introduce", "develop", "design", "use", "apply", "adopt", "employ")
_FINDING_CUES = ("show", "find", "demonstrat", "achiev", "improv", "outperform", "increase", "decrease", "reduce", "result")
_EXPERIMENT_CUES = ("evaluat", "experiment", "benchmark", "dataset", "corpus", "participants", "test", "trained on", "measured on")
_METRIC_CUES = ("accuracy", "precision", "recall", "f1", "auc", "bleu", "rouge", "score", "error", "loss", "latency", "runtime", "reduction", "improvement", "significant")
_COMPARISON_STOPWORDS = {
    "about", "after", "against", "also", "been", "being", "between", "from", "have", "into",
    "more", "most", "only", "over", "paper", "propose", "proposed", "research", "shows", "that",
    "their", "there", "these", "they", "this", "using", "with", "which", "will",
}


def _compact_text(value: str, limit: int = 280) -> str:
    clean = " ".join(value.split()).strip()
    if len(clean) <= limit:
        return clean
    shortened = clean[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:")
    return f"{shortened}…"


def _sentence_parts(value: str) -> list[str]:
    clean = " ".join(value.split()).strip()
    if not clean:
        return []
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(])", clean) if part.strip()]


def _paper_sentences(text: str) -> list[tuple[str, str]]:
    """Return substantive sentences with the nearest paper section label."""

    sentences: list[tuple[str, str]] = []
    section = "opening"
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split()).strip(" -\t")
        if not line:
            continue
        match = _SECTION_RE.match(line)
        if match:
            section = match.group("section").casefold()
            continue
        for sentence in _sentence_parts(line):
            if len(re.findall(r"[A-Za-z0-9]+", sentence)) >= 5:
                sentences.append((sentence, section))
    if not sentences:
        sentences = [(sentence, "opening") for sentence in _sentence_parts(text)]
    return sentences


def _best_paper_sentence(
    sentences: list[tuple[str, str]],
    cues: tuple[str, ...],
    preferred_sections: tuple[str, ...] = (),
) -> tuple[str, str] | None:
    candidates: list[tuple[int, int, str, str]] = []
    for index, (sentence, section) in enumerate(sentences):
        lower = sentence.casefold()
        if len(sentence) < 25:
            continue
        cue_score = sum(1 for cue in cues if re.search(rf"\b{re.escape(cue.casefold())}\w*\b", lower))
        section_score = 2 if any(preferred in section for preferred in preferred_sections) else 0
        # Avoid selecting a bare title or author line when a sentence with a
        # research verb is available.
        if cue_score == 0 and cues:
            continue
        candidates.append((cue_score + section_score, -index, sentence, section))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    _, _, sentence, section = candidates[0]
    return _compact_text(sentence), section


def _first_substantive_sentence(sentences: list[tuple[str, str]]) -> tuple[str, str] | None:
    for sentence, section in sentences:
        if len(sentence) >= 35:
            return _compact_text(sentence), section
    return sentences[0] if sentences else None


def _phrase_after_cue(sentence: str, cues: tuple[str, ...], limit: int = 64) -> str | None:
    cue_pattern = "|".join(re.escape(cue) for cue in cues)
    match = re.search(rf"\b(?:{cue_pattern})\w*\b\s+(?:a|an|the|our|this|their)?\s*(?P<phrase>[^.;,:]+)", sentence, re.IGNORECASE)
    if not match:
        return None
    phrase = re.split(r"\s+(?:to|for|on|across|from|that|which|while|using|with|and|compared|versus|against|relative)\s+", match.group("phrase"), maxsplit=1, flags=re.IGNORECASE)[0]
    phrase = _compact_text(phrase, limit).strip(" .,")
    return phrase if len(phrase) >= 4 else None


def _metric_label(sentence: str) -> str | None:
    metric = re.search(
        r"\b(?:accuracy|precision|recall|F1(?:-score)?|AUC|BLEU|ROUGE|score|error|loss|latency|runtime|reduction|improvement)\b",
        sentence,
        re.IGNORECASE,
    )
    if not metric:
        return None
    number = re.search(r"[+-]?\d+(?:\.\d+)?\s*(?:%|percent|percentage points)?", sentence)
    if number:
        return f"{metric.group(0)} ({number.group(0).strip()})"
    return metric.group(0)


def _label_from_sentence(sentence: str, cues: tuple[str, ...], fallback: str) -> str:
    phrase = _phrase_after_cue(sentence, cues)
    if phrase:
        return phrase[0].upper() + phrase[1:]
    words = sentence.split()
    if len(words) > 8:
        return _compact_text(" ".join(words[:8]), 58).rstrip(".,") + "…"
    return sentence.rstrip(".") or fallback


def _source_location(text: str, excerpt: str, section: str) -> str:
    """Return a useful, stable location in the filtered paper body."""

    clean_excerpt = " ".join(excerpt.split()).casefold()
    line = None
    if clean_excerpt:
        words = clean_excerpt.split()
        signatures = (" ".join(words[:8]), " ".join(words[:4]))
        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            normalized_line = " ".join(raw_line.split()).casefold()
            if any(signature and signature in normalized_line for signature in signatures):
                line = line_number
                break
    location = f"{section.title()} section"
    if line is not None:
        location += f", line {line}"
    else:
        location += ", filtered paper text"
    return location


def _offset_location(text: str, offset: int, section: str | None = None) -> str:
    safe_offset = max(0, min(offset, len(text)))
    line = text.count("\n", 0, safe_offset) + 1
    return f"{section.title() + ' section, ' if section else ''}line {line} (character {safe_offset})"


def _comparison_terms(value: str) -> set[str]:
    return {
        term
        for term in re.findall(r"[a-z][a-z0-9-]{3,}", value.casefold())
        if term not in _COMPARISON_STOPWORDS
    }


def _comparison_relationship(current_text: str) -> str:
    lowered = current_text.casefold()
    if re.search(r"\b(?:contradict|challenge|disagree|fails? to|cannot|worse than)\b", lowered):
        return "contradicts"
    if re.search(r"\b(?:extend|extends|build(?:s)? on|adapt(?:s)?|improve(?:s)? on)\b", lowered):
        return "extends"
    if re.search(r"\b(?:support(?:s)?|confirm(?:s)?|consistent with|agree(?:s)? with)\b", lowered):
        return "supports"
    return "similar"


def _experiment_label(sentence: str) -> str:
    """Prefer the named dataset, benchmark, task, or sample in an evaluation sentence."""

    match = re.search(r"\b(?:on|using|across|with)\s+(?:the\s+)?(?P<subject>[^.;,:]+)", sentence, re.IGNORECASE)
    if match:
        subject = re.split(r"\s+(?:to|for|that|which|and|compared|versus|against)\s+", match.group("subject"), maxsplit=1, flags=re.IGNORECASE)[0]
        subject = _compact_text(subject, 58).strip(" .,")
        if len(subject) >= 4:
            return subject[0].upper() + subject[1:]
    return _label_from_sentence(sentence, ("evaluate", "experiment", "benchmark", "test", "measure"), "Evaluation described in the paper")


def _evidence(
    evidence_id: str,
    claim: str,
    source: tuple[str, str] | None,
    kind: str,
    fallback: str,
    confidence: float,
    paper_text: str,
) -> dict[str, object]:
    sentence, section = source or (fallback, "paper text")
    return {
        "id": evidence_id,
        "claim": claim,
        "kind": kind,
        "excerpt": _compact_text(sentence, 420),
        "source_location": _source_location(
            paper_text,
            sentence,
            "opening text" if section == "opening" else section,
        ),
        "confidence": confidence,
    }


class DemoResearchModel(ResearchModel):
    """Deterministic stand-in that keeps the workflow runnable without an API key."""

    def extract_scanned_documents(
        self,
        scanned_documents: list[ScannedDocument],
        source_url: str | None = None,
        query: str | None = None,
    ) -> PaperAnalysis:
        text = self.scanned_documents_to_text(scanned_documents)
        title = _first_line(text)
        year_match = re.search(r"\b(19|20)\d{2}\b", text)
        year = int(year_match.group(0)) if year_match else None
        query_matches = search_text(text, query)

        sentences = _paper_sentences(text)
        opening_source = _first_substantive_sentence(sentences)
        thesis_source = _best_paper_sentence(
            sentences,
            ("propose", "present", "introduce", "develop", "investigate", "aim", "show", "demonstrate"),
            ("abstract", "introduction", "conclusion", "discussion"),
        ) or opening_source
        thesis = thesis_source[0] if thesis_source else f"The paper studies {title}."

        method_source = _best_paper_sentence(
            sentences,
            _METHOD_CUES,
            ("method", "approach", "experiment", "evaluation"),
        ) or _best_paper_sentence(
            sentences,
            ("method", "architecture", "model", "framework", "approach"),
            ("method", "approach", "experiment", "evaluation"),
        )
        finding_source = _best_paper_sentence(
            sentences,
            _FINDING_CUES,
            ("result", "finding", "discussion", "conclusion", "abstract"),
        ) or thesis_source
        experiment_source = _best_paper_sentence(
            sentences,
            _EXPERIMENT_CUES,
            ("experiment", "evaluation", "method"),
        ) or method_source
        metric_source = _best_paper_sentence(
            sentences,
            _METRIC_CUES,
            ("result", "finding", "evaluation", "experiment"),
        ) or finding_source

        method_label = _label_from_sentence(
            method_source[0], _METHOD_CUES, "Method described in the paper"
        ) if method_source else "Method described in the paper"
        finding_label = _label_from_sentence(
            finding_source[0], _FINDING_CUES, "Finding reported by the paper"
        ) if finding_source else "Finding reported by the paper"
        experiment_label = _experiment_label(experiment_source[0]) if experiment_source else "Evaluation described in the paper"
        metric_label = _metric_label(metric_source[0]) if metric_source else None
        metric_label = metric_label or _label_from_sentence(
            metric_source[0], ("report", "measure", "achieve", "improv", "reduce"), "Result reported by the paper"
        ) if metric_source else "Result reported by the paper"

        evidence = [
            _evidence(
                "evidence-context",
                "The paper frames its research question or central claim.",
                thesis_source or opening_source,
                "context",
                text,
                0.84,
                text,
            ),
            _evidence(
                "evidence-method",
                f"The paper describes the approach: {method_label}.",
                method_source or thesis_source,
                "experiment",
                text,
                0.80,
                text,
            ),
            _evidence(
                "evidence-finding",
                f"The paper reports this outcome: {finding_label}.",
                finding_source or thesis_source,
                "statistic",
                text,
                0.78,
                text,
            ),
            _evidence(
                "evidence-experiment",
                f"The paper evaluates its claim using {experiment_label}.",
                experiment_source or method_source,
                "dataset",
                text,
                0.76,
                text,
            ),
            _evidence(
                "evidence-metric",
                f"The paper provides a measurable result: {metric_label}.",
                metric_source or finding_source,
                "statistic",
                text,
                0.73,
                text,
            ),
        ]
        if query_matches:
            query_position = text.casefold().find(query.strip().casefold())
            evidence.append({"id": "evidence-query", "claim": f"The requested concept '{query.strip()}' appears in the extracted paper text.", "kind": "quote", "excerpt": query_matches[0], "source_location": _offset_location(text, query_position if query_position >= 0 else 0, "query match"), "confidence": 0.9})
        concepts = [
            {"id": "thesis", "label": title[:72], "kind": "thesis", "description": thesis, "evidence_ids": ["evidence-context"], "confidence": 0.84, "recognition_status": "structural"},
            {"id": "method", "label": method_label, "kind": "method", "description": method_source[0] if method_source else "The paper does not expose a clear method section in the extracted text.", "evidence_ids": ["evidence-method"], "confidence": 0.80, "recognition_status": "structural"},
            {"id": "finding", "label": finding_label, "kind": "finding", "description": finding_source[0] if finding_source else "The paper does not expose a clear findings section in the extracted text.", "evidence_ids": ["evidence-finding"], "confidence": 0.78, "recognition_status": "structural"},
            {"id": "experiment", "label": experiment_label, "kind": "experiment", "description": experiment_source[0] if experiment_source else "The paper does not expose a clear evaluation description in the extracted text.", "evidence_ids": ["evidence-experiment"], "confidence": 0.76, "recognition_status": "structural"},
            {"id": "metric", "label": metric_label, "kind": "metric", "description": metric_source[0] if metric_source else "The paper does not expose a clear measurable result in the extracted text.", "evidence_ids": ["evidence-metric"], "confidence": 0.73, "recognition_status": "structural"},
        ]

        # Add only paper-specific entities that the recognition pipeline can
        # link to a documented concept; do not manufacture unsupported labels.
        structural_labels = {concept["label"].casefold() for concept in concepts}
        for index, entity in enumerate(self.recognize_scanned_documents(scanned_documents), start=1):
            if entity.term.casefold() in structural_labels:
                continue
            evidence_id = f"evidence-entity-{index}"
            evidence.append({
                "id": evidence_id,
                "claim": f"The paper mentions {entity.term}.",
                "kind": "quote",
                "excerpt": entity.excerpt,
                "source_location": _offset_location(text, entity.start_char),
                "confidence": 0.72,
            })
            concepts.append({
                "id": f"entity-{index}",
                "label": entity.term,
                "kind": "concept",
                "description": (
                    f"{entity.concept_type.title()} documented as {entity.term}. "
                    f"{entity.knowledge_description} "
                    f"Recognized in the paper as a {entity.entity_type.lower()} mention "
                    f"({entity.mentions} occurrence(s))."
                ),
                "evidence_ids": [evidence_id],
                "confidence": entity.confidence,
                "concept_type": entity.concept_type,
                "wikipedia_url": entity.wikipedia_url,
                "wikidata_id": entity.wikidata_id,
                "source_urls": list(entity.source_urls),
                "recognition_status": entity.recognition_status,
            })

        return PaperAnalysis(
            metadata={"title": title, "authors": ["Imported document"], "year": year, "source_url": source_url},
            thesis=thesis,
            plain_language_summary=(
                f"Central claim: {thesis} Evaluation: {experiment_label}. Key result signal: {metric_label}. The requested concept '{query.strip()}' was also found in the extracted text."
                if query_matches and query else
                f"Central claim: {thesis} Evaluation: {experiment_label}. Key result signal: {metric_label}."
            ),
            relevance=80 if query_matches else 70,
            concepts=concepts,
            evidence=evidence,
        )

    def summarise(self, analysis: PaperAnalysis) -> tuple[str, int]:
        summary = f"{analysis.thesis} The strongest next check is the evidence behind {analysis.concepts[2].label.lower()}."
        return summary, analysis.relevance

    def compare(self, analysis: PaperAnalysis, existing_papers: list[PaperRecord]) -> list[Relationship]:
        current_text = " ".join([
            analysis.metadata.title,
            analysis.thesis,
            analysis.plain_language_summary,
            *(concept.label for concept in analysis.concepts),
            *(concept.description for concept in analysis.concepts),
        ])
        current_terms = _comparison_terms(current_text)
        relationship_type = _comparison_relationship(current_text)
        relationships: list[Relationship] = []
        for paper in existing_papers:
            other_text = " ".join([paper.title, paper.abstract or "", *paper.concepts])
            other_terms = _comparison_terms(other_text)
            overlap = current_terms & other_terms
            if overlap:
                union = current_terms | other_terms
                overlap_ratio = len(overlap) / max(1, len(union))
                confidence = min(0.95, 0.48 + overlap_ratio * 0.9 + min(len(overlap), 4) * 0.04)
                relationships.append(Relationship(
                    source_id="current-paper",
                    target_id=paper.id,
                    relationship_type=relationship_type,
                    explanation=(
                        f"Shared paper terms: {', '.join(sorted(overlap)[:6])}. "
                        f"The current paper explicitly appears to {relationship_type} the earlier work based on its extracted claims; verify in the cited evidence."
                    ),
                    confidence=confidence,
                    paper_ids=[paper.id],
                ))
        return relationships


def _json_from_model_output(output: str) -> dict[str, Any]:
    """Parse a JSON object from a provider response, including code fences."""

    cleaned = output.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.IGNORECASE | re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for start, character in enumerate(cleaned):
            if character != "{":
                continue
            try:
                payload, _ = decoder.raw_decode(cleaned[start:])
                break
            except json.JSONDecodeError:
                continue
        else:
            raise ValueError("The model did not return a JSON object")
    if not isinstance(payload, dict):
        raise ValueError("The model returned JSON, but it was not an object")
    return payload


def _provider_text(payload: dict[str, Any]) -> str:
    """Read common Bedrock response shapes without coupling agents to a model."""

    content = payload.get("content")
    if isinstance(content, list):
        text = "".join(
            str(block.get("text", ""))
            for block in content
            if isinstance(block, dict) and block.get("text")
        )
        if text:
            return text
    output = payload.get("output")
    if isinstance(output, dict):
        message = output.get("message")
        if isinstance(message, dict):
            message_content = message.get("content")
            if isinstance(message_content, list):
                text = "".join(
                    str(block.get("text", ""))
                    for block in message_content
                    if isinstance(block, dict) and block.get("text")
                )
                if text:
                    return text
    for key in ("completion", "generation", "outputText"):
        if isinstance(payload.get(key), str):
            return payload[key]
    results = payload.get("results")
    if isinstance(results, list) and results and isinstance(results[0], dict):
        for key in ("text", "outputText", "generation"):
            if isinstance(results[0].get(key), str):
                return results[0][key]
    raise ValueError("The Bedrock model returned no readable text")


def _analysis_prompt(text: str, source_url: str | None, query: str | None) -> str:
    query_instruction = (
        f"The user's optional focus is: {query.strip()}\nPrioritize that focus only when it is supported by the paper.\n"
        if query and query.strip()
        else "There is no additional user focus; analyze the paper independently.\n"
    )
    return f"""You are the research-paper analysis agent for Paper Atlas.

Analyze only the PAPER BODY below. It has already been filtered to remove browser chrome,
publisher navigation, repeated headers/footers, and references. Do not use outside facts to
invent claims. Return one JSON object and no prose outside it.

{query_instruction}
Every evidence.excerpt must be copied from the PAPER BODY (whitespace may be normalized),
and every concept must link to at least one evidence id. Use concrete names, measurements,
datasets, methods, and outcomes from the paper. Prefer a precise claim over a generic label.
The `concept` kind is for a named scientific idea, law, theory, method, dataset, or entity;
only use it when the term appears in the paper. Use one of the allowed kinds exactly:
thesis, method, finding, experiment, metric, concept.
Use evidence kinds exactly: statistic, experiment, quote, dataset, context.

The output must satisfy this shape:
{{
  "metadata": {{"title": "...", "authors": ["..."], "year": 2024, "source_url": {json.dumps(source_url)}}},
  "thesis": "one concrete central claim",
  "plain_language_summary": "short but specific summary",
  "relevance": 0,
  "concepts": [{{"id":"...","label":"...","kind":"...","description":"...","evidence_ids":["..."],"confidence":0.0}}],
  "evidence": [{{"id":"...","claim":"...","kind":"...","excerpt":"verbatim source sentence","source_location":"section or page if known","confidence":0.0}}]
}}

PAPER BODY:
{text}
"""


class BedrockResearchModel(DemoResearchModel):
    """Optional provider-backed extractor using the AWS Bedrock runtime.

    The deterministic summarisation and comparison agents remain available so
    the provider is responsible only for the part that benefits most from a
    language model: extracting paper-specific claims and evidence.
    """

    def __init__(self, settings: Settings) -> None:
        if not settings.bedrock_model_id.strip():
            raise RuntimeError(
                "PAPER_ATLAS_BEDROCK_MODEL_ID must be set when PAPER_ATLAS_MODEL_MODE=bedrock"
            )
        self.settings = settings

    def _invoke(self, prompt: str) -> str:
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - dependency is optional at runtime
            raise RuntimeError("Bedrock mode requires boto3; install the backend dependencies first") from exc

        try:
            session = boto3.Session(profile_name=self.settings.aws_profile, region_name=self.settings.aws_region)
            client = session.client("bedrock-runtime")
            model_id = self.settings.bedrock_model_id
            lowered = model_id.casefold()
            if "anthropic" in lowered:
                body: dict[str, Any] = {
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 6000,
                    "temperature": 0,
                    "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
                }
            elif "amazon.nova" in lowered:
                body = {
                    "schemaVersion": "messages-v1",
                    "inferenceConfig": {"maxTokens": 6000, "temperature": 0},
                    "messages": [{"role": "user", "content": [{"text": prompt}]}],
                }
            else:
                # This covers legacy text-completion providers such as Titan
                # and Cohere. Unsupported models return a clear provider error.
                body = {"prompt": prompt, "max_tokens_to_sample": 6000, "temperature": 0}
            response = client.invoke_model(
                modelId=model_id,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )
            raw_body = response.get("body")
            raw = raw_body.read() if hasattr(raw_body, "read") else raw_body
            payload = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
            if not isinstance(payload, dict):
                raise ValueError("The Bedrock response body was not a JSON object")
            return _provider_text(payload)
        except Exception as exc:
            raise RuntimeError(f"Bedrock analysis failed: {exc}") from exc

    def extract_scanned_documents(
        self,
        scanned_documents: list[ScannedDocument],
        source_url: str | None = None,
        query: str | None = None,
    ) -> PaperAnalysis:
        text = self.scanned_documents_to_text(scanned_documents)
        if not text.strip():
            raise ValueError("The scanned paper body is empty")
        bounded_text = text[: self.settings.max_model_input_chars]
        payload = _json_from_model_output(self._invoke(_analysis_prompt(bounded_text, source_url, query)))
        analysis = PaperAnalysis.model_validate(payload)
        if source_url and analysis.metadata.source_url is None:
            analysis = analysis.model_copy(
                update={"metadata": analysis.metadata.model_copy(update={"source_url": source_url})}
            )
        return analysis


def default_model(settings: Settings | None = None) -> ResearchModel:
    """Select the configured provider while keeping local setup zero-config."""

    if settings and settings.model_mode == "bedrock" and settings.bedrock_model_id.strip():
        return BedrockResearchModel(settings)
    return DemoResearchModel()
