from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from opf_to_grimmory_json import (  # noqa: E402
    build_sidecar_payload,
    target_cover_path,
    target_json_path,
    write_sidecar,
    write_sidecar_cover,
)


OpfData = dict[str, Any]
_COVER_EXTS = (".jpg", ".jpeg", ".png")


def _auto_cover_source(book: Path) -> Path | None:
    for ext in _COVER_EXTS:
        candidate = book.with_name(f"{book.stem}{ext}")
        if candidate.exists():
            return candidate
    return None


def write_sidecars(book: str | Path, opf: OpfData, opts: dict[str, Any] | None = None) -> bool:
    opts = opts or {}
    book_path = Path(book)
    metadata = dict(opf)
    overwrite = bool(opts.get("overwrite", True))

    json_path = target_json_path(book_path)
    if json_path.exists() and not overwrite:
        return False

    cover_source_opt = opts.get("cover_source")
    if cover_source_opt:
        cover_source = Path(cover_source_opt)
    else:
        cover_source = _auto_cover_source(book_path)

    cover_target_name: str | None = None
    if cover_source and cover_source.exists():
        cover_target = target_cover_path(book_path)
        write_sidecar_cover(cover_source, cover_target)
        cover_target_name = cover_target.name

    payload = build_sidecar_payload(metadata, cover_target_name)
    write_sidecar(json_path, payload)
    return True


def render_sidecar_preview(opf: OpfData, cover_target_name: str | None) -> str:
    payload = build_sidecar_payload(dict(opf), cover_target_name)
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
