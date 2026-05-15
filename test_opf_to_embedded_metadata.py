import tempfile
import unittest
import json
import zipfile
from pathlib import Path

import opf_to_embedded_metadata as embedder


SAMPLE_OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="uid" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Book Title</dc:title>
    <dc:creator>Author A</dc:creator>
    <dc:creator>Author B</dc:creator>
    <dc:publisher>Kadokawa</dc:publisher>
    <dc:date>2024-05-17</dc:date>
    <dc:description>Example description</dc:description>
    <dc:language>th</dc:language>
    <dc:subject>Fantasy</dc:subject>
    <dc:subject>Action</dc:subject>
    <dc:identifier id="isbn">ISBN 978-616-123-456-7</dc:identifier>
    <meta name="calibre:series" content="Series Name" />
    <meta name="calibre:series_index" content="2" />
  </metadata>
</package>
"""


def create_sample_pdf(path: Path) -> None:
    writer = embedder.PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with path.open("wb") as handle:
        writer.write(handle)


def create_sample_epub(path: Path) -> None:
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


class EmbeddedMetadataTests(unittest.TestCase):
    def test_write_pdf_metadata_embeds_info_and_xmp(self) -> None:
        metadata = {
            "title": "Book Title",
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
            pdf_path = Path(tmp) / "Book Title.pdf"
            create_sample_pdf(pdf_path)

            changed = embedder.write_pdf_metadata(pdf_path, metadata)

            self.assertTrue(changed)
            reader = embedder.PdfReader(str(pdf_path))
            self.assertEqual(reader.metadata.get("/Title"), "Book Title")
            self.assertEqual(reader.metadata.get("/Author"), "Author A, Author B")
            self.assertEqual(reader.metadata.get("/EBX_PUBLISHER"), "Kadokawa")
            self.assertEqual(reader.metadata.get("/Publisher"), "Kadokawa")
            self.assertEqual(reader.metadata.get("/Language"), "th")
            self.assertEqual(reader.metadata.get("/Keywords"), "Fantasy; Action")
            self.assertEqual(reader.metadata.get("/CreationDate"), "D:20240517000000")
            xmp_bytes = reader.xmp_metadata.stream.get_data()
            xmp_text = xmp_bytes.decode("utf-8", errors="ignore")
            self.assertIn("booklore:seriesName", xmp_text)
            self.assertIn("Series Name", xmp_text)
            self.assertIn("xmpidq:Scheme", xmp_text)
            self.assertIn("isbn13", xmp_text)
            self.assertEqual(xmp_text.count("<rdf:Description"), 1)
            description_start = xmp_text.index("<rdf:Description")
            description_end = xmp_text.index("</rdf:Description>") + len("</rdf:Description>")
            first_description = xmp_text[description_start:description_end]
            self.assertIn("xmlns:calibre=", xmp_text)
            self.assertIn("xmlns:calibreSI=", xmp_text)
            self.assertIn("<calibre:series>", first_description)
            self.assertIn("<rdf:value>Series Name</rdf:value>", first_description)
            self.assertIn("<calibreSI:series_index>2</calibreSI:series_index>", first_description)
            self.assertIn("<booklore:seriesName>Series Name</booklore:seriesName>", first_description)
            self.assertIn("<booklore:seriesNumber>2</booklore:seriesNumber>", first_description)
            self.assertIn("<xmpidq:Scheme>isbn13</xmpidq:Scheme>", first_description)

    def test_write_pdf_metadata_removes_orphaned_stale_xmp_streams(self) -> None:
        metadata = {
            "title": "Fresh Title",
            "authors": ["Author A"],
            "publisher": "Kadokawa",
            "publishedDate": "2024-05-17",
            "description": "Example description",
            "language": "th",
            "categories": ["Fantasy"],
            "isbn13": "9786161234567",
            "series": {"name": "Series Name", "number": 2},
        }
        stale_marker = "STALE_XMP_SENTINEL_12345"
        stale_xmp = (
            "<x:xmpmeta xmlns:x='adobe:ns:meta/'>"
            "<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>"
            "<rdf:Description>"
            f"<dc:title xmlns:dc='http://purl.org/dc/elements/1.1/'>{stale_marker}</dc:title>"
            "</rdf:Description>"
            "</rdf:RDF>"
            "</x:xmpmeta>"
        ).encode("utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "Book Title.pdf"
            create_sample_pdf(pdf_path)

            reader = embedder.PdfReader(str(pdf_path))
            writer = embedder.PdfWriter()
            writer.clone_document_from_reader(reader)
            writer.xmp_metadata = embedder.build_pdf_xmp({"title": "Old Title"})

            from pypdf.generic import DecodedStreamObject, NameObject

            stale_stream = DecodedStreamObject()
            stale_stream.set_data(stale_xmp)
            stale_stream[NameObject("/Type")] = NameObject("/Metadata")
            writer._add_object(stale_stream)

            with pdf_path.open("wb") as handle:
                writer.write(handle)

            before_bytes = pdf_path.read_bytes()
            self.assertIn(stale_marker.encode("utf-8"), before_bytes)

            changed = embedder.write_pdf_metadata(pdf_path, metadata)
            self.assertTrue(changed)

            after_bytes = pdf_path.read_bytes()
            self.assertNotIn(stale_marker.encode("utf-8"), after_bytes)

            updated_reader = embedder.PdfReader(str(pdf_path))
            updated_xmp = updated_reader.xmp_metadata.stream.get_data().decode("utf-8", errors="ignore")
            self.assertIn("Fresh Title", updated_xmp)

    def test_write_epub_metadata_updates_internal_opf(self) -> None:
        metadata = {
            "title": "Book Title",
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
            epub_path = Path(tmp) / "Book Title.epub"
            create_sample_epub(epub_path)

            changed = embedder.write_epub_metadata(epub_path, metadata)

            self.assertTrue(changed)
            with zipfile.ZipFile(epub_path, "r") as archive:
                opf_text = archive.read("OEBPS/content.opf").decode("utf-8")
            self.assertIn("Book Title", opf_text)
            self.assertIn("Author A", opf_text)
            self.assertIn("Author B", opf_text)
            self.assertIn("Kadokawa", opf_text)
            self.assertIn("Example description", opf_text)
            self.assertIn("urn:isbn:9786161234567", opf_text)
            self.assertIn("belongs-to-collection", opf_text)
            self.assertIn("collection-type", opf_text)
            self.assertIn("group-position", opf_text)
            self.assertIn('name="calibre:series"', opf_text)
            self.assertIn('name="calibre:series_index"', opf_text)
            self.assertIn("Series Name", opf_text)

    def test_compatibility_report_includes_target_sections(self) -> None:
        metadata = {
            "title": "Book Title",
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
            epub_path = Path(tmp) / "Book Title.epub"
            create_sample_epub(epub_path)
            embedder.write_epub_metadata(epub_path, metadata)

            lines = embedder.build_compatibility_report_lines(epub_path)
            joined = "\n".join(lines)

            self.assertIn("COMPATIBILITY REPORT", joined)
            self.assertIn("Format: EPUB", joined)
            self.assertIn("OPF version: 3.0", joined)
            self.assertIn("KOReader", joined)
            self.assertIn("Grimmory", joined)
            self.assertIn("Calibre", joined)
            self.assertIn("series source: EPUB3 collection markers plus calibre:series fallback", joined)
            self.assertIn("title: ok -> Book Title", joined)
            self.assertIn("series: ok -> Series Name #2", joined)

    def test_scan_library_matches_same_stem_opf_with_epub(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            opf_path = root / "Book 1.opf"
            epub_path = root / "Book 1.epub"
            opf_path.write_text(SAMPLE_OPF, encoding="utf-8")
            create_sample_epub(epub_path)

            logs: list[str] = []
            stats = embedder.scan_library(
                root=root,
                allowed_exts={".epub"},
                write=True,
                log=logs.append,
            )

            self.assertEqual(stats.opf_files_found, 1)
            self.assertEqual(stats.book_files_found, 1)
            self.assertEqual(stats.files_updated, 1)
            self.assertEqual(stats.json_planned, 1)
            self.assertEqual(stats.json_created, 1)
            json_path = embedder.metadata_json_path(epub_path)
            self.assertTrue(json_path.exists())
            sidecar = json.loads(json_path.read_text(encoding="utf-8"))
            joined = "\n".join(logs)
            self.assertIn("FILE", joined)
            self.assertIn("COMPATIBILITY", joined)
            self.assertIn("KOReader : OK", joined)
            self.assertIn("JSON", joined)
            self.assertIn("mode: write", joined)
            self.assertEqual(sidecar["generatedBy"], "booklore")
            self.assertEqual(sidecar["metadata"]["title"], "Book Title")
            self.assertEqual(sidecar["metadata"]["series"]["name"], "Series Name")
            with zipfile.ZipFile(epub_path, "r") as archive:
                opf_text = archive.read("OEBPS/content.opf").decode("utf-8")
            self.assertIn("Book Title", opf_text)
            self.assertIn("Series Name", opf_text)

    def test_scan_library_same_stem_multiple_formats_writes_one_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            opf_path = root / "Book 1.opf"
            pdf_path = root / "Book 1.pdf"
            epub_path = root / "Book 1.epub"
            opf_path.write_text(SAMPLE_OPF, encoding="utf-8")
            create_sample_pdf(pdf_path)
            create_sample_epub(epub_path)

            logs: list[str] = []
            stats = embedder.scan_library(
                root=root,
                allowed_exts={".pdf", ".epub"},
                write=True,
                log=logs.append,
            )

            self.assertEqual(stats.opf_files_found, 1)
            self.assertEqual(stats.book_files_found, 2)
            self.assertEqual(stats.files_planned, 2)
            self.assertEqual(stats.json_planned, 1)
            self.assertEqual(stats.json_created, 1)
            self.assertEqual(stats.files_updated + stats.files_unchanged, 2)
            self.assertIn("SKIP duplicate JSON target", "\n".join(logs))
            self.assertTrue(embedder.metadata_json_path(pdf_path).exists())
            self.assertTrue(embedder.metadata_json_path(epub_path).exists())

    def test_scan_library_matches_same_stem_opf_with_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            opf_path = root / "Book 1.opf"
            pdf_path = root / "Book 1.pdf"
            jpg_path = root / "Book 1.jpg"
            opf_path.write_text(SAMPLE_OPF, encoding="utf-8")
            create_sample_pdf(pdf_path)
            jpg_path.write_bytes(b"jpg")

            logs: list[str] = []
            stats = embedder.scan_library(
                root=root,
                allowed_exts={".pdf"},
                write=True,
                log=logs.append,
            )

            self.assertEqual(stats.opf_files_found, 1)
            self.assertEqual(stats.book_files_found, 1)
            self.assertEqual(stats.files_updated, 1)
            self.assertEqual(stats.json_planned, 1)
            self.assertEqual(stats.json_created, 1)
            json_path = embedder.metadata_json_path(pdf_path)
            cover_path = root / "Book 1.cover.jpg"
            self.assertTrue(json_path.exists())
            self.assertTrue(cover_path.exists())
            self.assertTrue(jpg_path.exists())
            sidecar = json.loads(json_path.read_text(encoding="utf-8"))
            joined = "\n".join(logs)
            self.assertIn("FILE", joined)
            self.assertIn("mode: write", joined)
            self.assertIn("JSON", joined)
            self.assertIn("Book 1.cover.jpg", joined)
            self.assertIn("title: [empty] -> Book Title", joined)
            self.assertIn("UPDATED ", joined)
            self.assertEqual(sidecar["generatedBy"], "booklore")
            self.assertEqual(sidecar["metadata"]["title"], "Book Title")
            self.assertEqual(sidecar["metadata"]["series"]["name"], "Series Name")
            self.assertEqual(sidecar["cover"]["path"], "Book 1.cover.jpg")
            reader = embedder.PdfReader(str(pdf_path))
            self.assertEqual(reader.metadata.get("/Title"), "Book Title")

    def test_dry_run_logs_preview_of_metadata_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            opf_path = root / "Book 1.opf"
            pdf_path = root / "Book 1.pdf"
            opf_path.write_text(SAMPLE_OPF, encoding="utf-8")
            create_sample_pdf(pdf_path)

            logs: list[str] = []
            stats = embedder.scan_library(
                root=root,
                allowed_exts={".pdf"},
                write=False,
                log=logs.append,
            )

            self.assertEqual(stats.files_planned, 1)
            joined = "\n".join(logs)
            self.assertIn("FILE", joined)
            self.assertIn("mode: dry-run", joined)
            self.assertIn("COMPATIBILITY", joined)
            self.assertIn("KOReader : OK", joined)
            self.assertIn("JSON", joined)
            self.assertIn("title: [empty] -> Book Title", joined)
            self.assertIn("authors: [empty] -> Author A | Author B", joined)
            self.assertIn("publisher: [empty] -> Kadokawa", joined)
            self.assertIn("publishedDate: [empty] -> 2024-05-17", joined)
            self.assertIn("categories: [empty] -> Fantasy; Action", joined)
            self.assertIn("series: [empty] -> Series Name #2", joined)


if __name__ == "__main__":
    unittest.main()
