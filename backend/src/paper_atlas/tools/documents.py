from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
import os
import re
from urllib.parse import urljoin, urlparse

import httpx
from pypdf import PdfReader

from ..schemas import DocumentChunk


_MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
_PDF_LINK_LIMIT = 8
_PDF_SUFFIX_RE = re.compile(r"\.pdf(?:$|[?#])", re.IGNORECASE)
_STOP_SECTION_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*[\s.)-]+)?"
    r"(?:references|bibliography|works cited|acknowledg(?:e)?ments|"
    r"funding|author contributions|data availability|conflict of interest|"
    r"supplement(?:ary|al)(?: material)?|appendix|appendices)\s*:?[\s.]*$",
    re.IGNORECASE,
)
_PAGE_NUMBER_RE = re.compile(r"^(?:page\s+)?\d+(?:\s*(?:of|/|-)\s*\d+)?$", re.IGNORECASE)
_BOILERPLATE_RE = re.compile(
    r"^(?:downloaded from|this content is|all rights reserved|copyright\s|"
    r"©|licensed under|published by|available at\s+https?://)",
    re.IGNORECASE,
)
_IGNORED_HTML_TAGS = {
    "script",
    "style",
    "noscript",
    "svg",
    "nav",
    "header",
    "footer",
    "aside",
    "form",
    "button",
    "input",
    "select",
    "option",
    "iframe",
    "canvas",
    "head",
    "title",
}
_HTML_BLOCK_TAGS = {
    "article",
    "br",
    "div",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "p",
    "section",
    "table",
    "tr",
}
_VOID_HTML_TAGS = {"br", "hr", "img", "meta", "link", "input", "source", "embed", "param", "wbr"}


class DocumentIngestionError(RuntimeError):
    """Raised when a paper cannot be fetched or converted into text."""


@dataclass(frozen=True)
class DocumentRead:
    """The bounded, paper-focused representation passed to the workflow."""

    text: str
    source_url: str | None
    format: str
    ocr_used: bool = False
    warnings: tuple[str, ...] = ()


