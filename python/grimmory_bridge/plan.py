from __future__ import annotations

import base64
from collections import OrderedDict
import copy
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from io import BytesIO
from pathlib import Path
import time
from typing import Any, Callable
import uuid
from xml.etree import ElementTree as ET
import zipfile

from PIL import Image

try:
    from .compat import compat_report
except ImportError:  # PyInstaller onefile entrypoint fallback
    from grimmory_bridge.compat import compat_report  # type: ignore

try:
    from .opf import parse_opf
except ImportError:  # PyInstaller onefile entrypoint fallback
    from grimmory_bridge.opf import parse_opf  # type: ignore

try:
    from .scan import scan_roots
except ImportError:  # PyInstaller onefile entrypoint fallback
    from grimmory_bridge.scan import scan_roots  # type: ignore

try:
    from .sidecar import render_sidecar_preview
except ImportError:  # PyInstaller onefile entrypoint fallback
    from grimmory_bridge.sidecar import render_sidecar_preview  # type: ignore


DEFAULT_SOURCE_PRIORITY = ["calibre", "grimmory", "koreader"]
_TARGETS = ("calibre", "grimmory", "koreader")

PLAN_CACHE_MAX = 32
PLAN_TTL_SECONDS = 10 * 60


ProgressCallback = Callable[[str, int, int], None]
_RESAMPLE = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS


@dataclass
class _CacheEntry:
    expires_at: float
    value: dict[str, Any]


_PLAN_CACHE: OrderedDict[str, _CacheEntry] = OrderedDict()


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _resolve_source_priority(source_priority: list[str] | None) -> list[str]:
    if not source_priority:
        return list(DEFAULT_SOURCE_PRIORITY)

    seen: set[str] = set()
    resolved: list[str] = []
    for target in source_priority:
        value = target.lower().strip()
        if value in _TARGETS and value not in seen:
            seen.add(value)
            resolved.append(value)

    for default in DEFAULT_SOURCE_PRIORITY:
        if default not in seen:
            resolved.append(default)

    return resolved


def _planned_outputs(book: dict[str, Any], sidecar_preview: str | None = None) -> list[dict[str, Any]]:
    path = Path(book["path"])
    kind = book["kind"]
    size = int(book.get("size", 0) or 0)
    has_opf = bool(book.get("has_opf"))

    if kind not in {"epub", "pdf"}:
        return []
    if not has_opf:
        return []

    outputs: list[dict[str, Any]] = [
        {
            "op": "backup",
            "path": f"{path}.bak",
            "kind": "backup",
            "bytes": size,
        },
        {
            "op": "write",
            "path": str(path),
            "kind": kind,
            "bytes": size,
        },
    ]

    sidecar_json = path.with_name(f"{path.stem}.metadata.json")
    outputs.append(
        {
            "op": "update" if bool(book.get("has_sidecar")) else "create",
            "path": str(sidecar_json),
            "kind": "sidecar_json",
            "bytes": 1024,
            "preview": sidecar_preview,
        }
    )

    if bool(book.get("has_cover_sidecar")):
        sidecar_cover = path.with_name(f"{path.stem}.cover.jpg")
        outputs.append(
            {
                "op": "update",
                "path": str(sidecar_cover),
                "kind": "sidecar_cover",
                "bytes": 0,
            }
        )

    return outputs


def _matching_opf(book_path: Path) -> Path | None:
    same_stem = book_path.with_suffix(".opf")
    if same_stem.exists():
        return same_stem
    metadata_opf = book_path.parent / "metadata.opf"
    if metadata_opf.exists():
        return metadata_opf
    return None


def _normalize_series_index(value: Any) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        try:
            return float(text)
        except ValueError:
            return None


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, tuple, set)):
        return len(value) == 0
    return False


def _field_status(current: Any, target: Any) -> str:
    if current == target:
        return "same"
    if _is_empty(current) and not _is_empty(target):
        return "added"
    if not _is_empty(current) and _is_empty(target):
        return "removed"
    return "changed"


