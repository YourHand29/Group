from paper_atlas.agents.scan_text import scan_pdf_document, scan_text_document, split_paragraphs


def test_scan_text_document_separates_blank_line_paragraphs_and_unwraps_lines() -> None:
    result = scan_text_document(
        "First paragraph is wrapped\nover two lines.\n\nSecond para-\ngraph is here."
    )

    assert result.text == "First paragraph is wrapped over two lines.\n\nSecond paragraph is here."
    assert [paragraph.id for paragraph in result.paragraphs] == [
        "paragraph-0000",
        "paragraph-0001",
    ]
    assert result.paragraphs[1].start_char < result.paragraphs[1].end_char


def test_split_paragraphs_keeps_page_context() -> None:
    paragraphs = split_paragraphs("One.\n\nTwo.", page_number=3, start_index=7)

    assert [paragraph.index for paragraph in paragraphs] == [7, 8]
    assert all(paragraph.page_number == 3 for paragraph in paragraphs)


def test_scan_pdf_uses_ocr_only_for_pages_without_embedded_text(monkeypatch) -> None:
    class FakePage:
        def __init__(self, text: str) -> None:
            self.text = text

        def extract_text(self) -> str:
            return self.text

    class FakeReader:
        pages = [FakePage("Embedded text."), FakePage("")]

    ocr_calls: list[int] = []
    monkeypatch.setattr("paper_atlas.agents.scan_text.PdfReader", lambda _: FakeReader())
    monkeypatch.setattr(
        "paper_atlas.agents.scan_text._ocr_pdf_page",
        lambda _source, page_number, _source_bytes: ocr_calls.append(page_number) or "OCR text.",
    )

    result = scan_pdf_document("example.pdf")

    assert [paragraph.text for paragraph in result.paragraphs] == ["Embedded text.", "OCR text."]
    assert [paragraph.page_number for paragraph in result.paragraphs] == [1, 2]
    assert ocr_calls == [2]
