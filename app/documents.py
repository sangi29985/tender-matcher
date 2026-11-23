"""Plain-text extraction from the document types tenders and companies usually share."""

import io
import logging
import re
import zipfile
from xml.etree import ElementTree

from pypdf import PdfReader
from pypdf.errors import PdfReadError

logger = logging.getLogger(__name__)

MAX_PDF_PAGES = 150
_WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class UnsupportedDocument(ValueError):
    pass


def _kind(content: bytes, content_type: str, filename: str) -> str:
    name = filename.lower()
    content_type = content_type.lower()
    if content.startswith(b"%PDF") or "pdf" in content_type or name.endswith(".pdf"):
        return "pdf"
    if name.endswith(".docx") or "wordprocessingml" in content_type:
        return "docx"
    if name.endswith((".txt", ".md", ".csv", ".htm", ".html")) or content_type.startswith("text/"):
        return "text"
    return "unknown"


def _pdf_text(content: bytes) -> str:
    reader = PdfReader(io.BytesIO(content))
    pages = []
    for index, page in enumerate(reader.pages):
        if index >= MAX_PDF_PAGES:
            pages.append(f"[Stopped after {MAX_PDF_PAGES} pages]")
            break
        pages.append(page.extract_text() or "")
    return "\n\n".join(pages)


def _docx_text(content: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    paragraphs = []
    for paragraph in root.iter(f"{_WORD_NAMESPACE}p"):
        text = "".join(node.text or "" for node in paragraph.iter(f"{_WORD_NAMESPACE}t"))
        if text.strip():
            paragraphs.append(text)
    return "\n".join(paragraphs)


def extract_text(content: bytes, *, content_type: str = "", filename: str = "") -> str:
    """Return the readable text of a PDF, DOCX, HTML or plain-text document."""
    kind = _kind(content, content_type, filename)
    try:
        if kind == "pdf":
            text = _pdf_text(content)
        elif kind == "docx":
            text = _docx_text(content)
        elif kind == "text":
            from app.samgov import html_to_text

            text = content.decode("utf-8", errors="replace")
            if "<" in text and ">" in text:
                text = html_to_text(text)
        else:
            raise UnsupportedDocument(f"Unsupported file type: {filename or content_type}")
    except (PdfReadError, zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
        raise UnsupportedDocument(f"Could not read {filename or 'document'}") from exc
    return re.sub(r"[ \t]+", " ", text).strip()