def _field_diffs(book: dict[str, Any]) -> list[dict[str, Any]]:
    has_opf = bool(book.get("has_opf"))
    book_path = Path(str(book.get("path")))
    kind = str(book.get("kind"))
    scan_series = book.get("series") if isinstance(book.get("series"), dict) else {}

    opf_target: dict[str, Any] = {}
    if has_opf:
        opf_path = _matching_opf(book_path)
        if opf_path is not None:
            try:
                opf_target = parse_opf(opf_path)
            except Exception:
                opf_target = {}

    target_series = opf_target.get("series") if isinstance(opf_target.get("series"), dict) else {}

    current_values = {
        "title": book.get("title"),
        "authors": book.get("authors") or [],
        "publisher": None,
        "pubdate": None,
        "language": None,
        "identifiers.isbn10": None,
        "identifiers.isbn13": book.get("isbn"),
        "description": None,
        "series.name": scan_series.get("name"),
        "series.index": _normalize_series_index(scan_series.get("index") or scan_series.get("number")),
        "tags": [],
        "rating": None,
    }

    target_values = {
        "title": opf_target.get("title"),
        "authors": opf_target.get("authors") or [],
        "publisher": opf_target.get("publisher"),
        "pubdate": opf_target.get("publishedDate"),
        "language": opf_target.get("language"),
        "identifiers.isbn10": opf_target.get("isbn10"),
        "identifiers.isbn13": opf_target.get("isbn13"),
        "description": opf_target.get("description"),
        "series.name": target_series.get("name"),
        "series.index": _normalize_series_index(target_series.get("index") or target_series.get("number")),
        "tags": opf_target.get("categories") or [],
        "rating": opf_target.get("rating"),
    }

    keys = [
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

    out: list[dict[str, Any]] = []
    for key in keys:
        current = current_values.get(key)
        target = target_values.get(key)

        if not has_opf:
            row = {"key": key, "status": "warn", "current": current, "target": target, "note": "missing OPF"}
            out.append(row)
            continue

        status = _field_status(current, target)
        row: dict[str, Any] = {"key": key, "status": status, "current": current, "target": target}
        if kind == "pdf" and status in {"changed", "added", "removed"}:
            row["note"] = "stale XMP"
        out.append(row)

    return out


def _cover_diff(book: dict[str, Any]) -> dict[str, Any]:
    book_path = Path(str(book.get("path")))
    kind = str(book.get("kind"))
    opf_path = _matching_opf(book_path)

    sidecar_path = _find_sidecar_cover(book_path)
    embedded = _extract_embedded_cover(book_path) if kind == "epub" else None
    opf_cover_path = _find_opf_cover(opf_path, book_path) if opf_path is not None else None

    current = None
    target = None

    if embedded is not None:
        current = _cover_payload("embedded", embedded[0], embedded[1], fresh_ref=book_path)
    elif sidecar_path is not None:
        current = _cover_payload("sidecar", sidecar_path, None, fresh_ref=book_path)
    else:
        current = {"src": "none"}

    if opf_cover_path is not None:
        target = _cover_payload("opf", opf_cover_path, None, fresh_ref=book_path)
    elif sidecar_path is not None:
        target = _cover_payload("sidecar", sidecar_path, None, fresh_ref=book_path)
    elif embedded is not None:
        target = _cover_payload("embedded", embedded[0], embedded[1], fresh_ref=book_path)
    else:
        target = {"src": "none"}

    return {
        "status": _field_status(current.get("sha"), target.get("sha")),
        "current": current,
        "target": target,
    }


def _find_sidecar_cover(book_path: Path) -> Path | None:
    sidecar = book_path.with_name(f"{book_path.stem}.cover.jpg")
    return sidecar if sidecar.exists() else None


def _planned_cover_target_name(book_path: Path) -> str | None:
    for suffix in (".jpg", ".jpeg", ".png"):
        candidate = book_path.with_name(f"{book_path.stem}{suffix}")
        if candidate.exists():
            return f"{book_path.stem}.cover.jpg"
    return None


def _find_opf_cover(opf_path: Path | None, book_path: Path) -> Path | None:
    if opf_path is None or not opf_path.exists():
        return None

    # Common side-by-side cover names in Calibre-style folders.
    for suffix in (".jpg", ".jpeg", ".png"):
        candidate = book_path.with_suffix(suffix)
        if candidate.exists():
            return candidate

    try:
        tree = ET.parse(opf_path)
        root = tree.getroot()
        ns = {"opf": "http://www.idpf.org/2007/opf"}
        cover_id = None
        for meta in root.findall(".//opf:meta", ns):
            if meta.attrib.get("name") == "cover":
                cover_id = meta.attrib.get("content")
                break

        href = None
        if cover_id:
            for item in root.findall(".//opf:item", ns):
                if item.attrib.get("id") == cover_id:
                    href = item.attrib.get("href")
                    break

        if href:
            candidate = (opf_path.parent / href).resolve()
            if candidate.exists():
                return candidate
    except Exception:
        return None

    return None


def _extract_embedded_cover(epub_path: Path) -> tuple[str, bytes] | None:
    if not epub_path.exists():
        return None
    try:
        with zipfile.ZipFile(epub_path, "r") as archive:
            container_xml = archive.read("META-INF/container.xml")
            container_root = ET.fromstring(container_xml)
            rootfile = container_root.find(".//{*}rootfile")
            if rootfile is None:
                return None
            opf_name = rootfile.attrib.get("full-path")
            if not opf_name:
                return None

            opf_xml = archive.read(opf_name)
            opf_root = ET.fromstring(opf_xml)
            ns = {"opf": "http://www.idpf.org/2007/opf"}
            cover_id = None
            for meta in opf_root.findall(".//opf:meta", ns):
                if meta.attrib.get("name") == "cover":
                    cover_id = meta.attrib.get("content")
                    break

            item_href = None
            if cover_id:
                for item in opf_root.findall(".//opf:item", ns):
                    if item.attrib.get("id") == cover_id:
                        item_href = item.attrib.get("href")
                        break

            if item_href is None:
                for item in opf_root.findall(".//opf:item", ns):
                    media_type = str(item.attrib.get("media-type", "")).lower()
                    href = str(item.attrib.get("href", "")).lower()
                    if media_type.startswith("image/") and "cover" in href:
                        item_href = item.attrib.get("href")
                        break

            if not item_href:
                return None

            opf_parent = Path(opf_name).parent
            image_name = str((opf_parent / item_href).as_posix())
            raw = archive.read(image_name)
            return image_name, raw
    except Exception:
        return None


def _cover_payload(src: str, path_or_name: Path | str, raw: bytes | None, fresh_ref: Path) -> dict[str, Any]:
    try:
        if raw is None:
            raw_bytes = Path(path_or_name).read_bytes()
        else:
            raw_bytes = raw

        with Image.open(BytesIO(raw_bytes)) as image:
            image = image.convert("RGB")
            image.thumbnail((300, 300), _RESAMPLE)
            width, height = image.size
            buffer = BytesIO()
            image.save(buffer, format="JPEG", quality=80)
            thumb_bytes = buffer.getvalue()

        freshness = "unknown"
        if raw is None:
            cover_path = Path(path_or_name)
            try:
                freshness = "fresh" if cover_path.stat().st_mtime >= fresh_ref.stat().st_mtime else "stale"
            except Exception:
                freshness = "unknown"

        return {
            "src": src,
            "w": width,
            "h": height,
            "sha": hashlib.sha1(thumb_bytes).hexdigest()[:16],
            "bytes": len(thumb_bytes),
            "freshness": freshness,
            "data_uri": "data:image/jpeg;base64," + base64.b64encode(thumb_bytes).decode("ascii"),
        }
    except Exception:
        return {"src": src}


def _compat_report(book: dict[str, Any]) -> list[dict[str, Any]]:
    return compat_report(book)


def _book_plan(book: dict[str, Any]) -> dict[str, Any]:
    warnings: list[str] = []
    errors: list[str] = []
    book_path = Path(str(book.get("path")))
    opf_data: dict[str, Any] = {}
    opf_found = False

    if not bool(book.get("has_opf")):
        warnings.append("No OPF found; run may skip writes for this book")
    if book.get("kind") not in {"epub", "pdf"}:
        warnings.append("Unsupported file kind for write mode in v1")

    if bool(book.get("has_opf")):
        opf_path = _matching_opf(book_path)
        if opf_path is not None:
            opf_found = True
            try:
                opf_data = parse_opf(opf_path)
            except Exception:
                opf_data = {}

    sidecar_preview = None
    if opf_found:
        try:
            sidecar_preview = render_sidecar_preview(opf_data, _planned_cover_target_name(book_path))
        except Exception:
            sidecar_preview = None

    return {
        "book_id": book["id"],
        "fields": _field_diffs(book),
        "cover": _cover_diff(book),
        "outputs": _planned_outputs(book, sidecar_preview),
        "compat": _compat_report(book),
        "warnings": warnings,
        "errors": errors,
    }


def _purge_expired(now: float | None = None) -> None:
    ts = now if now is not None else time.time()
    stale = [plan_id for plan_id, entry in _PLAN_CACHE.items() if entry.expires_at <= ts]
    for plan_id in stale:
        _PLAN_CACHE.pop(plan_id, None)


def cache_plan(plan: dict[str, Any]) -> None:
    _purge_expired()

    plan_id = str(plan["plan_id"])
    _PLAN_CACHE[plan_id] = _CacheEntry(expires_at=time.time() + PLAN_TTL_SECONDS, value=copy.deepcopy(plan))
    _PLAN_CACHE.move_to_end(plan_id)

    while len(_PLAN_CACHE) > PLAN_CACHE_MAX:
        _PLAN_CACHE.popitem(last=False)


def get_cached_plan(plan_id: str) -> dict[str, Any] | None:
    _purge_expired()
    entry = _PLAN_CACHE.get(plan_id)
    if entry is None:
        return None

    _PLAN_CACHE.move_to_end(plan_id)
    return copy.deepcopy(entry.value)


def clear_cached_plans() -> None:
    _PLAN_CACHE.clear()


def build_plan(
    roots: list[str],
    ext_kinds: list[str] | None = None,
    source_priority: list[str] | None = None,
    progress_cb: ProgressCallback | None = None,
) -> dict[str, Any]:
    scan_result = scan_roots(roots=roots, ext_kinds=ext_kinds)
    books = scan_result["books"]
    scan_id = scan_result["scan_id"]
    total = len(books)

    summary = {
        "total": total,
        "changes": 0,
        "warn": 0,
        "same": 0,
        "errored": 0,
    }

    planned_books: list[dict[str, Any]] = []
    for idx, book in enumerate(books, start=1):
        plan = _book_plan(book)
        planned_books.append(plan)

        if plan["errors"]:
            summary["errored"] += 1
        elif plan["warnings"]:
            summary["warn"] += 1
        elif plan["outputs"]:
            summary["changes"] += 1
        else:
            summary["same"] += 1

        if progress_cb is not None and (idx % 25 == 0 or idx == total):
            progress_cb(scan_id, idx, total)

    plan_result = {
        "plan_id": f"p_{uuid.uuid4().hex[:12]}",
        "scan_id": scan_id,
        "built_at": _iso_now(),
        "roots": [str(root.get("path")) for root in scan_result.get("roots", []) if root.get("path")],
        "source_priority": _resolve_source_priority(source_priority),
        "summary": summary,
        "books": planned_books,
    }
    cache_plan(plan_result)
    return plan_result
