from __future__ import annotations

from pathlib import Path
import tempfile

from PIL import Image

from grimmory_bridge.plan import build_plan, clear_cached_plans, get_cached_plan
import grimmory_bridge.plan as plan_mod


OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Book</dc:title>
    <dc:creator>Author</dc:creator>
    <dc:publisher>Pub House</dc:publisher>
    <dc:date>2024-05-17</dc:date>
    <dc:description>Desc</dc:description>
    <dc:language>th</dc:language>
    <dc:subject>Fantasy</dc:subject>
    <dc:identifier>ISBN 9781402894626</dc:identifier>
    <meta name="calibre:series" content="Series One" />
    <meta name="calibre:series_index" content="2" />
    <meta name="calibre:rating" content="4" />
  </metadata>
</package>
"""


def _seed_epub(root: Path, name: str, with_opf: bool = True) -> None:
    book = root / f"{name}.epub"
    book.write_bytes(b"epub")
    if with_opf:
        book.with_suffix(".opf").write_text(OPF, encoding="utf-8")


def _seed_pdf(root: Path, name: str, with_opf: bool = True) -> None:
    book = root / f"{name}.pdf"
    book.write_bytes(b"%PDF-1.4\n%mock\n")
    if with_opf:
        book.with_suffix(".opf").write_text(OPF, encoding="utf-8")


def _seed_cbz(root: Path, name: str, with_opf: bool = False) -> None:
    book = root / f"{name}.cbz"
    book.write_bytes(b"cbz")
    if with_opf:
        book.with_suffix(".opf").write_text(OPF, encoding="utf-8")


def _seed_cover(path: Path) -> None:
    image = Image.new("RGB", (1200, 800), color=(100, 60, 140))
    image.save(path, format="JPEG", quality=95)


def test_plan_returns_structurally_complete_payload_and_caches() -> None:
    clear_cached_plans()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        expected_root = str(root)
        _seed_epub(root, "A", with_opf=True)
        _seed_epub(root, "B", with_opf=False)

        result = build_plan([str(root)], ext_kinds=["epub"])

    assert result["plan_id"].startswith("p_")
    assert result["scan_id"].startswith("s_")
    assert result["roots"] == [expected_root]
    assert result["source_priority"] == ["calibre", "grimmory", "koreader"]
    assert set(result["summary"]) == {"total", "changes", "warn", "same", "errored"}
    assert result["summary"]["total"] == 2
    assert len(result["books"]) == 2

    first = result["books"][0]
    assert set(first) == {"book_id", "fields", "cover", "outputs", "compat", "warnings", "errors"}
    assert len(first["compat"]) == 3
    assert first["cover"]["status"] in {"same", "changed", "warn", "added", "removed"}
    keys = [field["key"] for field in first["fields"]]
    assert keys == [
        "title",
        "authors",
        "publisher",
        "pubdate",
        "language",
        "identifiers.isbn10",
        "identifiers.isbn13",
        "description",
        "series.name",
        "series.index",
        "tags",
        "rating",
    ]

    cached = get_cached_plan(result["plan_id"])
    assert cached is not None
    assert cached["plan_id"] == result["plan_id"]


def test_plan_progress_callback_emits_every_25_books() -> None:
    clear_cached_plans()
    progress: list[tuple[int, int]] = []

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for idx in range(60):
            _seed_epub(root, f"Book-{idx}", with_opf=True)

        build_plan(
            [str(root)],
            ext_kinds=["epub"],
            progress_cb=lambda _scan_id, current, total: progress.append((current, total)),
        )

    assert progress == [(25, 60), (50, 60), (60, 60)]


def test_cached_plan_respects_ttl(monkeypatch) -> None:
    clear_cached_plans()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_epub(root, "A", with_opf=True)
        result = build_plan([str(root)], ext_kinds=["epub"])

    plan_id = result["plan_id"]
    assert get_cached_plan(plan_id) is not None

    now = plan_mod.time.time()
    monkeypatch.setattr(plan_mod.time, "time", lambda: now + plan_mod.PLAN_TTL_SECONDS + 1)
    assert get_cached_plan(plan_id) is None


def test_pdf_diff_rows_can_include_stale_xmp_note() -> None:
    clear_cached_plans()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_pdf(root, "A", with_opf=True)
        result = build_plan([str(root)], ext_kinds=["pdf"])

    rows = result["books"][0]["fields"]
    notes = [row.get("note") for row in rows if row["status"] in {"changed", "added", "removed"}]
    assert "stale XMP" in notes


def test_cover_diff_contains_thumbnail_data_uri() -> None:
    clear_cached_plans()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_epub(root, "A", with_opf=True)
        _seed_cover(root / "A.cover.jpg")
        _seed_cover(root / "A.jpg")
        result = build_plan([str(root)], ext_kinds=["epub"])

    cover = result["books"][0]["cover"]
    current = cover["current"]
    target = cover["target"]
    assert isinstance(current, dict)
    assert isinstance(target, dict)
    assert str(current.get("data_uri", "")).startswith("data:image/jpeg;base64,")
    assert str(target.get("data_uri", "")).startswith("data:image/jpeg;base64,")
    assert int(current.get("w", 0)) <= 300
    assert int(current.get("h", 0)) <= 300


def test_sidecar_output_includes_preview_string() -> None:
    clear_cached_plans()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_epub(root, "A", with_opf=True)
        _seed_cover(root / "A.jpg")
        result = build_plan([str(root)], ext_kinds=["epub"])

    outputs = result["books"][0]["outputs"]
    sidecar = next((entry for entry in outputs if entry.get("kind") == "sidecar_json"), None)
    assert isinstance(sidecar, dict)

    preview = sidecar.get("preview")
    assert isinstance(preview, str)
    assert preview.startswith("{")
    assert '"metadata"' in preview
    assert '"title": "Book"' in preview
    assert '"path": "A.cover.jpg"' in preview


def test_compat_matrix_pdf_marks_koreader_partial() -> None:
    clear_cached_plans()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_pdf(root, "A", with_opf=True)
        result = build_plan([str(root)], ext_kinds=["pdf"])

    compat = result["books"][0]["compat"]
    by_target = {entry["target"]: entry for entry in compat}
    assert by_target["grimmory"]["status"] == "ok"
    assert by_target["koreader"]["status"] == "partial"
    assert "reads only Title + Author from /Info" in by_target["koreader"]["notes"]
    assert by_target["calibre"]["status"] == "source"


def test_compat_matrix_cbz_is_unsupported_for_all_targets() -> None:
    clear_cached_plans()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_cbz(root, "A", with_opf=False)
        result = build_plan([str(root)], ext_kinds=["cbz"])

    compat = result["books"][0]["compat"]
    assert len(compat) == 3
    for entry in compat:
        assert entry["status"] == "unsupported"
        assert "sidecar only" in entry["notes"]