def _attrs_to_dict(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
    return {key.lower(): value.strip() for key, value in attrs if value and value.strip()}


def _is_preferred_html_container(tag: str, attrs: list[tuple[str, str | None]]) -> bool:
    if tag.lower() in {"article", "main"}:
        return True
    values = _attrs_to_dict(attrs)
    marker = f"{values.get('id', '')} {values.get('class', '')}".lower()
    return bool(re.search(r"\b(?:article|paper|full[-_ ]?text|abstract|article[-_ ]?body|content[-_ ]?body)\b", marker))


class _VisibleTextParser(HTMLParser):
    """Collect visible article text, preferring semantic paper containers."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.preferred_parts: list[str] = []
        self._stack: list[tuple[str, bool, bool]] = []

    @property
    def _ignored(self) -> bool:
        return bool(self._stack and self._stack[-1][1])

    @property
    def _preferred(self) -> bool:
        return bool(self._stack and self._stack[-1][2])

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _VOID_HTML_TAGS:
            if tag == "br" and not self._ignored:
                self.parts.append("\n")
                if self._preferred:
                    self.preferred_parts.append("\n")
            return
        inherited_ignored = self._ignored
        inherited_preferred = self._preferred
        ignored = inherited_ignored or tag in _IGNORED_HTML_TAGS
        preferred = inherited_preferred or (not ignored and _is_preferred_html_container(tag, attrs))
        self._stack.append((tag, ignored, preferred))
        if not ignored and tag in _HTML_BLOCK_TAGS:
            self.parts.append("\n")
            if preferred:
                self.preferred_parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in _VOID_HTML_TAGS:
            self.handle_starttag(tag, attrs)
            return
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self._stack:
            return
        current_tag, ignored, preferred = self._stack.pop()
        if current_tag != tag.lower():
            return
        if not ignored and tag.lower() in _HTML_BLOCK_TAGS:
            self.parts.append("\n")
            if preferred:
                self.preferred_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored:
            return
        self.parts.append(data)
        if self._preferred:
            self.preferred_parts.append(data)


class _PdfLinkParser(HTMLParser):
    """Find likely PDF links without requiring a heavyweight HTML parser."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str, str]] = []

    def _record(self, value: str | None, signal: str, kind: str = "") -> None:
        if value and value.strip():
            self.links.append((value.strip(), signal, kind))

    def _handle_attrs(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = _attrs_to_dict(attrs)
        if tag in {"a", "link"}:
            self._record(values.get("href"), values.get("type", ""), values.get("rel", ""))
        elif tag in {"iframe", "embed", "object", "source"}:
            self._record(values.get("src") or values.get("data"), values.get("type", ""), tag)
        elif tag == "meta":
            name = f"{values.get('name', '')} {values.get('property', '')}".lower()
            if "citation_pdf_url" in name or "pdf" in name:
                self._record(values.get("content"), "meta", name)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._handle_attrs(tag.lower(), attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._handle_attrs(tag.lower(), attrs)


def _normalise_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in text.replace("\x00", " ").splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if line:
            lines.append(line)
    return lines


def _edge_line_key(line: str) -> str:
    return re.sub(r"\b\d+\b", "#", line.casefold()).strip()


def _is_stop_heading(line: str) -> bool:
    return bool(_STOP_SECTION_RE.match(line))


def _filter_research_body(pages: list[str]) -> str:
    """Keep paper prose while removing page chrome and non-body sections.

    This intentionally keeps the title, abstract, keywords, and main sections:
    those are part of the paper content needed for screening. References,
    appendices, acknowledgements, and common publication boilerplate are not
    passed to the model.
    """

    page_lines = [_normalise_lines(page) for page in pages]
    edge_counts: Counter[str] = Counter()
    for lines in page_lines:
        edge_lines = lines[:4] + lines[-4:]
        edge_counts.update({key for key in (_edge_line_key(line) for line in edge_lines) if len(key) >= 3})
    repeated_edges = {key for key, count in edge_counts.items() if count >= 2}

    kept: list[str] = []
    stop = False
    for lines in page_lines:
        for index, line in enumerate(lines):
            if stop:
                break
            if _is_stop_heading(line):
                stop = True
                break
            if _BOILERPLATE_RE.match(line):
                continue
            if _PAGE_NUMBER_RE.match(line) and (index < 2 or index >= len(lines) - 2):
                continue
            if index < 4 or index >= len(lines) - 4:
                if _edge_line_key(line) in repeated_edges:
                    continue
            kept.append(line)

    # Preserve section boundaries for title detection, chunking, and readable
    # evidence excerpts without preserving the PDF's unreliable line wrapping.
    joined: list[str] = []
    for line in kept:
        if joined and joined[-1].endswith("-") and line and line[0].islower():
            joined[-1] = joined[-1][:-1] + line
        else:
            joined.append(line)
    return "\n".join(joined).strip()


def _html_to_text(html: str) -> str:
    parser = _VisibleTextParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # pragma: no cover - malformed HTML parser edge case
        raise DocumentIngestionError(f"HTML text extraction failed: {exc}") from exc
    preferred = "".join(parser.preferred_parts)
    visible = preferred if preferred.strip() else "".join(parser.parts)
    return _filter_research_body([visible])


def _pdf_text_pages(content: bytes) -> list[str]:
    reader = PdfReader(BytesIO(content))
    return [page.extract_text() or "" for page in reader.pages]


def _ocr_pdf_pages(content: bytes) -> list[str]:
    try:
        import pytesseract
        from pdf2image import convert_from_bytes
    except ImportError as exc:
        raise DocumentIngestionError(
            "This PDF appears to be scanned or image-only. Install the OCR extras "
            "with 'python -m pip install -e \".[ocr]\"', then install Tesseract OCR "
            "and Poppler and make both available on PATH."
        ) from exc

    try:
        dpi = int(os.getenv("PAPER_ATLAS_OCR_DPI", "220"))
        language = os.getenv("PAPER_ATLAS_OCR_LANG", "eng")
        images = convert_from_bytes(content, dpi=dpi, fmt="png", thread_count=1)
        return [pytesseract.image_to_string(image, lang=language, config="--psm 3") for image in images]
    except Exception as exc:  # pragma: no cover - depends on local OCR binaries
        raise DocumentIngestionError(
            "OCR could not read this PDF. Install Tesseract OCR and Poppler, "
            "ensure they are on PATH, and retry."
        ) from exc


def _is_meaningful_text(text: str) -> bool:
    alpha_count = sum(character.isalpha() for character in text)
    return len(text.strip()) >= 240 or alpha_count >= 120


def _extract_pdf(content: bytes, max_chars: int | None = None) -> DocumentRead:
    if not content.startswith(b"%PDF"):
        raise DocumentIngestionError("The downloaded file is not a valid PDF")

    try:
        pages = _pdf_text_pages(content)
        text = _filter_research_body(pages)
    except Exception as exc:  # pragma: no cover - depends on malformed PDFs
        pages = []
        text = ""
        text_error = exc
    else:
        text_error = None

    if _is_meaningful_text(text):
        return DocumentRead(text=text[:max_chars] if max_chars else text, source_url=None, format="pdf")

    try:
        ocr_pages = _ocr_pdf_pages(content)
        ocr_text = _filter_research_body(ocr_pages)
    except DocumentIngestionError as exc:
        if text:
            message = f"Selectable PDF text was limited; OCR fallback was unavailable ({exc})."
            return DocumentRead(
                text=text[:max_chars] if max_chars else text,
                source_url=None,
                format="pdf",
                warnings=(message,),
            )
        if text_error:
            raise DocumentIngestionError(f"PDF text extraction failed: {text_error}. {exc}") from exc
        raise

    if not ocr_text:
        raise DocumentIngestionError("The PDF did not contain readable paper text after OCR")
    return DocumentRead(
        text=ocr_text[:max_chars] if max_chars else ocr_text,
        source_url=None,
        format="pdf",
        ocr_used=True,
        warnings=("The PDF had limited selectable text, so OCR was used before analysis.",),
    )


def _pdf_to_text(content: bytes) -> str:
    """Backward-compatible PDF text helper used by older callers and tests."""

    return _extract_pdf(content).text


def _is_pdf_response(response: httpx.Response, requested_url: str) -> bool:
    content_type = response.headers.get("content-type", "").lower()
    return (
        response.content.startswith(b"%PDF")
        or "application/pdf" in content_type
    )


def _response_url(response: httpx.Response, fallback: str) -> str:
    return str(getattr(response, "url", "") or fallback)


def _fetch_url(url: str) -> httpx.Response:
    try:
        response = httpx.get(
            url,
            follow_redirects=True,
            timeout=25.0,
            headers={"User-Agent": "PaperAtlas/0.1 research-paper-reader"},
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise DocumentIngestionError(f"Could not fetch URL: {exc}") from exc
    if len(response.content) > _MAX_DOWNLOAD_BYTES:
        raise DocumentIngestionError("The downloaded document is larger than the 50 MB limit")
    return response


def _pdf_candidates(html: str, page_url: str) -> list[str]:
    parser = _PdfLinkParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return []

    page_host = urlparse(page_url).netloc.lower()
    scored: list[tuple[int, str]] = []
    seen: set[str] = set()
    for raw_url, signal, kind in parser.links:
        candidate = urljoin(page_url, raw_url)
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        score = 0
        if "citation_pdf_url" in kind:
            score += 120
        if "application/pdf" in signal.lower():
            score += 100
        if _PDF_SUFFIX_RE.search(candidate):
            score += 80
        if kind in {"alternate", "embed", "object", "source"}:
            score += 20
        if parsed.netloc.lower() == page_host:
            score += 5
        # Links that do not advertise a PDF are still checked when their
        # metadata came from a publisher's explicit PDF field.
        if score >= 20:
            scored.append((score, candidate))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [candidate for _, candidate in scored[:_PDF_LINK_LIMIT]]


def _extract_linked_pdf(html: str, page_url: str, max_chars: int) -> DocumentRead | None:
    for candidate_url in _pdf_candidates(html, page_url):
        try:
            response = _fetch_url(candidate_url)
        except DocumentIngestionError:
            # A page can expose stale or access-controlled PDF links. Continue
            # to the next candidate before falling back to the HTML page.
            continue
        if not _is_pdf_response(response, candidate_url):
            continue
        try:
            extracted = _extract_pdf(response.content, max_chars)
        except DocumentIngestionError:
            # The URL may end in .pdf while serving a login page, an expired
            # download, or an unsupported PDF. Keep the article URL usable.
            continue
        return DocumentRead(
            text=extracted.text,
            source_url=_response_url(response, candidate_url),
            format="pdf",
            ocr_used=extracted.ocr_used,
            warnings=extracted.warnings,
        )
    return None


def extract_uploaded_file_details(filename: str, content_type: str, content: bytes, max_chars: int) -> DocumentRead:
    """Extract only paper text from a local PDF, TXT, or Markdown upload."""

    lower_name = filename.lower()
    lower_type = content_type.lower()
    is_pdf = lower_type == "application/pdf" or lower_name.endswith(".pdf") or content.startswith(b"%PDF")
    is_text = lower_type.startswith("text/") or lower_name.endswith((".txt", ".md", ".markdown"))

    if is_pdf:
        extracted = _extract_pdf(content, max_chars)
    elif is_text:
        text = content.decode("utf-8", errors="replace")
        filtered = _filter_research_body([text])
        extracted = DocumentRead(text=filtered[:max_chars], source_url=None, format="text")
    else:
        raise DocumentIngestionError("Supported uploads are PDF, TXT, and Markdown files")

    if not extracted.text.strip():
        raise DocumentIngestionError("The uploaded file did not contain extractable paper text")
    return extracted


def extract_uploaded_file(filename: str, content_type: str, content: bytes, max_chars: int) -> str:
    """Backward-compatible upload helper returning just the extracted text."""

    return extract_uploaded_file_details(filename, content_type, content, max_chars).text


def load_document_details(source_type: str, source: str, max_chars: int) -> DocumentRead:
    """Load a paper, preferring a linked PDF over the submitted web page."""

    if source_type == "text":
        text = _filter_research_body([source.strip()])
        if not text:
            raise DocumentIngestionError("The supplied text is empty")
        return DocumentRead(text=text[:max_chars], source_url=None, format="text")

    if source_type != "url":
        raise DocumentIngestionError(f"Unsupported source type: {source_type}")

    parsed = urlparse(source)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise DocumentIngestionError("source must be a valid http(s) URL")

    response = _fetch_url(source)
    requested_url = _response_url(response, source)
    if _is_pdf_response(response, source):
        extracted = _extract_pdf(response.content, max_chars)
        return DocumentRead(
            text=extracted.text,
            source_url=requested_url,
            format="pdf",
            ocr_used=extracted.ocr_used,
            warnings=extracted.warnings,
        )

    content_type = response.headers.get("content-type", "").lower()
    if "html" in content_type or "text/html" in content_type or not content_type:
        linked_pdf = _extract_linked_pdf(response.text, requested_url, max_chars)
        if linked_pdf:
            return linked_pdf
        text = _html_to_text(response.text)
        format_name = "html"
    else:
        text = _filter_research_body([response.content.decode("utf-8", errors="replace")])
        format_name = "text"

    if not text:
        raise DocumentIngestionError("The document did not contain extractable paper text")
    return DocumentRead(
        text=text[:max_chars],
        source_url=requested_url,
        format=format_name,
        warnings=("No readable linked PDF was found; the paper-content portion of the submitted page was used.",)
        if format_name == "html"
        else (),
    )


def load_document(source_type: str, source: str, max_chars: int) -> tuple[str, str | None]:
    """Backward-compatible loader returning text and the effective source URL."""

    document = load_document_details(source_type, source, max_chars)
    return document.text, document.source_url


def chunk_text(text: str, max_chunk_chars: int, overlap: int = 350) -> list[DocumentChunk]:
    """Split text into bounded chunks while preferring paragraph/sentence breaks."""
    if len(text) <= max_chunk_chars:
        return [DocumentChunk(id="chunk-000", text=text, index=0, start_char=0, end_char=len(text))]

    chunks: list[DocumentChunk] = []
    start = 0
    index = 0
    safe_overlap = min(overlap, max_chunk_chars // 3)

    while start < len(text):
        proposed_end = min(start + max_chunk_chars, len(text))
        end = proposed_end
        if proposed_end < len(text):
            boundary = max(text.rfind("\n\n", start + max_chunk_chars // 2, proposed_end), text.rfind(". ", start + max_chunk_chars // 2, proposed_end))
            if boundary > start:
                end = boundary + (2 if text[boundary:boundary + 2] == ". " else 0)

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(DocumentChunk(id=f"chunk-{index:03d}", text=chunk, index=index, start_char=start, end_char=end))
            index += 1

        if end >= len(text):
            break
        start = max(end - safe_overlap, start + 1)

    return chunks
