import httpx
import pytest

import paper_atlas.tools.documents as documents


def _response(url: str, content_type: str, content: bytes) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": content_type},
        content=content,
        request=httpx.Request("GET", url),
    )


def test_body_filter_removes_repeated_page_chrome_and_back_matter() -> None:
    text = documents._filter_research_body([
        "Journal header\n1\nA Study of Attention\nIntroduction\nThe first body paragraph.",
        "Journal header\n2\nMethod\nThe second body paragraph.\nReferences\nReference one\nJournal header\n2",
    ])

    assert "Journal header" not in text
    assert "Reference one" not in text
    assert "The first body paragraph." in text
    assert "The second body paragraph." in text


def test_html_fallback_keeps_article_body_and_removes_page_chrome() -> None:
    html = """
    <html><head><title>Browser title</title><script>ignore()</script></head>
    <body><nav>Navigation and cookie controls</nav>
      <article><h1>Paper title</h1><p>Abstract and introduction text.</p>
      <p>Methods and results are described here.</p><h2>References</h2><p>Do not read this.</p></article>
      <footer>Footer advertisement</footer>
    </body></html>
    """

    text = documents._html_to_text(html)

    assert "Paper title" in text
    assert "Methods and results" in text
    assert "Navigation" not in text
    assert "Footer advertisement" not in text
    assert "Do not read this" not in text


def test_url_ingestion_prefers_a_linked_pdf(monkeypatch) -> None:
    page_url = "https://publisher.example/paper"
    pdf_url = "https://publisher.example/files/paper.pdf"
    responses = {
        page_url: _response(page_url, "text/html", b'<html><head><meta name="citation_pdf_url" content="/files/paper.pdf"></head><body><article>HTML fallback text</article></body></html>'),
        pdf_url: _response(pdf_url, "application/pdf", b"%PDF-1.7 fake bytes"),
    }

    monkeypatch.setattr(documents.httpx, "get", lambda url, **_: responses[url])
    monkeypatch.setattr(
        documents,
        "_extract_pdf",
        lambda content, max_chars: documents.DocumentRead(
            text="Paper title\nIntroduction\nPDF body text",
            source_url=None,
            format="pdf",
        ),
    )

    result = documents.load_document_details("url", page_url, 10_000)

    assert result.format == "pdf"
    assert result.source_url == pdf_url
    assert "PDF body text" in result.text
    assert "HTML fallback" not in result.text


def test_article_url_falls_back_when_advertised_pdf_is_not_usable(monkeypatch) -> None:
    page_url = "https://publisher.example/article"
    pdf_url = "https://publisher.example/files/paper.pdf"
    responses = {
        page_url: _response(page_url, "text/html", b'<html><body><article><h1>Research article</h1><p>The website article remains readable.</p></article><a href="/files/paper.pdf">PDF</a></body></html>'),
        pdf_url: _response(pdf_url, "text/html", b"Sign-in required"),
    }

    monkeypatch.setattr(documents.httpx, "get", lambda url, **_: responses[url])

    result = documents.load_document_details("url", page_url, 10_000)

    assert result.format == "html"
    assert result.source_url == page_url
    assert "website article remains readable" in result.text


def test_scanned_pdf_uses_ocr_fallback(monkeypatch) -> None:
    monkeypatch.setattr(documents, "_pdf_text_pages", lambda content: [""])
    monkeypatch.setattr(
        documents,
        "_ocr_pdf_pages",
        lambda content: ["Scanned paper title\nIntroduction\nThis is the OCR body text with enough words to be useful."],
    )

    result = documents._extract_pdf(b"%PDF-1.7 fake bytes", 10_000)

    assert result.ocr_used is True
    assert "OCR body text" in result.text


def test_pdf_candidates_include_dynamic_data_and_script_urls() -> None:
    html = r'''
    <button data-pdf-url="/downloads/paper.pdf?download=1">Download</button>
    <script type="application/json">
      {"pdfUrl":"https:\/\/cdn.example.org\/paper.pdf"}
    </script>
    '''

    candidates = documents._pdf_candidates(html, "https://publisher.example/article")

    assert "https://publisher.example/downloads/paper.pdf?download=1" in candidates
    assert "https://cdn.example.org/paper.pdf" in candidates


def test_url_retries_transient_browser_error_then_uses_paper(monkeypatch) -> None:
    page_url = "https://publisher.example/slow-paper"
    error_response = _response(
        page_url,
        "text/html",
        b"A required part of this site could not load. This may be due to a browser.",
    )
    good_response = _response(
        page_url,
        "text/html",
        b"<article><h1>Slow paper</h1><p>The paper body loaded after a retry and remains available.</p></article>",
    )
    responses = iter([error_response, good_response])
    monkeypatch.setattr(documents.httpx, "get", lambda url, **_: next(responses))
    monkeypatch.setattr(documents.time, "sleep", lambda _: None)

    result = documents.load_document_details("url", page_url, 10_000)

    assert result.format == "html"
    assert "paper body loaded after a retry" in result.text


def test_browser_error_page_is_not_sent_to_analysis(monkeypatch) -> None:
    page_url = "https://publisher.example/blocked-paper"
    response = _response(
        page_url,
        "text/html",
        b"<main><h1>A required part of this site couldn't load</h1><p>This may be due to a browser extension.</p></main>",
    )
    monkeypatch.setattr(documents.httpx, "get", lambda url, **_: response)
    monkeypatch.setattr(documents.time, "sleep", lambda _: None)

    with pytest.raises(documents.DocumentIngestionError, match="browser or JavaScript error page"):
        documents.load_document_details("url", page_url, 10_000)
