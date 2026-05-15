from __future__ import annotations

from pathlib import Path
import sys
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import opf_to_embedded_metadata as legacy  # noqa: E402


OpfData = dict[str, Any]


def embed_pdf(book: str | Path, opf: OpfData, opts: dict[str, Any] | None = None) -> bool:
    return legacy.write_pdf_metadata(Path(book), dict(opf), opts or {})
