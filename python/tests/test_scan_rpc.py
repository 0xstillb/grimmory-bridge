from __future__ import annotations

from pathlib import Path
import tempfile

import pytest

from grimmory_bridge.scan import ScanError, scan_roots


def test_scan_roots_returns_books_with_contract_fields() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "A").mkdir()
        (root / "A" / "Book 1.epub").write_bytes(b"epub")
        (root / "A" / "Book 1.opf").write_text(
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Book One</dc:title>
    <dc:creator>Author One</dc:creator>
  </metadata>
</package>
""",
            encoding="utf-8",
        )
        (root / "A" / "Book 1.metadata.json").write_text("{}", encoding="utf-8")
        (root / "A" / "Book 1.cover.jpg").write_bytes(b"jpg")

        result = scan_roots([str(root)], ext_kinds=["epub"])

        assert "scan_id" in result
        assert result["roots"][0]["book_count"] == 1
        book = result["books"][0]
        assert len(book["id"]) == 16
        assert book["kind"] == "epub"
        assert book["title"] == "Book One"
        assert book["authors"] == ["Author One"]
        assert book["has_opf"] is True
        assert book["has_sidecar"] is True
        assert book["has_cover_sidecar"] is True


def test_scan_roots_bad_root_raises_scan_error() -> None:
    with pytest.raises(ScanError) as exc:
        scan_roots(["Z:/path/that/does/not/exist"], ext_kinds=["epub"])
    assert exc.value.code == 1001
    assert exc.value.message == "BAD_ROOT"


def test_scan_roots_applies_v1_book_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("grimmory_bridge.scan.MAX_BOOKS_V1", 3)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for i in range(4):
            (root / f"Book-{i}.epub").write_bytes(b"x")

        with pytest.raises(ScanError) as exc:
            scan_roots([str(root)], ext_kinds=["epub"])

    assert exc.value.code == 1001
    assert exc.value.message == "BAD_ROOT"
    assert "too large" in (exc.value.data or {}).get("reason", "")

