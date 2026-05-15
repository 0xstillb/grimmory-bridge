from __future__ import annotations

import argparse
from pathlib import Path
import sys


_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import opf_to_embedded_metadata as legacy  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Embed OPF metadata into EPUB/PDF and generate Grimmory sidecars."
    )
    parser.add_argument("root", help="Root folder to scan recursively.")
    parser.add_argument(
        "--ext",
        default="pdf,epub",
        help="Comma-separated extension filter (default: pdf,epub).",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write changes to files. Dry-run is default when omitted.",
    )
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.root).expanduser()

    valid, error_message = legacy.validate_root(root)
    if not valid:
        print(error_message)
        return 2

    allowed_exts = {ext for ext in legacy.normalize_allowed_exts(args.ext) if ext in legacy.SUPPORTED_EXTS}
    stats = legacy.scan_library(
        root=root,
        allowed_exts=allowed_exts,
        write=bool(args.write),
    )
    legacy.print_summary(stats)
    return 0


def main() -> int:
    return run(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())

