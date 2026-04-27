import tempfile
import unittest
from pathlib import Path

import opf_to_grimmory_json as converter


class OpfConverterTests(unittest.TestCase):
    def test_normalize_extensions(self) -> None:
        self.assertEqual(
            converter.normalize_extensions("pdf, epub,CBZ"),
            {".pdf", ".epub", ".cbz"},
        )

    def test_target_json_path(self) -> None:
        self.assertEqual(
            converter.target_json_path(Path("My Book.pdf")),
            Path("My Book.metadata.json"),
        )

    def test_normalize_date_returns_date_only_for_datetime_values(self) -> None:
        self.assertEqual(
            converter.normalize_date("2009-12-31T17:00:00+00:00"),
            "2009-12-31",
        )
        self.assertEqual(
            converter.normalize_date("2026-04-25T06:43:00.310808Z"),
            "2026-04-25",
        )

    def test_iter_opf_files_is_case_insensitive_and_accepts_any_opf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "A").mkdir()
            (root / "B").mkdir()
            (root / "A" / "Metadata.OPF").write_text("<package />", encoding="utf-8")
            (root / "B" / "book.opf").write_text("<package />", encoding="utf-8")
            (root / "B" / "note.txt").write_text("x", encoding="utf-8")

            found = converter.iter_opf_files(root)

        self.assertEqual(
            [path.name for path in found],
            ["Metadata.OPF", "book.opf"],
        )

    def test_discover_book_files_for_named_opf_matches_same_stem_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            opf_path = root / "Volume 1.opf"
            opf_path.write_text("<package />", encoding="utf-8")
            (root / "Volume 1.pdf").write_text("pdf", encoding="utf-8")
            (root / "Volume 2.pdf").write_text("pdf", encoding="utf-8")

            found = converter.discover_book_files_for_opf(opf_path, set())

        self.assertEqual(found, [root / "Volume 1.pdf"])

    def test_find_cover_for_named_opf_prefers_same_stem_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            opf_path = root / "Volume 1.opf"
            book_path = root / "Volume 1.pdf"
            opf_path.write_text("<package />", encoding="utf-8")
            book_path.write_text("pdf", encoding="utf-8")
            (root / "Volume 1.jpg").write_text("img", encoding="utf-8")
            (root / "cover.jpg").write_text("img", encoding="utf-8")

            cover_name = converter.find_cover_for_opf(opf_path, book_path)

        self.assertEqual(cover_name, "Volume 1.jpg")

    def test_extract_metadata(self) -> None:
        opf = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>หนังสือทดสอบ</dc:title>
    <dc:creator>ผู้เขียน A</dc:creator>
    <dc:creator>ผู้เขียน B</dc:creator>
    <dc:publisher>สำนักพิมพ์ตัวอย่าง</dc:publisher>
    <dc:date>2024-01-05</dc:date>
    <dc:description>คำอธิบาย</dc:description>
    <dc:language>th</dc:language>
    <dc:subject>หมวดหนึ่ง</dc:subject>
    <dc:subject>หมวดสอง</dc:subject>
    <dc:identifier id="isbn">ISBN 978-1-4028-9462-6</dc:identifier>
    <meta name="calibre:series" content="ชุดตัวอย่าง" />
    <meta name="calibre:series_index" content="2" />
  </metadata>
