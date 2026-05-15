from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from grimmory_bridge.epub import embed_epub
from grimmory_bridge.opf import parse_opf
from grimmory_bridge.pdf import embed_pdf


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _sample_epub(path: Path) -> None:
    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""
    opf_xml = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="uid" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Old Title</dc:title>
    <dc:creator id="creator1">Old Author</dc:creator>
    <dc:language>en</dc:language>
  </metadata>
  <manifest></manifest>
  <spine></spine>
</package>
"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            zipfile.ZipInfo("mimetype"),
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr("META-INF/container.xml", container_xml)
        archive.writestr("OEBPS/content.opf", opf_xml)


def _sample_pdf(path: Path) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with path.open("wb") as handle:
        writer.write(handle)


def _sample_encrypted_pdf(path: Path, password: str) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.encrypt(password, use_128bit=True)
    with path.open("wb") as handle:
        writer.write(handle)


def test_parse_opf_fixtures() -> None:
    fixtures = [
        (
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Fixture One</dc:title>
    <dc:creator>Author A</dc:creator>
    <dc:identifier id="isbn">ISBN 978-1-4028-9462-6</dc:identifier>
    <meta name="calibre:series" content="Series One" />
    <meta name="calibre:series_index" content="2" />
  </metadata>
</package>
""",
            {
                "title": "Fixture One",
                "authors": ["Author A"],
                "isbn13": "9781402894626",
                "isbn10": "1402894627",
                "series": {"name": "Series One", "number": 2},
            },
        ),
        (
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Fixture Two</dc:title>
    <dc:creator>Author B</dc:creator>
    <dc:identifier>ISBN 1-4028-9462-7</dc:identifier>
    <dc:subject>Fantasy</dc:subject>
    <dc:subject>Action</dc:subject>
  </metadata>
</package>
""",
            {
                "title": "Fixture Two",
                "authors": ["Author B"],
                "isbn10": "1402894627",
                "isbn13": "9781402894626",
                "categories": ["Fantasy", "Action"],
            },
        ),
        (
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Fixture Three</dc:title>
    <dc:language>th</dc:language>
  </metadata>
</package>
""",
            {
                "title": "Fixture Three",
                "language": "th",
            },
        ),
    ]

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for idx, (xml, expected) in enumerate(fixtures, start=1):
            opf_path = root / f"fixture-{idx}.opf"
            _write(opf_path, xml)
            actual = parse_opf(opf_path)
            for key, value in expected.items():
                assert actual.get(key) == value


def test_embed_epub_round_trip() -> None:
    metadata = {
        "title": "Round Trip Book",
        "authors": ["Author A", "Author B"],
        "publisher": "Kadokawa",
        "publishedDate": "2024-05-17",
        "description": "Example description",
        "language": "th",
        "categories": ["Fantasy", "Action"],
        "isbn13": "9786161234567",
        "series": {"name": "Series Name", "number": 2},
    }

    with tempfile.TemporaryDirectory() as tmp:
        epub_path = Path(tmp) / "Book.epub"
        _sample_epub(epub_path)

        changed = embed_epub(epub_path, metadata, {})
        assert changed is True

        with zipfile.ZipFile(epub_path, "r") as archive:
            opf_text = archive.read("OEBPS/content.opf").decode("utf-8")

        assert "Round Trip Book" in opf_text
        assert "Author A" in opf_text
        assert "Author B" in opf_text
        assert "urn:isbn:9786161234567" in opf_text
        assert "belongs-to-collection" in opf_text
        assert "Series Name" in opf_text


def test_embed_pdf_xmp_rewrite() -> None:
    metadata = {
        "title": "PDF Book",
        "authors": ["Author A", "Author B"],
        "publisher": "Kadokawa",
        "publishedDate": "2024-05-17",
        "description": "Example description",
        "language": "th",
        "categories": ["Fantasy", "Action"],
        "isbn13": "9786161234567",
        "series": {"name": "Series Name", "number": 2},
    }

    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "Book.pdf"
        _sample_pdf(pdf_path)

        changed = embed_pdf(pdf_path, metadata, {})
        assert changed is True

        reader = PdfReader(str(pdf_path))
        assert reader.metadata.get("/Title") == "PDF Book"
        assert reader.metadata.get("/Author") == "Author A, Author B"

        xmp_bytes = reader.xmp_metadata.stream.get_data()
        xmp_text = xmp_bytes.decode("utf-8", errors="ignore")
        assert "booklore:seriesName" in xmp_text
        assert "Series Name" in xmp_text
        assert "xmpidq:Scheme" in xmp_text
        assert "isbn13" in xmp_text


def test_embed_pdf_encrypted_round_trip() -> None:
    metadata = {
        "title": "Protected PDF",
        "authors": ["Author Locked"],
    }

    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "Protected.pdf"
        _sample_encrypted_pdf(pdf_path, "secret")

        changed = embed_pdf(pdf_path, metadata, {"pdf_password": "secret", "pdf_reencrypt": True})
        assert changed is True

        encrypted_reader = PdfReader(str(pdf_path))
        assert encrypted_reader.is_encrypted
        assert int(encrypted_reader.decrypt("secret")) > 0
        assert encrypted_reader.metadata.get("/Title") == "Protected PDF"
        assert encrypted_reader.metadata.get("/Author") == "Author Locked"


def test_embed_pdf_encrypted_missing_password_raises() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "Protected.pdf"
        _sample_encrypted_pdf(pdf_path, "secret")

        try:
            embed_pdf(pdf_path, {"title": "Nope"}, {})
        except RuntimeError as exc:
            assert "decrypt PDF" in str(exc)
        else:
            raise AssertionError("Expected RuntimeError for encrypted PDF without password")


def test_embed_pdf_encrypted_aes_reencrypt_support() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "Protected.pdf"
        _sample_encrypted_pdf(pdf_path, "secret")

        has_crypto = True
        try:
            import cryptography  # noqa: F401
        except Exception:
            has_crypto = False

        try:
            changed = embed_pdf(
                pdf_path,
                {"title": "AES wanted"},
                {"pdf_password": "secret", "pdf_reencrypt": True, "pdf_encrypt_algorithm": "AES-256"},
            )
        except RuntimeError as exc:
            if has_crypto:
                raise
            assert "cryptography>=3.1" in str(exc)
        else:
            assert changed is True
            reader = PdfReader(str(pdf_path))
            assert reader.is_encrypted
            assert int(reader.decrypt("secret")) > 0
            assert reader.metadata.get("/Title") == "AES wanted"
