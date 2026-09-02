from __future__ import annotations

from html.parser import HTMLParser
from io import BytesIO
import re
from urllib.parse import urlparse

import httpx
from pypdf import PdfReader

from ..schemas import DocumentChunk


class DocumentIngestionError(RuntimeError):
    """Raised when a paper cannot be fetched or converted into text."""


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1
        elif self._ignored_depth == 0:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1
        elif self._ignored_depth == 0:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self.parts.append(data)


def _html_to_text(html: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(html)
    return re.sub(r"\s+", " ", "".join(parser.parts)).strip()


def _pdf_to_text(content: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except Exception as exc:  # pragma: no cover - depends on malformed PDFs
        raise DocumentIngestionError(f"PDF text extraction failed: {exc}") from exc


def extract_uploaded_file(filename: str, content_type: str, content: bytes, max_chars: int) -> str:
    """Extract text from a local upload without requiring internet access."""
    lower_name = filename.lower()
    is_pdf = content_type.lower() == "application/pdf" or lower_name.endswith(".pdf")
    is_text = content_type.lower().startswith("text/") or lower_name.endswith((".txt", ".md"))

    if is_pdf:
        text = _pdf_to_text(content)
    elif is_text:
        text = content.decode("utf-8", errors="replace")
    else:
        raise DocumentIngestionError("Supported uploads are PDF, TXT, and Markdown files")

    text = text.strip()
    if not text:
        raise DocumentIngestionError("The uploaded file did not contain extractable text")
    return text[:max_chars]


def load_document(source_type: str, source: str, max_chars: int) -> tuple[str, str | None]:
    """Load text from a direct text input or an HTTP(S) document URL."""
    if source_type == "text":
        text = source.strip()
        if not text:
            raise DocumentIngestionError("The supplied text is empty")
        return text[:max_chars], None

    if source_type != "url":
        raise DocumentIngestionError(f"Unsupported source type: {source_type}")

    parsed = urlparse(source)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise DocumentIngestionError("source must be a valid http(s) URL")

    try:
        response = httpx.get(source, follow_redirects=True, timeout=20.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise DocumentIngestionError(f"Could not fetch URL: {exc}") from exc

    content_type = response.headers.get("content-type", "").lower()
    if "application/pdf" in content_type or source.lower().split("?", 1)[0].endswith(".pdf"):
        text = _pdf_to_text(response.content)
    elif "html" in content_type:
        text = _html_to_text(response.text)
    else:
        text = response.text

    text = text.strip()
    if not text:
        raise DocumentIngestionError("The document did not contain extractable text")
    return text[:max_chars], source


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
