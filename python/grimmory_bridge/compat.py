from __future__ import annotations

from typing import Any


_TARGETS = ("grimmory", "koreader", "calibre")
_SIDECAR_ONLY_KINDS = {"cbz", "azw3", "mobi"}


def _unsupported_rows(note: str) -> list[dict[str, Any]]:
    return [{"target": target, "status": "unsupported", "notes": [note]} for target in _TARGETS]


def compat_report(book: dict[str, Any]) -> list[dict[str, Any]]:
    kind = str(book.get("kind") or "other").lower()
    has_opf = bool(book.get("has_opf"))

    if kind in _SIDECAR_ONLY_KINDS:
        return _unsupported_rows("sidecar only")

    if kind not in {"epub", "pdf"}:
        return _unsupported_rows(f"{kind} is not write-supported in v1")

    reports: list[dict[str, Any]] = []
    if kind == "epub":
        reports.append({"target": "grimmory", "status": "ok", "notes": []})
        reports.append({"target": "koreader", "status": "ok", "notes": []})
    else:
        reports.append({"target": "grimmory", "status": "ok", "notes": ["sidecar bypasses XMP"]})
        reports.append(
            {
                "target": "koreader",
                "status": "partial",
                "notes": ["reads only Title + Author from /Info"],
            }
        )

    if has_opf:
        reports.append({"target": "calibre", "status": "source", "notes": []})
    else:
        reports.append(
            {
                "target": "calibre",
                "status": "missing",
                "notes": ["No OPF metadata available"],
            }
        )
    return reports
