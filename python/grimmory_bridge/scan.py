from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from pathlib import Path
from typing import Any
import uuid

try:
    from .opf import parse_opf
except ImportError:  # PyInstaller onefile entrypoint fallback
    from grimmory_bridge.opf import parse_opf  # type: ignore


MAX_BOOKS_V1 = 5000

_KIND_TO_EXT = {
    "epub": {".epub"},
    "pdf": {".pdf"},
    "cbz": {".cbz"},
    "azw3": {".azw3"},
    "mobi": {".mobi"},
    "other": set(),
}
_EXT_TO_KIND = {
    ".epub": "epub",
    ".pdf": "pdf",
    ".cbz": "cbz",
    ".azw3": "azw3",
    ".mobi": "mobi",
}


@dataclass
class ScanError(Exception):
    code: int
    message: str
    data: dict[str, Any] | None = None


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).isoformat().replace("+00:00", "Z")


def _book_id(path: Path) -> str:
    return hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:16]


def _matching_opf(book_path: Path) -> Path | None:
    same_stem = book_path.with_suffix(".opf")
    if same_stem.exists():
        return same_stem
    metadata_opf = book_path.parent / "metadata.opf"
    if metadata_opf.exists():
        return metadata_opf
    return None


def _allowed_exts(ext_kinds: list[str] | None) -> set[str]:
    if not ext_kinds:
        return {".epub", ".pdf"}

    out: set[str] = set()
    for kind in ext_kinds:
        key = kind.lower().strip()
        if key in _KIND_TO_EXT:
            out.update(_KIND_TO_EXT[key])
    return out


def _kind_for(path: Path) -> str:
    return _EXT_TO_KIND.get(path.suffix.lower(), "other")


def _book_record(path: Path, root: Path) -> dict[str, Any]:
    stat = path.stat()
    opf_path = _matching_opf(path)

    title: str | None = None
    authors: list[str] = []
    series: dict[str, Any] | None = None
    isbn: str | None = None
    if opf_path is not None:
        try:
            metadata = parse_opf(opf_path)
            title = metadata.get("title")
            authors = metadata.get("authors") or []
            series = metadata.get("series")
            isbn = metadata.get("isbn13") or metadata.get("isbn10")
        except Exception:
            # Keep scan resilient: metadata enrichment is best-effort.
            pass

    sidecar = path.with_name(f"{path.stem}.metadata.json")
    cover_sidecar = path.with_name(f"{path.stem}.cover.jpg")

    return {
        "id": _book_id(path),
        "path": str(path.resolve()),
        "rel": str(path.resolve().relative_to(root.resolve())),
        "kind": _kind_for(path),
        "size": stat.st_size,
        "mtime": _iso(stat.st_mtime),
        "title": title,
        "authors": authors,
        "series": series,
        "isbn": isbn,
        "has_opf": opf_path is not None,
        "has_sidecar": sidecar.exists(),
        "has_cover_sidecar": cover_sidecar.exists(),
        "has_embedded_cover": False,
    }


def scan_roots(roots: list[str], ext_kinds: list[str] | None = None) -> dict[str, Any]:
    if not roots:
        raise ScanError(1001, "BAD_ROOT", {"reason": "roots is empty"})

    root_paths = [Path(root).expanduser() for root in roots]
    for root in root_paths:
        if not root.exists() or not root.is_dir():
            raise ScanError(1001, "BAD_ROOT", {"path": str(root)})

    allowed_exts = _allowed_exts(ext_kinds)

    books: list[dict[str, Any]] = []
    roots_out: list[dict[str, Any]] = []

    for root in root_paths:
        count_for_root = 0
        for file_path in root.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in allowed_exts:
                continue

            books.append(_book_record(file_path, root))
            count_for_root += 1

            if len(books) > MAX_BOOKS_V1:
                raise ScanError(
                    1001,
                    "BAD_ROOT",
                    {
                        "path": str(root),
                        "reason": f"too large (>{MAX_BOOKS_V1} books)",
                    },
                )

        roots_out.append({"path": str(root.resolve()), "book_count": count_for_root})

    return {
        "scan_id": f"s_{uuid.uuid4().hex[:12]}",
        "scanned_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "roots": roots_out,
        "books": books,
    }
