import io
import zipfile

import pytest

from app.documents import UnsupportedDocument, extract_text


def minimal_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = io.BytesIO(), []
    out.write(b"%PDF-1.4\n")
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % number + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for offset in offsets:
        out.write(b"%010d 00000 n \n" % offset)
    out.write(
        b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    )
    return out.getvalue()


def minimal_docx(paragraphs: list[str]) -> bytes:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    xml = f'<?xml version="1.0"?><w:document xmlns:w="{ns}"><w:body>{body}</w:body></w:document>'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


def test_extracts_pdf_text():
    text = extract_text(minimal_pdf("Offerors must be ISO 27001 certified."), filename="sow.pdf")
    assert "Offerors must be ISO 27001 certified." in text


def test_extracts_docx_paragraphs():
    content = minimal_docx(["Cloud migration services", "Past performance required"])
    assert extract_text(content, filename="cap.docx") == (
        "Cloud migration services\nPast performance required"
    )


def test_extracts_plain_and_html_text():
    assert extract_text(b"Hello  world", filename="a.txt") == "Hello world"
    assert extract_text(b"<p>Hello</p><p>there</p>", content_type="text/html") == "Hello\n\nthere"


def test_rejects_unsupported_and_corrupt_files():
    with pytest.raises(UnsupportedDocument):
        extract_text(b"\x00\x01", filename="drawing.dwg")
    with pytest.raises(UnsupportedDocument):
        extract_text(b"not a zip", filename="broken.docx")
