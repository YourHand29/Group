"""Extract readable text and paragraph records from PDFs or plain text.

The module deliberately does not interpret paragraphs. It turns a document
into stable, addressable units for downstream analysis and citations.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
import re
from typing import BinaryIO

from pydantic import BaseModel, Field
from pypdf import PdfReader

try:
    import pytesseract
    from pdf2image import convert_from_bytes, convert_from_path
except ImportError:  # OCR remains optional for text-layer PDFs.
    pytesseract = None  # type: ignore[assignment]
    convert_from_bytes = None  # type: ignore[assignment]
    convert_from_path = None  # type: ignore[assignment]


class DocumentScanError(RuntimeError):
    """Raised when a document cannot be read into usable text."""


class Paragraph(BaseModel):
    """A paragraph extracted from one input document."""

    id: str
    text: str
    index: int = Field(ge=0)
    page_number: int | None = Field(default=None, ge=1)
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)


class ScannedDocument(BaseModel):
    """Normalized document text together with its ordered paragraphs."""

    text: str
    paragraphs: list[Paragraph]
    page_count: int | None = Field(default=None, ge=1)
    source_text: str | None = None


_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n+")
_WHITESPACE = re.compile(r"[ \t\n]+")


def _normalise_paragraph(block: str) -> str:
    """Join PDF line wrapping without joining words split by a hyphen."""
    block = re.sub(r"(?<=\w)-[ \t]*\n[ \t]*(?=\w)", "", block)
    return _WHITESPACE.sub(" ", block).strip()


def split_paragraphs(text: str, *, page_number: int | None = None, start_index: int = 0) -> list[Paragraph]:
    """Separate blank-line-delimited paragraphs and retain source offsets.

    PDF extractors commonly wrap visual lines with a single newline. Single
    newlines are converted to spaces, while blank lines remain paragraph
    boundaries.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    source = text.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs: list[Paragraph] = []
    cursor = 0
    for block in _PARAGRAPH_BREAK.split(source):
        block_start = source.find(block, cursor)
        cursor = block_start + len(block)
        cleaned = _normalise_paragraph(block)
        if not cleaned:
            continue
        paragraphs.append(
            Paragraph(
                id="",  # IDs are assigned after pages have been combined.
                text=cleaned,
                index=start_index + len(paragraphs),
                page_number=page_number,
                start_char=block_start,
                end_char=cursor,
            )
        )
    return paragraphs


def scan_text_document(text: str) -> ScannedDocument:
    """Scan plain text and return normalized text plus paragraph records."""
    paragraphs = split_paragraphs(text)
    if not paragraphs:
        raise DocumentScanError("The supplied text does not contain any paragraphs")
    for paragraph in paragraphs:
        paragraph.id = f"paragraph-{paragraph.index:04d}"
    return ScannedDocument(text="\n\n".join(p.text for p in paragraphs), paragraphs=paragraphs, source_text=text)


PdfSource = str | Path | bytes | BinaryIO


def _prepare_pdf_source(source: PdfSource) -> tuple[object, bytes | None]:
    """Return a pypdf source and optional bytes for rendering an OCR page."""
    if isinstance(source, bytes):
        return BytesIO(source), source
    if isinstance(source, (str, Path)):
        return source, None
    if not hasattr(source, "read"):
        raise TypeError("source must be a path, bytes, or binary file object")

    content = source.read()
    if not isinstance(content, bytes):
        raise TypeError("binary file objects must return bytes")
    return BytesIO(content), content


def _ocr_pdf_page(source: PdfSource, page_number: int, source_bytes: bytes | None) -> str:
    """Render and OCR exactly one page, preserving OCR as a true fallback."""
    if pytesseract is None or convert_from_bytes is None or convert_from_path is None:
        raise DocumentScanError(
            "OCR support is not installed. Install the backend OCR extras and "
            "the Tesseract OCR and Poppler executables before reading scanned PDFs."
        )
    conversion_args = {"first_page": page_number, "last_page": page_number}
    if source_bytes is not None:
        images = convert_from_bytes(source_bytes, **conversion_args)
    else:
        images = convert_from_path(str(source), **conversion_args)
    if not images:
        raise DocumentScanError(f"Could not render PDF page {page_number} for OCR")
    return pytesseract.image_to_string(images[0])


def scan_pdf_document(source: PdfSource) -> ScannedDocument:
    """Extract text from a PDF and separate paragraphs page by page.

    Each page uses its embedded text layer when available. Pages with no text
    layer are rendered and processed with Tesseract OCR as a fallback.
    """
    try:
        reader_source, source_bytes = _prepare_pdf_source(source)
        reader = PdfReader(reader_source)
    except Exception as exc:  # pragma: no cover - pypdf error types vary
        raise DocumentScanError(f"Could not open PDF: {exc}") from exc

    paragraphs: list[Paragraph] = []
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            page_text = (page.extract_text() or "").strip()
        except Exception as exc:  # pragma: no cover - malformed page-specific PDFs
            raise DocumentScanError(f"Could not extract text from page {page_number}: {exc}") from exc
        if not page_text:
            try:
                page_text = _ocr_pdf_page(source, page_number, source_bytes).strip()
            except Exception as exc:  # pragma: no cover - external OCR/runtime failures
                raise DocumentScanError(f"Could not OCR page {page_number}: {exc}") from exc
        paragraphs.extend(
            split_paragraphs(page_text, page_number=page_number, start_index=len(paragraphs))
        )
    if not paragraphs:
        raise DocumentScanError(
            "The PDF did not contain any usable text after extraction and OCR."
        )
    for paragraph in paragraphs:
        paragraph.id = f"paragraph-{paragraph.index:04d}"
    return ScannedDocument(
        text="\n\n".join(p.text for p in paragraphs),
        paragraphs=paragraphs,
        page_count=len(reader.pages),
    )