</package>
"""
        with tempfile.TemporaryDirectory() as tmp:
            opf_path = Path(tmp) / "metadata.opf"
            opf_path.write_text(opf, encoding="utf-8")
            metadata = converter.extract_metadata(opf_path)

        self.assertEqual(metadata["title"], "หนังสือทดสอบ")
        self.assertEqual(metadata["authors"], ["ผู้เขียน A", "ผู้เขียน B"])
        self.assertEqual(metadata["publisher"], "สำนักพิมพ์ตัวอย่าง")
        self.assertEqual(metadata["publishedDate"], "2024-01-05")
        self.assertEqual(metadata["description"], "คำอธิบาย")
        self.assertEqual(metadata["language"], "th")
        self.assertEqual(metadata["categories"], ["หมวดหนึ่ง", "หมวดสอง"])
        self.assertEqual(metadata["isbn13"], "9781402894626")
        self.assertEqual(metadata["isbn10"], "1402894627")
        self.assertEqual(metadata["series"], {"name": "ชุดตัวอย่าง", "number": 2})

    def test_build_sidecar_payload(self) -> None:
        payload = converter.build_sidecar_payload(
            {"title": "Example"},
            "Book 1.cover.jpg",
        )
        self.assertEqual(payload["version"], "1.0")
        self.assertEqual(payload["generatedBy"], "booklore")
        self.assertIn("generatedAt", payload)
        self.assertEqual(payload["metadata"], {"title": "Example"})
        self.assertEqual(payload["cover"], {"source": "external", "path": "Book 1.cover.jpg"})

    def test_write_sidecar_cover_preserves_source_and_creates_jpg(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "Book 1.jpg"
            target = root / "Book 1.cover.jpg"
            source.write_bytes(b"fakejpeg")

            converter.write_sidecar_cover(source, target)

            self.assertTrue(source.exists())
            self.assertTrue(target.exists())
            self.assertEqual(target.read_bytes(), b"fakejpeg")

    def test_scan_library_logs_when_no_opf_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logs: list[str] = []
            stats = converter.scan_library(
                Path(tmp),
                allowed_exts=set(),
                write=False,
                overwrite=False,
                log=logs.append,
            )

        self.assertEqual(stats.opf_files_found, 0)
        self.assertEqual(logs, [f"SKIP no OPF files found under {Path(tmp)}"])

    def test_scan_library_named_opf_does_not_duplicate_every_book(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for number in ("1", "2"):
                opf = root / f"Vol {number}.opf"
                pdf = root / f"Vol {number}.pdf"
                jpg = root / f"Vol {number}.jpg"
                opf.write_text(
                    """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Test</dc:title>
  </metadata>
</package>
""",
                    encoding="utf-8",
                )
                pdf.write_text("pdf", encoding="utf-8")
                jpg.write_text("jpg", encoding="utf-8")

            logs: list[str] = []
            stats = converter.scan_library(
                root,
                allowed_exts=set(),
                write=False,
                overwrite=False,
                log=logs.append,
            )

        self.assertEqual(stats.opf_files_found, 2)
        self.assertEqual(stats.book_files_found, 2)
        self.assertEqual(stats.json_planned, 2)
        self.assertEqual(stats.cover_found, 2)

    def test_scan_library_same_stem_multiple_formats_writes_one_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            opf = root / "Book 1.opf"
            pdf = root / "Book 1.pdf"
            epub = root / "Book 1.epub"
            opf.write_text(
                """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Test</dc:title>
  </metadata>
</package>
""",
                encoding="utf-8",
            )
            pdf.write_text("pdf", encoding="utf-8")
            epub.write_bytes(b"epub")

            logs: list[str] = []
            stats = converter.scan_library(
                root,
                allowed_exts=set(),
                write=True,
                overwrite=True,
                log=logs.append,
            )

            self.assertEqual(stats.opf_files_found, 1)
            self.assertEqual(stats.book_files_found, 2)
            self.assertEqual(stats.json_planned, 1)
            self.assertEqual(stats.json_created, 1)
            self.assertIn("SKIP duplicate target", "\n".join(logs))
            self.assertTrue(converter.target_json_path(pdf).exists())
            self.assertTrue(converter.target_json_path(epub).exists())
            self.assertEqual(
                converter.build_sidecar_payload({"title": "Test"}, converter.target_cover_path(pdf).name)["cover"]["path"],
                "Book 1.cover.jpg",
            )


if __name__ == "__main__":
    unittest.main()
