#!/usr/bin/env python3
"""Convert Calibre metadata.opf files into Grimmory-compatible sidecar JSON files."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable
from xml.etree import ElementTree as ET


SUPPORTED_BOOK_EXTS = {
    ".pdf",
    ".epub",
    ".mobi",
    ".azw3",
    ".cbz",
    ".cbr",
    ".cb7",
}

COVER_NAMES = ("cover.jpg", "cover.jpeg", "cover.png")
SUPPORTED_COVER_EXTS = (".jpg", ".jpeg", ".png")

DC_NS = "http://purl.org/dc/elements/1.1/"
OPF_NS = "http://www.idpf.org/2007/opf"

SIDECAR_BOOK_METADATA_ORDER = [
    "title",
    "subtitle",
    "authors",
    "publisher",
    "publishedDate",
    "description",
    "isbn10",
    "isbn13",
    "language",
    "pageCount",
    "categories",
    "moods",
    "tags",
    "series",
    "identifiers",
    "ratings",
    "ageRating",
    "contentRating",
    "narrator",
    "abridged",
    "comicMetadata",
]


@dataclass
class RunStats:
    opf_files_found: int = 0
    book_files_found: int = 0
    json_planned: int = 0
    json_created: int = 0
    skipped_existing: int = 0
    parse_errors: int = 0
    write_errors: int = 0
    no_book_file: int = 0
    cover_found: int = 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scan a book library for Calibre metadata.opf files and generate "
            "Grimmory sidecar JSON files."
        )
    )
    parser.add_argument(
        "--root",
        default="/media/QNAP_Books/Books",
        help="Root folder to scan recursively for metadata.opf files.",
    )
    parser.add_argument(
        "--ext",
        default="",
        help="Optional comma-separated list of book extensions to process, e.g. pdf,epub.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Actually create JSON sidecar files. Dry-run is the default.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing .metadata.json files.",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Open a simple folder picker and run with a GUI window.",
    )
    return parser.parse_args(argv)


def normalize_extensions(ext_value: str) -> set[str]:
    if not ext_value.strip():
        return set()
    result = set()
    for part in ext_value.split(","):
        cleaned = part.strip().lower()
        if not cleaned:
            continue
        if not cleaned.startswith("."):
            cleaned = f".{cleaned}"
        result.add(cleaned)
    return result


def local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def first_text(elements: Iterable[ET.Element]) -> str | None:
    for element in elements:
        text = clean_text("".join(element.itertext()))
        if text:
            return text
    return None


def all_text(elements: Iterable[ET.Element]) -> list[str]:
    values: list[str] = []
    for element in elements:
        text = clean_text("".join(element.itertext()))
        if text:
            values.append(text)
    return values


def clean_text(value: str | None) -> str:
    if value is None:
        return ""
    text = re.sub(r"\s+", " ", value).strip()
    return text


def normalize_date(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None

    candidates = [text]
    if text.endswith("Z"):
        candidates.append(text[:-1] + "+00:00")

    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        return parsed.date().isoformat()

    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date().isoformat()
    except ValueError:
        pass

    return text


ISBN10_RE = re.compile(r"(?i)\b(?:ISBN(?:-1[03])?:?\s*)?([0-9][0-9\- ]{8,}[0-9Xx])\b")
ISBN13_RE = re.compile(r"(?i)\b(?:ISBN(?:-1[03])?:?\s*)?(97[89][0-9\- ]{9,}[0-9])\b")


def normalize_isbn(raw: str | None) -> tuple[str | None, str | None, str | None]:
    if not raw:
        return (None, None, None)

    candidate = raw.strip()
    if not candidate:
        return (None, None, None)

    direct_13 = _extract_and_validate_isbn(candidate, isbn13=True)
    direct_10 = _extract_and_validate_isbn(candidate, isbn13=False)

    if direct_13:
        isbn13 = direct_13
        isbn10 = isbn13_to_isbn10(isbn13)
        canonical = isbn13
        return canonical, isbn10, isbn13

    if direct_10:
        isbn10 = direct_10
        isbn13 = isbn10_to_isbn13(isbn10)
        canonical = isbn13 or isbn10
        return canonical, isbn10, isbn13

    return (None, None, None)


def _extract_and_validate_isbn(raw: str, isbn13: bool) -> str | None:
    pattern = ISBN13_RE if isbn13 else ISBN10_RE
    match = pattern.search(raw)
    if not match:
        return None
    digits = re.sub(r"[^0-9Xx]", "", match.group(1)).upper()
    if isbn13:
        if len(digits) != 13 or not digits.isdigit():
            return None
        return digits if is_valid_isbn13(digits) else None
    if len(digits) != 10:
        return None
    return digits if is_valid_isbn10(digits) else None


def is_valid_isbn10(value: str) -> bool:
    if len(value) != 10:
        return False
    total = 0
    for index, char in enumerate(value[:9]):
        if not char.isdigit():
            return False
        total += (10 - index) * int(char)

    check_char = value[9]
    if check_char == "X":
        check = 10
    elif check_char.isdigit():
        check = int(check_char)
    else:
        return False
    total += check
    return total % 11 == 0


def isbn10_to_isbn13(value: str) -> str | None:
    if not is_valid_isbn10(value):
        return None
    core = "978" + value[:9]
    check = _isbn13_check_digit(core)
    return core + check


def is_valid_isbn13(value: str) -> bool:
    if len(value) != 13 or not value.isdigit():
        return False
    return _isbn13_check_digit(value[:12]) == value[12]


def isbn13_to_isbn10(value: str) -> str | None:
    if not is_valid_isbn13(value):
        return None
    if not value.startswith("978"):
        return None
    core = value[3:12]
    total = 0
    for index, char in enumerate(core):
        total += (10 - index) * int(char)
    remainder = total % 11
    check_value = (11 - remainder) % 11
    check = "X" if check_value == 10 else str(check_value)
    return core + check


def _isbn13_check_digit(first_12: str) -> str:
    total = 0
    for index, char in enumerate(first_12):
        digit = int(char)
        total += digit if index % 2 == 0 else digit * 3
    return str((10 - (total % 10)) % 10)


def extract_metadata(opf_path: Path) -> dict:
    tree = ET.parse(opf_path)
    root = tree.getroot()
    metadata = None
    for child in root.iter():
        if local_name(child.tag) == "metadata":
            metadata = child
            break
    if metadata is None:
        raise ValueError("Missing metadata element")

    fields: dict[str, object] = {}

    def metadata_elements(name: str) -> list[ET.Element]:
        return [element for element in metadata if local_name(element.tag) == name]

    title = first_text(metadata_elements("title"))
    if title:
        fields["title"] = title

    authors = all_text(metadata_elements("creator"))
    if authors:
        fields["authors"] = authors

    publisher = first_text(metadata_elements("publisher"))
    if publisher:
        fields["publisher"] = publisher

    published_date = normalize_date(first_text(metadata_elements("date")))
    if published_date:
        fields["publishedDate"] = published_date

    description = first_text(metadata_elements("description"))
    if description:
        fields["description"] = description

    language = first_text(metadata_elements("language"))
    if language:
        fields["language"] = language

    categories = all_text(metadata_elements("subject"))
    if categories:
        fields["categories"] = categories

    isbn_info = extract_isbn(metadata_elements("identifier"))
    if isbn_info:
        _, isbn10, isbn13 = isbn_info
        if isbn10:
            fields["isbn10"] = isbn10
        if isbn13:
            fields["isbn13"] = isbn13

    series_name = extract_meta_value(metadata, "calibre:series")
    series_number_raw = extract_meta_value(metadata, "calibre:series_index")
    if series_name or series_number_raw:
        series_data: dict[str, object] = {}
        if series_name:
            series_data["name"] = series_name
        if series_number_raw:
            series_number = parse_numeric(series_number_raw)
            if series_number is not None:
                series_data["number"] = series_number
        if series_data:
            fields["series"] = series_data

    return fields


def build_sidecar_payload(metadata: dict, cover_name: str | None) -> dict:
    metadata = normalize_sidecar_metadata(metadata)
    payload: dict[str, object] = {
        "version": "1.0",
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "generatedBy": "booklore",
        "metadata": metadata,
    }
    if cover_name:
        payload["cover"] = {
            "source": "external",
            "path": cover_name,
        }
    return payload


def normalize_sidecar_metadata(metadata: dict) -> dict:
    normalized: dict[str, object] = {}
    for field_name in SIDECAR_BOOK_METADATA_ORDER:
        if field_name in metadata and metadata[field_name] is not None:
            normalized[field_name] = metadata[field_name]
    for field_name, value in metadata.items():
        if field_name not in normalized and value is not None:
            normalized[field_name] = value
    return normalized


def extract_meta_value(metadata: ET.Element, name: str) -> str | None:
    for element in metadata:
        if local_name(element.tag) != "meta":
            continue
        attrs = element.attrib
        if attrs.get("name") == name:
            content = clean_text(attrs.get("content"))
            if content:
                return content
        if attrs.get("{http://www.idpf.org/2007/opf}name") == name:
            content = clean_text(attrs.get("{http://www.idpf.org/2007/opf}content"))
            if content:
                return content
    return None


def extract_isbn(identifier_elements: list[ET.Element]) -> tuple[str | None, str | None, str | None] | None:
    for element in identifier_elements:
        text = clean_text("".join(element.itertext()))
        if not text:
            continue

        attrs = {key.lower(): value for key, value in element.attrib.items()}
        scheme = clean_text(attrs.get("scheme"))
        identifier_id = clean_text(attrs.get("id"))
        if scheme.lower() == "isbn" or "isbn" in identifier_id.lower():
            isbn = normalize_isbn(text)
            if isbn[0] or isbn[1] or isbn[2]:
                return isbn

        isbn = normalize_isbn(text)
        if isbn[0] or isbn[1] or isbn[2]:
            return isbn

    return None


def parse_numeric(value: str) -> int | float | None:
    text = value.strip()
    if not text:
        return None
    try:
        integer = int(text)
    except ValueError:
        try:
            number = float(text)
        except ValueError:
            return None
        return number
    return integer


def discover_book_files(folder: Path, allowed_exts: set[str]) -> list[Path]:
    book_files: list[Path] = []
    for item in folder.iterdir():
        if not item.is_file():
            continue
        if item.name.lower() == "metadata.opf":
            continue
        if item.name.lower() in COVER_NAMES:
            continue
        if item.suffix.lower() not in SUPPORTED_BOOK_EXTS:
            continue
        if allowed_exts and item.suffix.lower() not in allowed_exts:
            continue
        book_files.append(item)
    return sorted(book_files)


def discover_book_files_for_opf(opf_path: Path, allowed_exts: set[str]) -> list[Path]:
    folder = opf_path.parent
    if opf_path.name.lower() == "metadata.opf":
        return discover_book_files(folder, allowed_exts)

    matched_files: list[Path] = []
    for ext in sorted(SUPPORTED_BOOK_EXTS):
        candidate = folder / f"{opf_path.stem}{ext}"
        if not candidate.is_file():
            continue
        if allowed_exts and candidate.suffix.lower() not in allowed_exts:
            continue
        matched_files.append(candidate)
    return matched_files


def find_cover_for_opf(opf_path: Path, book_file: Path | None = None) -> str | None:
    folder = opf_path.parent

    if book_file is not None:
        for ext in SUPPORTED_COVER_EXTS:
            candidate = folder / f"{book_file.stem}{ext}"
            if candidate.is_file():
                return candidate.name

    for cover_name in COVER_NAMES:
        candidate = folder / cover_name
        if candidate.is_file():
            return candidate.name

    return None


def target_cover_path(book_file: Path) -> Path:
    return book_file.with_name(f"{book_file.stem}.cover.jpg")


def write_sidecar_cover(source_path: Path, target_path: Path) -> None:
    if source_path == target_path:
        return

    target_path.parent.mkdir(parents=True, exist_ok=True)
    source_suffix = source_path.suffix.lower()
    if source_suffix in {".jpg", ".jpeg"}:
        target_path.write_bytes(source_path.read_bytes())
        return

    try:
        from PIL import Image
    except Exception:
        target_path.write_bytes(source_path.read_bytes())
        return

    with Image.open(source_path) as image:
        if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
            rgba = image.convert("RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.getchannel("A"))
            background.save(target_path, format="JPEG", quality=95, optimize=True)
        else:
            image.convert("RGB").save(target_path, format="JPEG", quality=95, optimize=True)


def iter_opf_files(root: Path) -> list[Path]:
    opf_files: list[Path] = []
    for item in root.rglob("*"):
        if not item.is_file():
            continue
        lower_name = item.name.lower()
        if lower_name == "metadata.opf" or lower_name.endswith(".opf"):
            opf_files.append(item)
    return sorted(opf_files)


def target_json_path(book_file: Path) -> Path:
    return book_file.with_name(f"{book_file.stem}.metadata.json")


def write_sidecar(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def process_opf(
    opf_path: Path,
    allowed_exts: set[str],
    write: bool,
    overwrite: bool,
    stats: RunStats,
    log: Callable[[str], None],
) -> None:
    stats.opf_files_found += 1

    try:
        metadata = extract_metadata(opf_path)
    except Exception as exc:  # noqa: BLE001
        stats.parse_errors += 1
        log(f"ERROR parse OPF {opf_path} :: {exc}")
        return

    folder = opf_path.parent
    book_files = discover_book_files_for_opf(opf_path, allowed_exts)
    if not book_files:
        stats.no_book_file += 1
        log(f"SKIP no book file {opf_path}")
        return

    seen_json_targets: set[Path] = set()
    for book_file in book_files:
        stats.book_files_found += 1
        cover_name = find_cover_for_opf(opf_path, book_file)
        cover_source_path = folder / cover_name if cover_name else None
        cover_target_path_value = target_cover_path(book_file)
        if cover_name:
            stats.cover_found += 1
            log(f"INFO cover found {cover_source_path} -> {cover_target_path_value}")

        output_path = target_json_path(book_file)
        if output_path.exists() and not overwrite:
            stats.skipped_existing += 1
            log(f"SKIP exists {output_path}")
            continue

        if output_path in seen_json_targets:
            log(f"SKIP duplicate target {output_path}")
            continue
        seen_json_targets.add(output_path)

        payload = build_sidecar_payload(metadata.copy(), cover_target_path_value.name if cover_name else None)

        if write:
            try:
                if cover_source_path is not None:
                    write_sidecar_cover(cover_source_path, cover_target_path_value)
                write_sidecar(output_path, payload)
            except Exception as exc:  # noqa: BLE001
                stats.write_errors += 1
                log(f"ERROR write JSON {output_path} :: {exc}")
                continue
            stats.json_created += 1
            log(f"CREATE {output_path}")
        else:
            log(f"CREATE {output_path} [dry-run]")
        stats.json_planned += 1


def scan_library(
    root: Path,
    allowed_exts: set[str],
    write: bool,
    overwrite: bool,
    log: Callable[[str], None] = print,
) -> RunStats:
    stats = RunStats()
    opf_paths = iter_opf_files(root)
    if not opf_paths:
        log(f"SKIP no OPF files found under {root}")
        return stats

    for opf_path in opf_paths:
        process_opf(opf_path, allowed_exts, write, overwrite, stats, log)
    return stats


def summary_lines(stats: RunStats) -> list[str]:
    return [
        "SUMMARY",
        f"OPF files found: {stats.opf_files_found}",
        f"Book files found: {stats.book_files_found}",
        f"JSON files planned: {stats.json_planned}",
        f"JSON files created: {stats.json_created}",
        f"Skipped existing files: {stats.skipped_existing}",
        f"Parse errors: {stats.parse_errors}",
        f"Write errors: {stats.write_errors}",
        f"Covers found: {stats.cover_found}",
    ]


def print_summary(stats: RunStats, log: Callable[[str], None] = print) -> None:
    for line in summary_lines(stats):
        log(line)


def validate_root(root: Path) -> tuple[bool, str | None]:
    if not root.exists():
        return False, f"ERROR root not found: {root}"
    if not root.is_dir():
        return False, f"ERROR root is not a directory: {root}"
    return True, None


def normalize_allowed_exts(ext_value: str, log: Callable[[str], None] = print) -> set[str]:
    allowed_exts = normalize_extensions(ext_value)
    if allowed_exts:
        unknown = sorted(ext for ext in allowed_exts if ext not in SUPPORTED_BOOK_EXTS)
        if unknown:
            log(
                "WARNING unsupported ext filters will be ignored: "
                + ", ".join(unknown)
            )
            allowed_exts = {ext for ext in allowed_exts if ext in SUPPORTED_BOOK_EXTS}
    return allowed_exts


def run_cli(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    valid, error_message = validate_root(root)
    if not valid:
        print(error_message)
        return 2

    allowed_exts = normalize_allowed_exts(args.ext)
    stats = scan_library(root, allowed_exts, write=args.write, overwrite=args.overwrite)
    print_summary(stats)
    return 0


def choose_gui_options() -> dict[str, object] | None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog

    root = tk.Tk()
    root.withdraw()
    root.update()

    selected_folder = filedialog.askdirectory(
        title="Select your Grimmory / Calibre library folder"
    )
    if not selected_folder:
        root.destroy()
        return None

    write_files = messagebox.askyesno(
        "Create sidecar files?",
        "Yes = create .metadata.json files now\nNo = dry-run only",
        parent=root,
    )
    overwrite = False
    if write_files:
        overwrite = messagebox.askyesno(
            "Overwrite existing files?",
            "Overwrite existing .metadata.json files if they already exist?",
            parent=root,
        )

    ext_value = simpledialog.askstring(
        "Optional extension filter",
        "Leave blank for all supported files, or enter values like: pdf,epub",
        parent=root,
    )
    root.destroy()
    return {
        "root": selected_folder,
        "write": write_files,
        "overwrite": overwrite,
        "ext": ext_value or "",
    }


def run_gui() -> int:
    try:
        import tkinter as tk
        from tkinter import messagebox, scrolledtext
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR GUI unavailable: {exc}")
        return 2

    options = choose_gui_options()
    if options is None:
        return 0

    selected_root = Path(str(options["root"])).expanduser()
    valid, error_message = validate_root(selected_root)
    if not valid:
        messagebox.showerror("OPF to Grimmory JSON", error_message)
        return 2

    collected_logs: list[str] = []
    allowed_exts = normalize_allowed_exts(str(options["ext"]), collected_logs.append)

    window = tk.Tk()
    window.title("OPF to Grimmory JSON")
    window.geometry("820x520")

    info_label = tk.Label(
        window,
        text=(
            f"Folder: {selected_root}\n"
            f"Mode: {'WRITE' if options['write'] else 'DRY-RUN'}"
            f"{' | OVERWRITE' if options['overwrite'] else ''}"
        ),
        justify="left",
        anchor="w",
    )
    info_label.pack(fill="x", padx=12, pady=(12, 6))

    log_view = scrolledtext.ScrolledText(window, wrap="word", state="disabled")
    log_view.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def append_log(line: str) -> None:
        collected_logs.append(line)
        log_view.configure(state="normal")
        log_view.insert("end", line + "\n")
        log_view.see("end")
        log_view.configure(state="disabled")
        window.update_idletasks()

    pending_logs = list(collected_logs)
    collected_logs.clear()
    for line in pending_logs:
        append_log(line)

    def do_run() -> None:
        try:
            stats = scan_library(
                selected_root,
                allowed_exts,
                write=bool(options["write"]),
                overwrite=bool(options["overwrite"]),
                log=append_log,
            )
        except Exception as exc:  # noqa: BLE001
            append_log(f"ERROR unexpected failure :: {exc}")
            messagebox.showerror(
                "OPF to Grimmory JSON",
                f"Unexpected error:\n{exc}",
                parent=window,
            )
            return

        append_log("")
        print_summary(stats, append_log)
        messagebox.showinfo(
            "OPF to Grimmory JSON",
            "\n".join(summary_lines(stats)),
            parent=window,
        )

    window.after(100, do_run)
    window.mainloop()
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        return run_gui()

    args = parse_args(argv)
    if args.gui:
        return run_gui()
    return run_cli(args)


if __name__ == "__main__":
    raise SystemExit(main())
