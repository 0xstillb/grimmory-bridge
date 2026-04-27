#!/usr/bin/env python3
"""Embed adjacent OPF metadata into EPUB and PDF files for Grimmory."""

from __future__ import annotations

import argparse
import ctypes
import copy
import os
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Callable
from zipfile import ZipInfo
from ctypes import wintypes


def _bootstrap_bundled_python_packages() -> None:
    candidates = [
        Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "python",
        Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "python" / "Lib" / "site-packages",
    ]
    for candidate in candidates:
        if candidate.exists():
            sys.path.insert(0, str(candidate))


def configure_console_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


try:
    from lxml import etree
    from pypdf import PdfReader, PdfWriter
except ModuleNotFoundError:
    _bootstrap_bundled_python_packages()
    from lxml import etree
    from pypdf import PdfReader, PdfWriter

from opf_to_grimmory_json import (
    build_sidecar_payload as build_grimmory_sidecar_payload,
    discover_book_files_for_opf,
    extract_isbn,
    extract_meta_value,
    extract_metadata,
    find_cover_for_opf as find_grimmory_cover_name,
    local_name,
    normalize_date,
    parse_numeric,
    iter_opf_files,
    normalize_allowed_exts,
    target_cover_path as grimmory_target_cover_path,
    target_json_path as metadata_json_path,
    write_sidecar_cover as write_metadata_cover,
    write_sidecar as write_metadata_json,
    validate_root,
)


DC_NS = "http://purl.org/dc/elements/1.1/"
OPF_NS = "http://www.idpf.org/2007/opf"
CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
X_NS = "adobe:ns:meta/"
XMP_NS = "http://ns.adobe.com/xap/1.0/"
XMPIDQ_NS = "http://ns.adobe.com/xmp/Identifier/qual/1.0/"
BOOKLORE_NS = "http://booklore.org/metadata/1.0/"
CALIBRE_NS = "http://calibre-ebook.com/xmp-namespace"
CALIBRE_SI_NS = "http://calibre-ebook.com/xmp-namespace/seriesIndex"

SUPPORTED_EXTS = {".pdf", ".epub"}
APP_NAME = "Grimmory Bridge"
APP_SUBTITLE = "OPF to Embedded and JSON"
APP_WINDOW_TITLE = f"{APP_NAME} - {APP_SUBTITLE}"


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    def __init__(self, guid_string: str) -> None:
        super().__init__()
        import uuid

        uuid_value = uuid.UUID(guid_string)
        self.Data1 = uuid_value.time_low
        self.Data2 = uuid_value.time_mid
        self.Data3 = uuid_value.time_hi_version
        self.Data4[:] = uuid_value.bytes[8:]


CLSID_FileOpenDialog = GUID("{DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7}")
IID_IFileOpenDialog = GUID("{D57C7288-D4AD-4768-BE02-9D969532D960}")
IID_IShellItemArray = GUID("{B63EA76D-1F85-456F-A19C-48159EFA858B}")
IID_IShellItem = GUID("{43826D1E-E718-42EE-BC55-A1E261C37BFE}")

CLSCTX_INPROC_SERVER = 0x1
FOS_OVERWRITEPROMPT = 0x2
FOS_STRICTFILETYPES = 0x4
FOS_NOCHANGEDIR = 0x8
FOS_PICKFOLDERS = 0x20
FOS_FORCEFILESYSTEM = 0x40
FOS_ALLNONSTORAGEITEMS = 0x80
FOS_NOVALIDATE = 0x100
FOS_ALLOWMULTISELECT = 0x200
FOS_PATHMUSTEXIST = 0x800
SIGDN_FILESYSPATH = 0x80058000
HRESULT_FROM_WIN32_ERROR_CANCELLED = 0x800704C7


@dataclass
class RunStats:
    opf_files_found: int = 0
    book_files_found: int = 0
    files_planned: int = 0
    files_updated: int = 0
    files_unchanged: int = 0
    files_skipped: int = 0
    parse_errors: int = 0
    write_errors: int = 0
    no_book_file: int = 0
    json_planned: int = 0
    json_created: int = 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Grimmory Bridge scans a library for adjacent OPF files, embeds metadata "
            "into EPUB and PDF files, and writes Grimmory JSON sidecars."
        )
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Root folder to scan recursively for OPF files.",
    )
    parser.add_argument(
        "--ext",
        default="pdf,epub",
        help="Optional comma-separated list of book extensions to process.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Actually modify book files. Dry-run is the default.",
    )
    parser.add_argument(
        "--inspect",
        help="Inspect a single EPUB or PDF file and print a KOReader/Grimmory/Calibre compatibility report.",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Open a simple folder picker and run in GUI mode.",
    )
    return parser.parse_args(argv)


def summary_lines(stats: RunStats) -> list[str]:
    fields = [
        ("OPF files found", str(stats.opf_files_found)),
        ("Book files found", str(stats.book_files_found)),
        ("Files planned", str(stats.files_planned)),
        ("Files updated", str(stats.files_updated)),
        ("Files unchanged", str(stats.files_unchanged)),
        ("Files skipped", str(stats.files_skipped)),
        ("Parse errors", str(stats.parse_errors)),
        ("Write errors", str(stats.write_errors)),
        ("No matching book file", str(stats.no_book_file)),
        ("JSON files planned", str(stats.json_planned)),
        ("JSON files created", str(stats.json_created)),
    ]
    return ["SUMMARY", *format_key_value_lines(fields)]


def format_key_value_lines(items: list[tuple[str, str]], indent: str = "  ") -> list[str]:
    if not items:
        return []
    width = max(len(key) for key, _ in items)
    return [f"{indent}{key.ljust(width)} : {value}" for key, value in items]


def print_summary(stats: RunStats, log: Callable[[str], None] = print) -> None:
    for line in summary_lines(stats):
        log(line)


def compact_text(value: str, max_length: int = 140) -> str:
    text = " ".join(value.split())
    if len(text) <= max_length:
        return text
    return text[: max_length - 3].rstrip() + "..."


def clean_joined_list(value: object, separator: str) -> str:
    if not isinstance(value, list):
        return ""
    cleaned = [compact_text(str(item), 50) for item in value if str(item).strip()]
    return separator.join(cleaned)


def format_numeric_value(value: object) -> str:
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return compact_text(str(value), 20)


def series_to_text(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    name = str(value.get("name", "")).strip()
    number = value.get("number")
    if number is None:
        return name
    if name:
        return f"{name} #{format_numeric_value(number)}"
    return f"#{format_numeric_value(number)}"


def metadata_field_text(metadata: dict, field_name: str) -> str:
    value = metadata.get(field_name)
    if field_name == "authors":
        return clean_joined_list(value, " | ")
    if field_name == "categories":
        return clean_joined_list(value, "; ")
    if field_name == "series":
        return compact_text(series_to_text(value))
    if value is None:
        return ""
    if isinstance(value, str):
        max_length = 180 if field_name == "description" else 140
        return compact_text(value, max_length)
    return compact_text(str(value))


def diff_metadata_lines(current_metadata: dict, target_metadata: dict) -> list[str]:
    field_order = [
        "title",
        "authors",
        "publisher",
        "publishedDate",
        "language",
        "categories",
        "isbn13",
        "isbn10",
        "series",
        "description",
    ]
    lines: list[str] = []
    for field_name in field_order:
        old_text = metadata_field_text(current_metadata, field_name)
        new_text = metadata_field_text(target_metadata, field_name)
        if old_text == new_text:
            continue
        if not old_text:
            old_text = "[empty]"
        if not new_text:
            new_text = "[empty]"
        lines.append(f"  {field_name}: {old_text} -> {new_text}")
    return lines


def missing_required_fields(metadata: dict, required_fields: list[str]) -> list[str]:
    return [field_name for field_name in required_fields if not metadata_field_text(metadata, field_name)]


def first_xml_text(elements: list[etree._Element]) -> str | None:
    for element in elements:
        text = compact_text("".join(element.itertext()), 10000).strip()
        if text:
            return text
    return None


def all_xml_text(elements: list[etree._Element]) -> list[str]:
    values: list[str] = []
    for element in elements:
        text = compact_text("".join(element.itertext()), 10000).strip()
        if text:
            values.append(text)
    return values


def parse_author_text(value: str | None) -> list[str]:
    if not value:
        return []
    normalized = value.replace("&", ",")
    return [part.strip() for part in normalized.split(",") if part.strip()]


def parse_keyword_text(value: str | None) -> list[str]:
    if not value:
        return []
    separator = ";" if ";" in value else ","
    return [part.strip() for part in value.split(separator) if part.strip()]


def parse_pdf_info_date(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    if text.startswith("D:"):
        text = text[2:]
    if len(text) >= 8 and text[:8].isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return normalize_date(text)


def xml_text(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.split()).strip()


def xml_first_text(elements: list[etree._Element]) -> str | None:
    for element in elements:
        text = xml_text("".join(element.itertext()))
        if text:
            return text
    return None


def xml_all_text(elements: list[etree._Element]) -> list[str]:
    values: list[str] = []
    for element in elements:
        text = xml_text("".join(element.itertext()))
        if text:
            values.append(text)
    return values


def extract_epub_metadata_from_opf_bytes(opf_bytes: bytes) -> dict:
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
    root = etree.fromstring(opf_bytes, parser=parser)
    metadata = metadata_element(root)

    def metadata_elements(name: str) -> list[etree._Element]:
        return [element for element in metadata if local_name(element.tag) == name]

    fields: dict[str, object] = {}

    title = xml_first_text(metadata_elements("title"))
    if title:
        fields["title"] = title

    authors = xml_all_text(metadata_elements("creator"))
    if authors:
        fields["authors"] = authors

    publisher = xml_first_text(metadata_elements("publisher"))
    if publisher:
        fields["publisher"] = publisher

    published_date = normalize_date(xml_first_text(metadata_elements("date")))
    if published_date:
        fields["publishedDate"] = published_date

    description = xml_first_text(metadata_elements("description"))
    if description:
        fields["description"] = description

    language = xml_first_text(metadata_elements("language"))
    if language:
        fields["language"] = language

    categories = xml_all_text(metadata_elements("subject"))
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

    if not series_name:
        collection_by_id: dict[str, str] = {}
        group_position_by_ref: dict[str, str] = {}
        for element in metadata:
            if local_name(element.tag) != "meta":
                continue
            prop = (element.get("property") or "").strip()
            content = (element.get("content") or xml_text(element.text or "")).strip()
            if prop == "belongs-to-collection":
                collection_id = (element.get("id") or "").strip()
                if collection_id and content:
                    collection_by_id[collection_id] = content
                elif content and not series_name:
                    series_name = content
            elif prop == "group-position":
                refines = (element.get("refines") or "").lstrip("#").strip()
                if refines and content:
                    group_position_by_ref[refines] = content
        if not series_name and collection_by_id:
            first_id = next(iter(collection_by_id))
            series_name = collection_by_id[first_id]
            series_number_raw = group_position_by_ref.get(first_id)
        elif series_name and not series_number_raw:
            for collection_id, collection_name in collection_by_id.items():
                if collection_name == series_name:
                    series_number_raw = group_position_by_ref.get(collection_id)
                    if series_number_raw:
                        break

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


def extract_pdf_metadata_from_xmp_bytes(xmp_bytes: bytes) -> dict:
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
    root = etree.fromstring(xmp_bytes, parser=parser)
    namespaces = {
        "dc": DC_NS,
        "rdf": RDF_NS,
        "xmp": XMP_NS,
        "xmpidq": XMPIDQ_NS,
        "booklore": BOOKLORE_NS,
        "calibre": CALIBRE_NS,
        "calibreSI": CALIBRE_SI_NS,
    }
    fields: dict[str, object] = {}

    def xpath_text(expr: str) -> str | None:
        values = root.xpath(expr, namespaces=namespaces)
        if not values:
            return None
        first = values[0]
        return xml_text(str(first))

    def xpath_texts(expr: str) -> list[str]:
        values = root.xpath(expr, namespaces=namespaces)
        return [xml_text(str(value)) for value in values if xml_text(str(value))]

    title = xpath_text("//dc:title/rdf:Alt/rdf:li/text()")
    if title:
        fields["title"] = title

    description = xpath_text("//dc:description/rdf:Alt/rdf:li/text()")
    if description:
        fields["description"] = description

    publisher = xpath_text("//dc:publisher/rdf:Bag/rdf:li/text()")
    if publisher:
        fields["publisher"] = publisher

    language = xpath_text("//dc:language/rdf:Bag/rdf:li/text()")
    if language:
        fields["language"] = language

    authors = xpath_texts("//dc:creator/rdf:Seq/rdf:li/text()")
    if authors:
        fields["authors"] = authors

    categories = xpath_texts("//dc:subject/rdf:Bag/rdf:li/text()")
    if categories:
        fields["categories"] = categories

    published_date = normalize_date(xpath_text("//xmp:CreateDate/text()"))
    if published_date:
        fields["publishedDate"] = published_date

    identifier_nodes = root.xpath("//xmp:Identifier/rdf:Bag/rdf:li", namespaces=namespaces)
    for node in identifier_nodes:
        scheme_values = node.xpath("xmpidq:Scheme/text()", namespaces=namespaces)
        value_values = node.xpath("rdf:value/text()", namespaces=namespaces)
        if not scheme_values or not value_values:
            continue
        scheme = xml_text(str(scheme_values[0])).lower()
        value = xml_text(str(value_values[0]))
        if scheme == "isbn13":
            fields["isbn13"] = value
        elif scheme == "isbn10":
            fields["isbn10"] = value
        elif scheme == "isbn" and "isbn13" not in fields and "isbn10" not in fields:
            if len(value) == 13:
                fields["isbn13"] = value
            elif len(value) == 10:
                fields["isbn10"] = value

    series_name = xpath_text("//booklore:seriesName/text()")
    series_number_raw = xpath_text("//booklore:seriesNumber/text()")
    if not series_name:
        series_name = xpath_text("//calibre:series/rdf:value/text()")
    if not series_number_raw:
        series_number_raw = xpath_text("//calibre:series/calibreSI:series_index/text()")
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


def read_current_pdf_metadata(book_path: Path) -> dict:
    reader = PdfReader(BytesIO(book_path.read_bytes()))
    fields: dict[str, object] = {}
    info = reader.metadata or {}

    title = info.get("/Title")
    if title:
        fields["title"] = str(title)

    authors = parse_author_text(info.get("/Author"))
    if authors:
        fields["authors"] = authors

    publisher = info.get("/EBX_PUBLISHER") or info.get("/Publisher")
    if publisher:
        fields["publisher"] = str(publisher)

    published_date = parse_pdf_info_date(info.get("/CreationDate"))
    if published_date:
        fields["publishedDate"] = published_date

    description = info.get("/Subject")
    if description:
        fields["description"] = str(description)

    language = info.get("/Language")
    if language:
        fields["language"] = str(language)

    categories = parse_keyword_text(info.get("/Keywords"))
    if categories:
        fields["categories"] = categories

    xmp = reader.xmp_metadata
    if xmp is not None and getattr(xmp, "stream", None) is not None:
        xmp_fields = extract_pdf_metadata_from_xmp_bytes(xmp.stream.get_data())
        fields.update({key: value for key, value in xmp_fields.items() if value})

    return fields


def read_current_epub_metadata(book_path: Path) -> dict:
    opf_path = find_opf_path(book_path)
    with zipfile.ZipFile(book_path, "r") as archive:
        opf_bytes = archive.read(opf_path)
    return extract_epub_metadata_from_opf_bytes(opf_bytes)


def read_current_embedded_metadata(book_path: Path) -> dict:
    suffix = book_path.suffix.lower()
    if suffix == ".pdf":
        return read_current_pdf_metadata(book_path)
    if suffix == ".epub":
        return read_current_epub_metadata(book_path)
    return {}


def build_preview_message(book_path: Path, current_metadata: dict, target_metadata: dict, write: bool) -> str:
    mode = "write" if write else "dry-run"
    lines = [
        "FILE",
        f"  path: {book_path}",
        f"  mode: {mode}",
    ]
    diff_lines = diff_metadata_lines(current_metadata, target_metadata)
    if diff_lines:
        field_count = len(diff_lines)
        lines.append(f"  changes ({field_count} field{'s' if field_count != 1 else ''}):")
        lines.extend(f"    {line.strip()}" for line in diff_lines)
    else:
        lines.append("  status: no metadata changes detected")
    return "\n".join(lines)


def build_json_preview_message(
    book_path: Path,
    metadata: dict,
    write: bool,
    cover_name: str | None = None,
) -> str:
    mode = "write" if write else "dry-run"
    json_path = metadata_json_path(book_path)
    series_detail = series_source_note(book_path, metadata).removeprefix("series source: ").strip()
    lines = [
        "JSON",
        f"  target: {json_path}",
        f"  mode: {mode}",
    ]
    visible_fields = [
        field_name
        for field_name in ["title", "authors", "publisher", "publishedDate", "language", "series"]
        if metadata_field_text(metadata, field_name)
    ]
    lines.append("  metadata: " + (", ".join(visible_fields) if visible_fields else "[empty]"))
    lines.append(f"  cover: {cover_name or '[none]'}")
    lines.append(f"  note: {series_detail}")
    return "\n".join(lines)


def compatibility_summary_line(book_path: Path, metadata: dict) -> str:
    suffix = book_path.suffix.lower()
    koreader_fields = ["title", "authors", "language"] if suffix == ".epub" else ["title", "authors"]
    grimmory_fields = ["title", "authors"]
    calibre_fields = ["title", "authors"]
    koreader_missing = missing_required_fields(metadata, koreader_fields)
    grimmory_missing = missing_required_fields(metadata, grimmory_fields)
    calibre_missing = missing_required_fields(metadata, calibre_fields)

    series_note = series_source_note(book_path, metadata).removeprefix("series source: ").strip()
    lines = [
        "COMPATIBILITY",
        f"  KOReader : {'OK' if not koreader_missing else 'PARTIAL'} | core: {', '.join(koreader_fields)} | missing: {', '.join(koreader_missing) if koreader_missing else 'none'}",
        f"  Grimmory : {'OK' if not grimmory_missing else 'PARTIAL'} | core: {', '.join(grimmory_fields)} | missing: {', '.join(grimmory_missing) if grimmory_missing else 'none'}",
        f"  Calibre  : {'OK' if not calibre_missing else 'PARTIAL'} | core: {', '.join(calibre_fields)} | missing: {', '.join(calibre_missing) if calibre_missing else 'none'}",
        f"  series source: {series_note}",
    ]
    return "\n".join(lines)


def validate_book_path(book_path: Path) -> tuple[bool, str | None]:
    if not book_path.exists():
        return False, f"ERROR book file not found: {book_path}"
    if not book_path.is_file():
        return False, f"ERROR book path is not a file: {book_path}"
    if book_path.suffix.lower() not in SUPPORTED_EXTS:
        return False, f"ERROR unsupported book file type: {book_path.suffix}"
    return True, None


def _hresult_value(hr: object) -> int:
    return int(hr) & 0xFFFFFFFF


def _is_cancelled_hresult(hr: object) -> bool:
    return _hresult_value(hr) == HRESULT_FROM_WIN32_ERROR_CANCELLED


def _com_call(obj: ctypes.c_void_p, index: int, restype, argtypes: list[object], *args):
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    func_type = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    func = func_type(vtable[index])
    return func(obj, *args)


def _release_com_object(obj: ctypes.c_void_p | None) -> None:
    if obj is None or not bool(obj):
        return
    try:
        _com_call(obj, 2, ctypes.c_long, [])
    except Exception:
        pass


def pick_folders_with_native_dialog(parent_hwnd: int | None, title: str) -> list[Path]:
    if sys.platform != "win32":
        return []

    ole32 = ctypes.windll.ole32
    dialog = ctypes.c_void_p()
    initialized = False

    hr = ole32.CoInitialize(None)
    initialized = _hresult_value(hr) in {0, 1}

    try:
        hr = ole32.CoCreateInstance(
            ctypes.byref(CLSID_FileOpenDialog),
            None,
            CLSCTX_INPROC_SERVER,
            ctypes.byref(IID_IFileOpenDialog),
            ctypes.byref(dialog),
        )
        if _hresult_value(hr) >= 0 and dialog:
            results = ctypes.c_void_p()
            try:
                options = ctypes.c_uint()
                hr = _com_call(dialog, 10, ctypes.c_long, [ctypes.POINTER(ctypes.c_uint)], ctypes.byref(options))
                if _hresult_value(hr) < 0:
                    raise OSError(f"GetOptions failed: 0x{_hresult_value(hr):08X}")

                options.value |= (
                    FOS_PICKFOLDERS
                    | FOS_ALLOWMULTISELECT
                    | FOS_FORCEFILESYSTEM
                    | FOS_PATHMUSTEXIST
                )
                hr = _com_call(dialog, 9, ctypes.c_long, [ctypes.c_uint], options.value)
                if _hresult_value(hr) < 0:
                    raise OSError(f"SetOptions failed: 0x{_hresult_value(hr):08X}")

                hr = _com_call(dialog, 17, ctypes.c_long, [ctypes.c_wchar_p], title)
                if _hresult_value(hr) < 0:
                    raise OSError(f"SetTitle failed: 0x{_hresult_value(hr):08X}")

                hwnd = wintypes.HWND(parent_hwnd or 0)
                hr = _com_call(dialog, 3, ctypes.c_long, [wintypes.HWND], hwnd)
                if _is_cancelled_hresult(hr):
                    return []
                if _hresult_value(hr) < 0:
                    raise OSError(f"Dialog show failed: 0x{_hresult_value(hr):08X}")

                hr = _com_call(dialog, 27, ctypes.c_long, [ctypes.POINTER(ctypes.c_void_p)], ctypes.byref(results))
                if _hresult_value(hr) < 0:
                    raise OSError(f"GetResults failed: 0x{_hresult_value(hr):08X}")

                count = ctypes.c_uint()
                hr = _com_call(results, 7, ctypes.c_long, [ctypes.POINTER(ctypes.c_uint)], ctypes.byref(count))
                if _hresult_value(hr) < 0:
                    raise OSError(f"GetCount failed: 0x{_hresult_value(hr):08X}")

                selected: list[Path] = []
                for index in range(count.value):
                    item = ctypes.c_void_p()
                    hr = _com_call(results, 8, ctypes.c_long, [ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)], index, ctypes.byref(item))
                    if _hresult_value(hr) < 0 or not item:
                        continue
                    try:
                        path_ptr = ctypes.c_void_p()
                        hr = _com_call(item, 5, ctypes.c_long, [ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)], SIGDN_FILESYSPATH, ctypes.byref(path_ptr))
                        if _hresult_value(hr) < 0 or not path_ptr.value:
                            continue
                        try:
                            selected.append(Path(ctypes.wstring_at(path_ptr.value)))
                        finally:
                            ole32.CoTaskMemFree(path_ptr)
                    finally:
                        _release_com_object(item)

                return selected
            finally:
                _release_com_object(results)
                _release_com_object(dialog)
        raise OSError(f"CoCreateInstance failed: 0x{_hresult_value(hr):08X}")
    finally:
        if initialized:
            ole32.CoUninitialize()


def epub_opf_version(book_path: Path) -> str | None:
    if book_path.suffix.lower() != ".epub":
        return None
    opf_path = find_opf_path(book_path)
    with zipfile.ZipFile(book_path, "r") as archive:
        opf_bytes = archive.read(opf_path)
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
    root = etree.fromstring(opf_bytes, parser=parser)
    return package_version(root) or None


def series_source_note(book_path: Path, metadata: dict) -> str:
    series = metadata.get("series")
    if not isinstance(series, dict) or not series.get("name"):
        return "series source: none"

    suffix = book_path.suffix.lower()
    if suffix == ".epub":
        version = epub_opf_version(book_path) or ""
        if version.startswith("3"):
            return "series source: EPUB3 collection markers plus calibre:series fallback"
        return "series source: calibre:series / calibre:series_index"

    if suffix == ".pdf":
        return "series source: XMP booklore:seriesName/seriesNumber plus calibre namespaces"

    return "series source: embedded metadata"


def format_field_status(metadata: dict, field_name: str) -> str:
    text = metadata_field_text(metadata, field_name)
    if text:
        return f"  {field_name}: ok -> {text}"
    return f"  {field_name}: missing"


def compatibility_verdict(metadata: dict, book_path: Path) -> str:
    required_fields = ["title", "authors"]
    if book_path.suffix.lower() == ".epub":
        required_fields.append("language")
    missing = missing_required_fields(metadata, required_fields)
    return "OK" if not missing else "PARTIAL"


def build_target_section(
    name: str,
    metadata: dict,
    required_fields: list[str],
    verdict_book_path: Path,
    notes: list[str],
) -> list[str]:
    missing = missing_required_fields(metadata, required_fields)
    lines = [
        name,
        f"  verdict: {compatibility_verdict(metadata, verdict_book_path)}",
        f"  required: {', '.join(required_fields)}",
        f"  missing: {', '.join(missing) if missing else 'none'}",
    ]
    lines.extend(notes)
    return lines


def build_compatibility_report_lines(book_path: Path) -> list[str]:
    metadata = read_current_embedded_metadata(book_path)
    suffix = book_path.suffix.lower()
    lines = [
        "COMPATIBILITY REPORT",
        f"File: {book_path}",
        f"Format: {suffix.lstrip('.').upper()}",
    ]
    if suffix == ".epub":
        version = epub_opf_version(book_path)
        if version:
            lines.append(f"OPF version: {version}")

    lines.append("Detected metadata:")
    for field_name in [
        "title",
        "authors",
        "publisher",
        "publishedDate",
        "language",
        "categories",
        "isbn13",
        "isbn10",
        "series",
        "description",
    ]:
        lines.append(format_field_status(metadata, field_name))

    series_note = series_source_note(book_path, metadata)
    lines.append(series_note)

    field_checks = [
        "  optional fields: publisher, tags, isbn, series, description",
    ]
    koreader_required = ["title", "authors", "language"]
    if suffix == ".pdf":
        field_checks = [
            "  optional fields: publisher, language, tags, isbn, series, description",
        ]
        koreader_required = ["title", "authors"]

    lines.append("")
    lines.append("Compatibility targets:")
    lines.extend(
        build_target_section(
            "KOReader",
            metadata,
            koreader_required,
            book_path,
            field_checks
            + ["  note: uses standard embedded metadata fields"]
            + [f"  note: {series_note}"],
        )
    )
    lines.append("")
    lines.extend(
        build_target_section(
            "Grimmory",
            metadata,
            ["title", "authors"],
            book_path,
            [
                "  note: uses this tool's embedded-metadata reader",
                f"  fields visible: {', '.join(field_name for field_name in ['title', 'authors', 'publisher', 'publishedDate', 'language', 'categories', 'isbn13', 'isbn10', 'series'] if metadata_field_text(metadata, field_name)) or 'none'}",
            ],
        )
    )
    lines.append("")
    lines.extend(
        build_target_section(
            "Calibre",
            metadata,
            ["title", "authors"],
            book_path,
            [
                "  note: uses standard OPF/XMP fields plus calibre series markers",
                f"  series handling: {series_note}",
            ],
        )
    )
    return lines


def print_compatibility_report(book_path: Path, log: Callable[[str], None] = print) -> None:
    for line in build_compatibility_report_lines(book_path):
        log(line)


def pdf_date_string(iso_date: str) -> str:
    year, month, day = iso_date.split("-", 2)
    return f"D:{year}{month}{day}000000"


def update_info_value(metadata: dict[str, str], key: str, value: str | None) -> None:
    if value:
        metadata[key] = value


def add_li_bag(parent: etree._Element, ns: str, tag: str, values: list[str]) -> None:
    if not values:
        return
    container = etree.SubElement(parent, etree.QName(ns, tag))
    bag = etree.SubElement(container, etree.QName(RDF_NS, "Bag"))
    for value in values:
        item = value.strip()
        if item:
            li = etree.SubElement(bag, etree.QName(RDF_NS, "li"))
            li.text = item


def add_alt_value(parent: etree._Element, ns: str, tag: str, value: str | None) -> None:
    if not value:
        return
    container = etree.SubElement(parent, etree.QName(ns, tag))
    alt = etree.SubElement(container, etree.QName(RDF_NS, "Alt"))
    li = etree.SubElement(alt, etree.QName(RDF_NS, "li"))
    li.set("{http://www.w3.org/XML/1998/namespace}lang", "x-default")
    li.text = value


def add_seq_values(parent: etree._Element, ns: str, tag: str, values: list[str]) -> None:
    if not values:
        return
    container = etree.SubElement(parent, etree.QName(ns, tag))
    seq = etree.SubElement(container, etree.QName(RDF_NS, "Seq"))
    for value in values:
        item = value.strip()
        if item:
            li = etree.SubElement(seq, etree.QName(RDF_NS, "li"))
            li.text = item


def build_pdf_xmp(metadata: dict) -> bytes:
    nsmap = {
        "x": X_NS,
        "rdf": RDF_NS,
        "dc": DC_NS,
        "xmp": XMP_NS,
        "xmpidq": XMPIDQ_NS,
        "booklore": BOOKLORE_NS,
        "calibre": CALIBRE_NS,
        "calibreSI": CALIBRE_SI_NS,
    }
    root = etree.Element(etree.QName(X_NS, "xmpmeta"), nsmap=nsmap)
    rdf = etree.SubElement(root, etree.QName(RDF_NS, "RDF"))

    desc = etree.SubElement(rdf, etree.QName(RDF_NS, "Description"))
    desc.set(etree.QName(RDF_NS, "about"), "")
    add_alt_value(desc, DC_NS, "title", metadata.get("title"))
    add_alt_value(desc, DC_NS, "description", metadata.get("description"))
    add_seq_values(desc, DC_NS, "creator", list(metadata.get("authors", [])))
    add_li_bag(desc, DC_NS, "publisher", [metadata["publisher"]] if metadata.get("publisher") else [])
    add_li_bag(desc, DC_NS, "language", [metadata["language"]] if metadata.get("language") else [])
    add_li_bag(desc, DC_NS, "subject", list(metadata.get("categories", [])))

    now_value = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    etree.SubElement(desc, etree.QName(XMP_NS, "CreatorTool")).text = "opf_to_embedded_metadata.py"
    etree.SubElement(desc, etree.QName(XMP_NS, "MetadataDate")).text = now_value
    etree.SubElement(desc, etree.QName(XMP_NS, "ModifyDate")).text = now_value

    published_date = metadata.get("publishedDate")
    if published_date:
        etree.SubElement(desc, etree.QName(XMP_NS, "CreateDate")).text = published_date

    identifiers = []
    isbn13 = metadata.get("isbn13")
    isbn10 = metadata.get("isbn10")
    if isbn13:
        identifiers.append(("isbn", isbn13))
        identifiers.append(("isbn13", isbn13))
    if isbn10:
        identifiers.append(("isbn10", isbn10))

    if identifiers:
        identifier_container = etree.SubElement(desc, etree.QName(XMP_NS, "Identifier"))
        bag = etree.SubElement(identifier_container, etree.QName(RDF_NS, "Bag"))
        for scheme, value in identifiers:
            li = etree.SubElement(bag, etree.QName(RDF_NS, "li"))
            li.set(etree.QName(RDF_NS, "parseType"), "Resource")
            etree.SubElement(li, etree.QName(XMPIDQ_NS, "Scheme")).text = scheme
            etree.SubElement(li, etree.QName(RDF_NS, "value")).text = value

    series = metadata.get("series")
    if isinstance(series, dict):
        series_name = series.get("name")
        series_number = series.get("number")
        if series_name:
            calibre_series = etree.SubElement(desc, etree.QName(CALIBRE_NS, "series"))
            etree.SubElement(calibre_series, etree.QName(RDF_NS, "value")).text = str(series_name)
            if series_number is not None:
                etree.SubElement(calibre_series, etree.QName(CALIBRE_SI_NS, "series_index")).text = str(series_number)
        if series.get("name"):
            etree.SubElement(desc, etree.QName(BOOKLORE_NS, "seriesName")).text = str(series["name"])
        if series.get("number") is not None:
            etree.SubElement(desc, etree.QName(BOOKLORE_NS, "seriesNumber")).text = str(series["number"])

    xml_bytes = etree.tostring(
        root,
        encoding="utf-8",
        xml_declaration=False,
        pretty_print=True,
    )
    packet = (
        b"<?xpacket begin='\xef\xbb\xbf' id='W5M0MpCehiHzreSzNTczkc9d'?>\n"
        + xml_bytes
        + b"\n<?xpacket end='w'?>"
    )
    return packet


def normalize_pdf_info(reader: PdfReader) -> dict[str, str]:
    result: dict[str, str] = {}
    meta = reader.metadata
    if not meta:
        return result
    for key, value in meta.items():
        if key is None or value is None:
            continue
        result[str(key)] = str(value)
    return result


def write_pdf_metadata(book_path: Path, metadata: dict) -> bool:
    reader = PdfReader(BytesIO(book_path.read_bytes()))
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)

    info = normalize_pdf_info(reader)
    update_info_value(info, "/Title", metadata.get("title"))
    if metadata.get("authors"):
        update_info_value(info, "/Author", ", ".join(metadata["authors"]))
    update_info_value(info, "/Subject", metadata.get("description"))
    if metadata.get("categories"):
        update_info_value(info, "/Keywords", "; ".join(metadata["categories"]))
    update_info_value(info, "/EBX_PUBLISHER", metadata.get("publisher"))
    update_info_value(info, "/Publisher", metadata.get("publisher"))
    update_info_value(info, "/Language", metadata.get("language"))
    if metadata.get("publishedDate"):
        update_info_value(info, "/CreationDate", pdf_date_string(metadata["publishedDate"]))
    writer.add_metadata(info)

    new_xmp = build_pdf_xmp(metadata)
    current_xmp = reader.xmp_metadata
    current_xmp_bytes = b""
    if current_xmp is not None and getattr(current_xmp, "stream", None) is not None:
        current_xmp_bytes = current_xmp.stream.get_data()
    writer.xmp_metadata = new_xmp

    changed = info != normalize_pdf_info(reader) or current_xmp_bytes != new_xmp
    if not changed:
        return False

    with tempfile.NamedTemporaryFile(
        delete=False,
        dir=book_path.parent,
        prefix=".pdfmeta-",
        suffix=".pdf",
    ) as handle:
        temp_path = Path(handle.name)
    try:
        with temp_path.open("wb") as stream:
            writer.write(stream)
        os.replace(temp_path, book_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return True


def parse_xml_bytes(content: bytes) -> etree._ElementTree:
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
    return etree.fromstring(content, parser=parser).getroottree()


def find_opf_path(epub_path: Path) -> str:
    with zipfile.ZipFile(epub_path, "r") as archive:
        container_bytes = archive.read("META-INF/container.xml")
    tree = parse_xml_bytes(container_bytes)
    rootfile = tree.find(".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile")
    if rootfile is None:
        raise ValueError("EPUB container.xml does not declare an OPF rootfile")
    full_path = rootfile.get("full-path")
    if not full_path:
        raise ValueError("EPUB container.xml rootfile is missing full-path")
    return full_path


def qname(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def metadata_element(opf_root: etree._Element) -> etree._Element:
    element = opf_root.find(f".//{qname(OPF_NS, 'metadata')}")
    if element is None:
        raise ValueError("OPF file is missing a metadata element")
    return element


def package_version(opf_root: etree._Element) -> str:
    return opf_root.get("version", "").strip()


def remove_children(parent: etree._Element, predicate: Callable[[etree._Element], bool]) -> list[etree._Element]:
    removed: list[etree._Element] = []
    for child in list(parent):
        if predicate(child):
            removed.append(child)
            parent.remove(child)
    return removed


def first_or_new(metadata_el: etree._Element, ns: str, tag: str) -> etree._Element:
    found = metadata_el.find(qname(ns, tag))
    if found is not None:
        return found
    new_el = etree.Element(qname(ns, tag))
    metadata_el.append(new_el)
    return new_el


def replace_simple_dc(metadata_el: etree._Element, tag: str, value: str) -> None:
    element = first_or_new(metadata_el, DC_NS, tag)
    element.text = value


def remove_refined_meta(metadata_el: etree._Element, removed_ids: set[str]) -> None:
    if not removed_ids:
        return
    for child in list(metadata_el):
        if etree.QName(child).localname != "meta":
            continue
        refines = (child.get("refines") or "").lstrip("#")
        if refines in removed_ids:
            metadata_el.remove(child)


def replace_epub_authors(metadata_el: etree._Element, authors: list[str]) -> None:
    removed_ids: set[str] = set()
    for child in list(metadata_el):
        if etree.QName(child).localname != "creator" or etree.QName(child).namespace != DC_NS:
            continue
        creator_id = child.get("id")
        if creator_id:
            removed_ids.add(creator_id)
        metadata_el.remove(child)
    remove_refined_meta(metadata_el, removed_ids)
    for author in authors:
        creator = etree.Element(qname(DC_NS, "creator"))
        creator.text = author
        metadata_el.append(creator)


def replace_epub_subjects(metadata_el: etree._Element, categories: list[str]) -> None:
    remove_children(
        metadata_el,
        lambda child: etree.QName(child).namespace == DC_NS
        and etree.QName(child).localname == "subject",
    )
    for category in categories:
        subject = etree.Element(qname(DC_NS, "subject"))
        subject.text = category
        metadata_el.append(subject)


def remove_epub_identifiers(metadata_el: etree._Element, schemes: set[str]) -> None:
    for child in list(metadata_el):
        if etree.QName(child).namespace != DC_NS or etree.QName(child).localname != "identifier":
            continue
        text = (child.text or "").strip().lower()
        scheme = (child.get(qname(OPF_NS, "scheme")) or "").strip().lower()
        if scheme in schemes:
            metadata_el.remove(child)
            continue
        if text.startswith("urn:isbn:") or text.startswith("isbn:"):
            metadata_el.remove(child)


def append_identifier(metadata_el: etree._Element, value: str) -> None:
    identifier = etree.Element(qname(DC_NS, "identifier"))
    identifier.text = f"urn:isbn:{value}"
    metadata_el.append(identifier)


def remove_series_metadata(metadata_el: etree._Element) -> None:
    remove_children(
        metadata_el,
        lambda child: etree.QName(child).localname == "meta"
        and (
            (child.get("property") or "") in {"belongs-to-collection", "collection-type", "group-position"}
            or (child.get("name") or "") in {"calibre:series", "calibre:series_index"}
        ),
    )


def add_series_metadata(metadata_el: etree._Element, opf_root: etree._Element, series: dict) -> None:
    name = series.get("name")
    number = series.get("number")
    if not name:
        return

    remove_series_metadata(metadata_el)
    is_epub3 = package_version(opf_root).startswith("3")
    if is_epub3:
        collection_id = "collection-main"
        collection = etree.Element(qname(OPF_NS, "meta"))
        collection.set("id", collection_id)
        collection.set("property", "belongs-to-collection")
        collection.text = str(name)
        metadata_el.append(collection)

        collection_type = etree.Element(qname(OPF_NS, "meta"))
        collection_type.set("property", "collection-type")
        collection_type.set("refines", f"#{collection_id}")
        collection_type.text = "series"
        metadata_el.append(collection_type)

        if number is not None:
            group_position = etree.Element(qname(OPF_NS, "meta"))
            group_position.set("property", "group-position")
            group_position.set("refines", f"#{collection_id}")
            group_position.text = str(number)
            metadata_el.append(group_position)

    series_meta = etree.Element(qname(OPF_NS, "meta"))
    series_meta.set("name", "calibre:series")
    series_meta.set("content", str(name))
    metadata_el.append(series_meta)

    if number is not None:
        series_index = etree.Element(qname(OPF_NS, "meta"))
        series_index.set("name", "calibre:series_index")
        series_index.set("content", str(number))
        metadata_el.append(series_index)


def update_epub_opf(opf_bytes: bytes, metadata: dict) -> bytes:
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
    root = etree.fromstring(opf_bytes, parser=parser)
    metadata_el = metadata_element(root)

    if metadata.get("title"):
        replace_simple_dc(metadata_el, "title", metadata["title"])
    if metadata.get("description"):
        replace_simple_dc(metadata_el, "description", metadata["description"])
    if metadata.get("publisher"):
        replace_simple_dc(metadata_el, "publisher", metadata["publisher"])
    if metadata.get("publishedDate"):
        replace_simple_dc(metadata_el, "date", metadata["publishedDate"])
    if metadata.get("language"):
        replace_simple_dc(metadata_el, "language", metadata["language"])
    if metadata.get("authors"):
        replace_epub_authors(metadata_el, list(metadata["authors"]))
    if metadata.get("categories"):
        replace_epub_subjects(metadata_el, list(metadata["categories"]))

    if metadata.get("isbn13") or metadata.get("isbn10"):
        remove_epub_identifiers(metadata_el, {"isbn", "isbn10", "isbn13"})
        if metadata.get("isbn13"):
            append_identifier(metadata_el, metadata["isbn13"])
        elif metadata.get("isbn10"):
            append_identifier(metadata_el, metadata["isbn10"])

    if metadata.get("series"):
        add_series_metadata(metadata_el, root, metadata["series"])

    return etree.tostring(
        root,
        encoding="utf-8",
        xml_declaration=True,
        pretty_print=False,
    )


def write_epub_metadata(book_path: Path, metadata: dict) -> bool:
    opf_path = find_opf_path(book_path)
    with zipfile.ZipFile(book_path, "r") as archive:
        original_infos = archive.infolist()
        original_opf = archive.read(opf_path)
        updated_opf = update_epub_opf(original_opf, metadata)
        if updated_opf == original_opf:
            return False
        original_entries = {
            info.filename: archive.read(info.filename)
            for info in original_infos
        }

    with tempfile.NamedTemporaryFile(
        delete=False,
        dir=book_path.parent,
        prefix=".epubmeta-",
        suffix=".epub",
    ) as handle:
        temp_path = Path(handle.name)

    try:
        with zipfile.ZipFile(temp_path, "w") as new_archive:
            for info in original_infos:
                content = updated_opf if info.filename == opf_path else original_entries[info.filename]
                copy_info = ZipInfo(filename=info.filename, date_time=info.date_time)
                copy_info.compress_type = info.compress_type
                copy_info.comment = info.comment
                copy_info.extra = info.extra
                copy_info.create_system = info.create_system
                copy_info.flag_bits = info.flag_bits
                copy_info.internal_attr = info.internal_attr
                copy_info.external_attr = info.external_attr
                copy_info.volume = getattr(info, "volume", 0)
                if info.filename == "mimetype":
                    copy_info.compress_type = zipfile.ZIP_STORED
                new_archive.writestr(copy_info, content)
        os.replace(temp_path, book_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return True


def embed_into_book(
    book_path: Path,
    metadata: dict,
    write: bool,
) -> tuple[str, str | None]:
    suffix = book_path.suffix.lower()
    if suffix not in SUPPORTED_EXTS:
        return "skip", f"SKIP unsupported file type {book_path}"

    if not write:
        return "planned", None

    if suffix == ".pdf":
        changed = write_pdf_metadata(book_path, metadata)
    else:
        changed = write_epub_metadata(book_path, metadata)

    if changed:
        return "updated", f"UPDATED {book_path}"
    return "unchanged", f"UNCHANGED {book_path}"


def process_opf(
    opf_path: Path,
    allowed_exts: set[str],
    write: bool,
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

    if not metadata:
        stats.files_skipped += 1
        log(f"SKIP empty metadata {opf_path}")
        return

    book_files = [
        path for path in discover_book_files_for_opf(opf_path, allowed_exts)
        if path.suffix.lower() in SUPPORTED_EXTS
    ]
    if not book_files:
        stats.no_book_file += 1
        log(f"SKIP no supported book file {opf_path}")
        return

    seen_json_targets: set[Path] = set()
    for index, book_file in enumerate(book_files):
        if index > 0:
            log("")
        stats.book_files_found += 1
        stats.files_planned += 1
        try:
            current_metadata = read_current_embedded_metadata(book_file)
        except Exception as exc:  # noqa: BLE001
            current_metadata = {}
            log(f"WARNING read current metadata {book_file} :: {exc}")

        log(build_preview_message(book_file, current_metadata, metadata, write))
        log(compatibility_summary_line(book_file, metadata))
        json_path = metadata_json_path(book_file)
        json_is_duplicate = json_path in seen_json_targets
        cover_name = find_grimmory_cover_name(opf_path, book_file)
        cover_source_path = opf_path.parent / cover_name if cover_name else None
        cover_target_path_value = grimmory_target_cover_path(book_file)
        if not json_is_duplicate:
            log(build_json_preview_message(book_file, metadata, write, cover_target_path_value.name if cover_name else None))
        try:
            status, message = embed_into_book(
                book_file,
                copy.deepcopy(metadata),
                write=write,
            )
        except Exception as exc:  # noqa: BLE001
            stats.write_errors += 1
            log(f"ERROR write metadata {book_file} :: {exc}")
            continue

        if status == "updated":
            stats.files_updated += 1
        elif status == "unchanged":
            stats.files_unchanged += 1
        elif status == "skip":
            stats.files_skipped += 1
        if message:
            log(message)

        if cover_name and not json_is_duplicate:
            log(f"INFO cover found {cover_source_path} -> {cover_target_path_value}")
        if json_is_duplicate:
            log(f"SKIP duplicate JSON target {json_path}")
            continue
        seen_json_targets.add(json_path)
        stats.json_planned += 1
        payload = build_grimmory_sidecar_payload(
            copy.deepcopy(metadata),
            cover_target_path_value.name if cover_name else None,
        )
        if write:
            try:
                if cover_source_path is not None:
                    write_metadata_cover(cover_source_path, cover_target_path_value)
                write_metadata_json(json_path, payload)
            except Exception as exc:  # noqa: BLE001
                stats.write_errors += 1
                log(f"ERROR write JSON {json_path} :: {exc}")
                continue
            stats.json_created += 1
            log(f"JSON {json_path} -> written")
        else:
            log(f"JSON {json_path} -> planned")


def scan_opf_paths(
    opf_paths: list[Path],
    allowed_exts: set[str],
    write: bool,
    log: Callable[[str], None] = print,
    progress_cb: Callable[[int, int, Path, RunStats], None] | None = None,
) -> RunStats:
    stats = RunStats()
    if not opf_paths:
        log("SKIP no OPF files found")
        return stats

    total = len(opf_paths)
    for index, opf_path in enumerate(opf_paths, start=1):
        process_opf(
            opf_path,
            allowed_exts=allowed_exts,
            write=write,
            stats=stats,
            log=log,
        )
        if progress_cb is not None:
            progress_cb(index, total, opf_path, stats)
    return stats


def scan_library(
    root: Path,
    allowed_exts: set[str],
    write: bool,
    log: Callable[[str], None] = print,
) -> RunStats:
    return scan_opf_paths(
        iter_opf_files(root),
        allowed_exts=allowed_exts,
        write=write,
        log=log,
    )


def scan_libraries(
    roots: list[Path],
    allowed_exts: set[str],
    write: bool,
    log: Callable[[str], None] = print,
    progress_cb: Callable[[int, int, Path, RunStats], None] | None = None,
    folder_done_cb: Callable[[Path], None] | None = None,
) -> RunStats:
    stats = RunStats()
    grouped_opf_paths: list[tuple[Path, list[Path]]] = []
    total = 0
    for root in roots:
        opf_paths = sorted(iter_opf_files(root))
        grouped_opf_paths.append((root, opf_paths))
        total += len(opf_paths)

    if total == 0:
        log("SKIP no OPF files found")
        for root, _ in grouped_opf_paths:
            if folder_done_cb is not None:
                folder_done_cb(root)
        return stats

    current = 0
    for root, opf_paths in grouped_opf_paths:
        for opf_path in opf_paths:
            process_opf(
                opf_path,
                allowed_exts=allowed_exts,
                write=write,
                stats=stats,
                log=log,
            )
            current += 1
            if progress_cb is not None:
                progress_cb(current, total, opf_path, stats)
        if folder_done_cb is not None:
            folder_done_cb(root)
    return stats


def run_cli(args: argparse.Namespace) -> int:
    if args.inspect:
        inspect_path = Path(args.inspect).expanduser()
        valid, error_message = validate_book_path(inspect_path)
        if not valid:
            print(error_message)
            return 2
        print_compatibility_report(inspect_path)
        return 0

    root = Path(args.root).expanduser()
    valid, error_message = validate_root(root)
    if not valid:
        print(error_message)
        return 2

    allowed_exts = {
        ext for ext in normalize_allowed_exts(args.ext)
        if ext in SUPPORTED_EXTS
    }
    stats = scan_library(
        root=root,
        allowed_exts=allowed_exts,
        write=args.write,
    )
    print_summary(stats)
    return 0


def run_gui() -> int:
    try:
        import tkinter as tk
        from tkinter import messagebox, scrolledtext, ttk
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR GUI unavailable: {exc}")
        return 2

    window = tk.Tk()
    window.title(APP_WINDOW_TITLE)
    window.geometry("1320x860")
    window.minsize(1120, 760)

    paper = "#f3efe7"
    card = "#fffdfa"
    card_soft = "#f8f2e8"
    inset = "#f1e9dc"
    line_soft = "#e2d7c7"
    ink = "#1f2937"
    ink_muted = "#6b7280"
    shelf_blue = "#355c7d"
    shelf_blue_dark = "#27455f"
    binding_green = "#3f6f5a"
    binding_green_dark = "#305646"
    plum = "#79568b"
    brass = "#b7791f"
    rose = "#b24c58"
    sky = "#dde8f4"
    moss_soft = "#deebe3"
    rose_soft = "#f5e2e5"

    window.configure(bg=paper)
    style = ttk.Style(window)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure("App.TFrame", background=paper)
    style.configure("Header.TFrame", background=paper)
    style.configure("TButton", padding=(12, 10), borderwidth=0)
    style.map("TButton", background=[("active", inset), ("pressed", inset)])
    style.configure("Accent.TButton", padding=(14, 10), background=shelf_blue, foreground="white", borderwidth=0)
    style.map("Accent.TButton", background=[("active", shelf_blue_dark), ("pressed", shelf_blue_dark)])
    style.configure("Success.TButton", padding=(14, 10), background=binding_green, foreground="white", borderwidth=0)
    style.map("Success.TButton", background=[("active", binding_green_dark), ("pressed", binding_green_dark)])
    style.configure("Soft.TButton", padding=(12, 10), background=card_soft, foreground=ink, borderwidth=0)
    style.map("Soft.TButton", background=[("active", inset), ("pressed", inset)])
    style.configure("Remove.TButton", padding=(12, 10), background=rose_soft, foreground=rose, borderwidth=0)
    style.map("Remove.TButton", background=[("active", "#f2cdd2"), ("pressed", "#f2cdd2")])
    style.configure(
        "Archive.Horizontal.TProgressbar",
        troughcolor=inset,
        background=binding_green,
        lightcolor=binding_green,
        darkcolor=binding_green,
        bordercolor=inset,
        thickness=12,
    )
    style.configure(
        "Queue.Treeview",
        background=card,
        fieldbackground=card,
        foreground=ink,
        rowheight=36,
        bordercolor=line_soft,
        lightcolor=line_soft,
        darkcolor=line_soft,
        relief="flat",
        font=("Segoe UI", 10),
    )
    style.map("Queue.Treeview", background=[("selected", sky)], foreground=[("selected", ink)])
    style.configure(
        "Treeview.Heading",
        background=inset,
        foreground=ink_muted,
        relief="flat",
        borderwidth=0,
        font=("Segoe UI", 9, "bold"),
        padding=(10, 8),
    )

    state: dict[str, object] = {
        "is_running": False,
        "active_root": None,
        "last_mode": "DRY-RUN",
    }
    summary_mode_var = tk.StringVar(value="Dry Run")
    summary_output_var = tk.StringVar(value="EPUB + PDF + Grimmory JSON")
    summary_compat_var = tk.StringVar(value="KOReader / Grimmory / Calibre")
    summary_folders_var = tk.StringVar(value="0 folders")
    log_density_var = tk.StringVar(value="detailed")
    log_entries: list[str] = []
    summary_keys = {
        "OPF files found",
        "Book files found",
        "Files planned",
        "Files updated",
        "Files unchanged",
        "Files skipped",
        "Parse errors",
        "Write errors",
        "No matching book file",
        "JSON files planned",
        "JSON files created",
    }

    def outlined_frame(parent: tk.Widget, bg_color: str = card, border_color: str = line_soft) -> tk.Frame:
        return tk.Frame(
            parent,
            bg=bg_color,
            highlightbackground=border_color,
            highlightcolor=border_color,
            highlightthickness=1,
            bd=0,
        )

    def badge(parent: tk.Widget, text: str, bg_color: str, fg_color: str = "white") -> tk.Label:
        return tk.Label(
            parent,
            text=text,
            bg=bg_color,
            fg=fg_color,
            font=("Segoe UI", 9, "bold"),
            padx=12,
            pady=7,
            bd=0,
            relief="flat",
        )

    def nav_pill(parent: tk.Widget, text: str, active: bool = False) -> tk.Label:
        return tk.Label(
            parent,
            text=text,
            bg=ink if active else card,
            fg="white" if active else ink,
            font=("Segoe UI", 9, "bold" if active else "normal"),
            padx=14,
            pady=7,
            bd=0,
            relief="flat",
        )

    header = ttk.Frame(window, style="Header.TFrame")
    header.pack(fill="x", padx=24, pady=(20, 14))

    header_row = tk.Frame(header, bg=paper)
    header_row.pack(fill="x")
    header_row.columnconfigure(1, weight=1)

    mark = outlined_frame(header_row, bg_color=shelf_blue, border_color=shelf_blue)
    mark.grid(row=0, column=0, rowspan=3, sticky="nw", padx=(0, 16))
    tk.Label(
        mark,
        text="OPF",
        width=4,
        font=("Segoe UI", 12, "bold"),
        bg=shelf_blue,
        fg="white",
        padx=10,
        pady=12,
    ).pack()

    tk.Label(
        header_row,
        text="ARCHIVE WORKBENCH",
        font=("Segoe UI", 8, "bold"),
        bg=paper,
        fg=ink_muted,
        anchor="w",
    ).grid(row=0, column=1, sticky="w", pady=(2, 0))
    tk.Label(
        header_row,
        text=APP_NAME,
        font=("Segoe UI", 20, "bold"),
        bg=paper,
        fg=ink,
        anchor="w",
    ).grid(row=1, column=1, sticky="w")
    tk.Label(
        header_row,
        text="OPF to Embedded and JSON. Batch-embed EPUB/PDF metadata, generate Grimmory sidecars, and review compatibility in one run.",
        font=("Segoe UI", 10),
        bg=paper,
        fg=ink_muted,
        anchor="w",
    ).grid(row=2, column=1, sticky="w", pady=(4, 0))

    badges_frame = tk.Frame(header_row, bg=paper)
    badges_frame.grid(row=0, column=2, rowspan=3, sticky="ne")
    badge(badges_frame, "KOReader", shelf_blue).pack(side="left", padx=(0, 8))
    badge(badges_frame, "Grimmory", plum).pack(side="left", padx=(0, 8))
    badge(badges_frame, "Calibre", "#64748b").pack(side="left", padx=(0, 8))
    badge(badges_frame, "Batch Ready", binding_green).pack(side="left")

    topbar = tk.Frame(header, bg=paper)
    topbar.pack(fill="x", pady=(14, 0))
    topbar.columnconfigure(0, weight=1)

    nav_frame = tk.Frame(topbar, bg=paper)
    nav_frame.grid(row=0, column=0, sticky="w")
    nav_pill(nav_frame, "Queue", active=True).pack(side="left", padx=(0, 8))
    nav_pill(nav_frame, "Embed").pack(side="left", padx=(0, 8))
    nav_pill(nav_frame, "Log").pack(side="left")

    assist_badges = tk.Frame(topbar, bg=paper)
    assist_badges.grid(row=0, column=1, sticky="e")
    badge(assist_badges, "Dry Run First", brass).pack(side="left", padx=(0, 8))
    badge(assist_badges, "Folder Status Live", shelf_blue).pack(side="left")

    summary_strip = tk.Frame(header, bg=paper)
    summary_strip.pack(fill="x", pady=(14, 0))
    for column in range(4):
        summary_strip.columnconfigure(column, weight=1)

    def summary_card(parent: tk.Widget, value_var: tk.StringVar, label_text: str, rule_color: str) -> tk.Frame:
        shell = outlined_frame(parent, bg_color=card)
        inner = tk.Frame(shell, bg=card)
        inner.pack(fill="both", expand=True, padx=14, pady=12)
        tk.Label(inner, text=label_text, bg=card, fg=ink_muted, font=("Segoe UI", 8, "bold"), anchor="w").pack(fill="x")
        tk.Label(inner, textvariable=value_var, bg=card, fg=ink, font=("Segoe UI", 11, "bold"), anchor="w").pack(fill="x", pady=(4, 0))
        tk.Frame(shell, bg=rule_color, height=4).pack(fill="x", side="bottom")
        return shell

    summary_card(summary_strip, summary_folders_var, "Queue", shelf_blue).grid(row=0, column=0, sticky="ew", padx=(0, 10))
    summary_card(summary_strip, summary_mode_var, "Mode", ink).grid(row=0, column=1, sticky="ew", padx=(0, 10))
    summary_card(summary_strip, summary_output_var, "Outputs", plum).grid(row=0, column=2, sticky="ew", padx=(0, 10))
    summary_card(summary_strip, summary_compat_var, "Targets", binding_green).grid(row=0, column=3, sticky="ew")

    content = ttk.Frame(window, style="App.TFrame")
    content.pack(fill="both", expand=True, padx=24, pady=(0, 24))
    content.columnconfigure(0, weight=1)
    content.columnconfigure(1, weight=2, minsize=640)
    content.rowconfigure(0, weight=1)

    left = outlined_frame(content, bg_color=card)
    left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
    left.columnconfigure(0, weight=1)
    left.rowconfigure(3, weight=1)

    left_header = tk.Frame(left, bg=card)
    left_header.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
    left_header.columnconfigure(0, weight=1)
    tk.Label(left_header, text="Batch Queue", bg=card, fg=ink, font=("Segoe UI", 13, "bold"), anchor="w").grid(row=0, column=0, sticky="w")
    tk.Label(
        left_header,
        text="Select one or more folders, then watch each queue move from pending to done.",
        bg=card,
        fg=ink_muted,
        font=("Segoe UI", 9),
        anchor="w",
    ).grid(row=1, column=0, sticky="w", pady=(3, 0))
    badge(left_header, "Folder stages", shelf_blue).grid(row=0, column=1, rowspan=2, sticky="e")

    hint_shell = tk.Frame(left, bg=card)
    hint_shell.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 10))
    folder_hint = tk.Label(
        hint_shell,
        text="Add one or more folders. The picker supports multi-select folders in one step.",
        bg=card,
        fg=ink_muted,
        font=("Segoe UI", 9),
        wraplength=300,
        justify="left",
    )
    folder_hint.pack(fill="x", pady=(2, 4))

    preview_shell = tk.Frame(left, bg=card)
    preview_shell.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 10))
    preview_shell.columnconfigure(0, weight=1)
    tk.Label(preview_shell, text="Queue Preview", bg=card, fg=ink_muted, font=("Segoe UI", 8, "bold"), anchor="w").grid(row=0, column=0, sticky="w")
    folder_preview_frame = tk.Frame(preview_shell, bg=card)
    folder_preview_frame.grid(row=1, column=0, sticky="ew", pady=(6, 0))
    folder_preview_frame.columnconfigure(0, weight=1)

    folder_frame = outlined_frame(left, bg_color=card)
    folder_frame.grid(row=3, column=0, sticky="nsew", padx=16, pady=(0, 10))
    folder_frame.rowconfigure(0, weight=1)
    folder_frame.columnconfigure(0, weight=1)

    folder_item_ids: dict[str, str] = {}
    folder_stage_map: dict[str, str] = {}
    folder_item_seq = 0

    folder_list = ttk.Treeview(
        folder_frame,
        columns=("stage", "path"),
        displaycolumns=("stage",),
        show="tree headings",
        selectmode="extended",
        style="Queue.Treeview",
    )
    folder_list.grid(row=0, column=0, sticky="nsew")
    folder_list.heading("#0", text="Folder")
    folder_list.heading("stage", text="Stage")
    folder_list.column("#0", width=290, minwidth=220, stretch=True, anchor="w")
    folder_list.column("stage", width=96, minwidth=92, stretch=False, anchor="center")
    folder_list.column("path", width=0, stretch=False)
    folder_list.tag_configure("pending", foreground=ink)
    folder_list.tag_configure("running", foreground=shelf_blue_dark, font=("Segoe UI", 10, "bold"))
    folder_list.tag_configure("done", foreground=binding_green)
    folder_list.tag_configure("error", foreground=rose)

    folder_scroll = ttk.Scrollbar(folder_frame, orient="vertical", command=folder_list.yview)
    folder_scroll.grid(row=0, column=1, sticky="ns")
    folder_list.configure(yscrollcommand=folder_scroll.set)

    folder_footer = tk.Frame(left, bg=card)
    folder_footer.grid(row=4, column=0, sticky="ew", padx=16, pady=(6, 4))
    folder_footer.columnconfigure(0, weight=1)
    folder_count_var = tk.StringVar(value="0 folders selected")
    tk.Label(folder_footer, textvariable=folder_count_var, bg=card, fg=ink_muted, font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w")
    tk.Label(folder_footer, text="Status updates appear directly in the queue.", bg=card, fg=ink_muted, font=("Segoe UI", 9)).grid(row=0, column=1, sticky="e")

    button_row = tk.Frame(left, bg=card)
    button_row.grid(row=5, column=0, sticky="ew", padx=16, pady=(10, 16))
    button_row.columnconfigure(0, weight=1)
    button_row.columnconfigure(1, weight=1)

    def selected_roots() -> list[Path]:
        roots: list[Path] = []
        for item_id in folder_list.get_children():
            item_path = folder_list.set(item_id, "path") or folder_list.item(item_id, "text")
            if item_path:
                roots.append(Path(item_path))
        return roots

    def stage_palette(stage: str) -> tuple[str, str]:
        return {
            "Pending": (inset, ink_muted),
            "Scanning": (sky, shelf_blue_dark),
            "Done": (moss_soft, binding_green),
            "Error": (rose_soft, rose),
        }.get(stage, (inset, ink_muted))

    def refresh_folder_count() -> None:
        count = len(folder_list.get_children())
        folder_count_var.set(f"{count} folder{'s' if count != 1 else ''} selected")
        folders_metric_var.set(str(count))
        summary_folders_var.set(f"{count} folder{'s' if count != 1 else ''}")
        if count == 0:
            folder_hint.configure(text="Add one or more folders. The picker supports multi-select folders in one step.")
        else:
            folder_hint.configure(text="Selected folders will be scanned in one batch. Each folder updates from Pending to Scanning to Done.")
        for child in folder_preview_frame.winfo_children():
            child.destroy()
        if count == 0:
            tk.Label(
                folder_preview_frame,
                text="No folders selected yet",
                bg=card,
                fg=ink_muted,
                font=("Segoe UI", 10, "italic"),
                anchor="w",
                justify="left",
            ).pack(fill="x")
            return

        preview_items: list[tuple[str, str]] = []
        for item_id in list(folder_list.get_children())[:4]:
            path_text = folder_list.set(item_id, "path") or folder_list.item(item_id, "text")
            display_name = folder_list.item(item_id, "text") or Path(path_text).name or path_text
            preview_items.append((display_name, folder_stage_map.get(path_text, "Pending")))
        if count > 4:
            preview_items.append((f"+{count - 4} more", "Pending"))
        for display_name, stage in preview_items:
            chip_bg, chip_fg = stage_palette(stage)
            chip_text = display_name if display_name.startswith("+") else f"{stage}  {display_name}"
            tk.Label(
                folder_preview_frame,
                text=chip_text,
                bg=chip_bg,
                fg=chip_fg,
                font=("Segoe UI", 9),
                padx=10,
                pady=5,
                bd=0,
                relief="flat",
            ).pack(side="left", padx=(0, 8))

    def set_folder_status(root: Path, stage: str) -> None:
        normalized = str(root.expanduser())
        if folder_stage_map.get(normalized) == stage:
            return
        folder_stage_map[normalized] = stage
        item_id = folder_item_ids.get(normalized)
        if item_id is None:
            return
        tag_name = {
            "Pending": "pending",
            "Scanning": "running",
            "Done": "done",
            "Error": "error",
        }.get(stage, "pending")
        folder_list.item(
            item_id,
            values=(stage, normalized),
            tags=(tag_name,),
        )
        refresh_folder_count()

    def add_folder_paths(paths: list[Path]) -> None:
        nonlocal folder_item_seq
        if not paths:
            return
        existing = {folder_list.set(item_id, "path") or folder_list.item(item_id, "text") for item_id in folder_list.get_children()}
        added_item_ids: list[str] = []
        for path in paths:
            normalized = str(path.expanduser())
            if normalized in existing:
                continue
            item_id = f"folder_{folder_item_seq}"
            folder_item_seq += 1
            folder_item_ids[normalized] = item_id
            folder_stage_map[normalized] = "Pending"
            folder_list.insert(
                "",
                "end",
                iid=item_id,
                text=path.name or normalized,
                values=("Pending", normalized),
                tags=("pending",),
            )
            existing.add(normalized)
            added_item_ids.append(item_id)
        if added_item_ids:
            folder_list.selection_set(added_item_ids)
            folder_list.focus(added_item_ids[-1])
            folder_list.see(added_item_ids[-1])
            refresh_folder_count()

    def add_folder() -> None:
        try:
            selected_paths = pick_folders_with_native_dialog(window.winfo_id(), "Select one or more folders")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(
                APP_NAME,
                f"Could not open the folder picker:\n{exc}",
                parent=window,
            )
            return
        if selected_paths:
            add_folder_paths(selected_paths)

    def remove_selected_folders() -> None:
        selected = list(folder_list.selection())
        for item_id in selected:
            item_path = folder_list.set(item_id, "path") or folder_list.item(item_id, "text")
            folder_item_ids.pop(item_path, None)
            folder_stage_map.pop(item_path, None)
            folder_list.delete(item_id)
        refresh_folder_count()

    def clear_folders() -> None:
        nonlocal folder_item_seq
        for item_id in list(folder_list.get_children()):
            folder_list.delete(item_id)
        folder_item_ids.clear()
        folder_stage_map.clear()
        folder_item_seq = 0
        refresh_folder_count()

    def reset_folder_statuses() -> None:
        state["active_root"] = None
        for normalized in list(folder_stage_map):
            set_folder_status(Path(normalized), "Pending")

    add_button = ttk.Button(button_row, text="Add Folder(s)", command=add_folder, style="Accent.TButton")
    add_button.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
    remove_button = ttk.Button(button_row, text="Remove Selected", command=remove_selected_folders, style="Remove.TButton")
    remove_button.grid(row=1, column=0, sticky="ew", padx=(0, 8))
    clear_button = ttk.Button(button_row, text="Clear All", command=clear_folders)
    clear_button.grid(row=1, column=1, sticky="ew", padx=(8, 0))

    right = outlined_frame(content, bg_color=card)
    right.grid(row=0, column=1, sticky="nsew")
    right.columnconfigure(0, weight=1)
    right.rowconfigure(6, weight=1)

    right_header = tk.Frame(right, bg=card)
    right_header.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
    right_header.columnconfigure(0, weight=1)
    tk.Label(right_header, text="Run Console", bg=card, fg=ink, font=("Segoe UI", 13, "bold"), anchor="w").grid(row=0, column=0, sticky="w")
    tk.Label(
        right_header,
        text="Watch progress, inspect compatibility output, and switch between detailed and compact log views.",
        bg=card,
        fg=ink_muted,
        font=("Segoe UI", 9),
        anchor="w",
    ).grid(row=1, column=0, sticky="w", pady=(3, 0))
    badge(right_header, "Archivist view", plum).grid(row=0, column=1, rowspan=2, sticky="e")

    status_var = tk.StringVar(value="Ready to scan")
    percent_var = tk.StringVar(value="0%")
    detail_var = tk.StringVar(value="Add folders, then choose Dry Run or Write Changes.")
    folders_metric_var = tk.StringVar(value="0")
    opf_metric_var = tk.StringVar(value="0")
    changed_metric_var = tk.StringVar(value="0 / 0")
    error_metric_var = tk.StringVar(value="0")

    status_panel = outlined_frame(right, bg_color=card_soft)
    status_panel.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 12))
    status_panel.columnconfigure(0, weight=1)
    status_row = tk.Frame(status_panel, bg=card_soft)
    status_row.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 10))
    status_row.columnconfigure(1, weight=1)

    status_chip_wrap = tk.Frame(status_row, bg=card_soft)
    status_chip_wrap.grid(row=0, column=0, sticky="w")
    status_dot = tk.Label(status_chip_wrap, text="", bg=shelf_blue, fg=shelf_blue, width=1, padx=6, pady=6, bd=0, relief="flat")
    status_dot.pack(side="left", padx=(0, 8))
    status_chip = tk.Label(
        status_chip_wrap,
        textvariable=status_var,
        bg=ink,
        fg="white",
        font=("Segoe UI", 10, "bold"),
        padx=12,
        pady=8,
        bd=0,
        relief="flat",
        anchor="w",
    )
    status_chip.pack(side="left")
    mode_chip = tk.Label(
        status_row,
        textvariable=summary_mode_var,
        bg=card,
        fg=ink,
        font=("Segoe UI", 9, "bold"),
        padx=12,
        pady=8,
        bd=0,
        relief="flat",
    )
    mode_chip.grid(row=0, column=1, sticky="w", padx=(12, 0))
    tk.Label(status_row, textvariable=percent_var, bg=card_soft, fg=ink_muted, font=("Segoe UI", 11, "bold")).grid(row=0, column=2, sticky="e")

    progress = ttk.Progressbar(status_panel, maximum=100, value=0, style="Archive.Horizontal.TProgressbar")
    progress.grid(row=1, column=0, sticky="ew", padx=14)
    tk.Label(
        status_panel,
        textvariable=detail_var,
        bg=card_soft,
        fg=ink_muted,
        font=("Segoe UI", 9),
        wraplength=620,
        justify="left",
        anchor="w",
    ).grid(row=2, column=0, sticky="ew", padx=14, pady=(10, 14))

    metrics_row = tk.Frame(right, bg=card)
    metrics_row.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 12))
    for column in range(4):
        metrics_row.columnconfigure(column, weight=1, uniform="metric")

    def make_metric_card(parent: tk.Widget, column: int, caption: str, value_var: tk.StringVar, color: str, badge_text: str) -> None:
        shell = outlined_frame(parent, bg_color=card)
        shell.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 8, 0))
        top_row = tk.Frame(shell, bg=card)
        top_row.pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(top_row, text=caption, bg=card, fg=ink, font=("Segoe UI", 9, "bold"), anchor="w").pack(side="left", fill="x", expand=True)
        tk.Label(
            top_row,
            text=badge_text,
            bg=color,
            fg="white",
            font=("Segoe UI", 8, "bold"),
            padx=7,
            pady=2,
            bd=0,
            relief="flat",
        ).pack(side="right")
        tk.Label(shell, textvariable=value_var, bg=card, fg=ink, font=("Segoe UI", 18, "bold"), anchor="w").pack(fill="x", padx=12, pady=(6, 0))
        tk.Frame(shell, bg=color, height=4).pack(fill="x", side="bottom", pady=(2, 0))

    make_metric_card(metrics_row, 0, "Folders selected", folders_metric_var, shelf_blue, "Q")
    make_metric_card(metrics_row, 1, "OPF files scanned", opf_metric_var, binding_green, "O")
    make_metric_card(metrics_row, 2, "Updated / planned", changed_metric_var, plum, "U")
    make_metric_card(metrics_row, 3, "Errors", error_metric_var, rose, "!")

    action_row = tk.Frame(right, bg=card)
    action_row.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 12))

    log_sep = tk.Frame(right, bg=line_soft, height=1)
    log_sep.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 0))

    log_header = tk.Frame(right, bg=card)
    log_header.grid(row=5, column=0, sticky="ew", padx=16, pady=(10, 8))
    log_header.columnconfigure(0, weight=1)
    tk.Label(log_header, text="Execution Log", bg=card, fg=ink, font=("Segoe UI", 12, "bold"), anchor="w").grid(row=0, column=0, sticky="w")
    tk.Label(
        log_header,
        text="Switch density when you want a quick summary or the full metadata trace.",
        bg=card,
        fg=ink_muted,
        font=("Segoe UI", 9),
        anchor="w",
    ).grid(row=1, column=0, sticky="w", pady=(2, 0))

    density_toggle = tk.Frame(log_header, bg=card)
    density_toggle.grid(row=0, column=1, rowspan=2, sticky="e")
    density_buttons: dict[str, tk.Label] = {}

    log_shell = outlined_frame(right, bg_color=inset)
    log_shell.grid(row=6, column=0, sticky="nsew", padx=16, pady=(0, 16))
    log_shell.rowconfigure(0, weight=1)
    log_shell.columnconfigure(0, weight=1)

    log_view = scrolledtext.ScrolledText(
        log_shell,
        wrap="word",
        height=24,
        state="disabled",
        bg=card,
        fg=ink,
        insertbackground=ink,
        relief="flat",
        padx=14,
        pady=14,
        font=("Consolas", 10),
        spacing1=3,
        spacing2=1,
        spacing3=8,
    )
    log_view.grid(row=0, column=0, sticky="nsew")
    log_view.tag_configure("section", foreground=shelf_blue_dark, font=("Consolas", 10, "bold"))
    log_view.tag_configure("start", foreground=binding_green, font=("Consolas", 10, "bold"))
    log_view.tag_configure("compat", foreground=binding_green, font=("Consolas", 10, "bold"))
    log_view.tag_configure("success", foreground=binding_green)
    log_view.tag_configure("warning", foreground=brass)
    log_view.tag_configure("error", foreground=rose, font=("Consolas", 10, "bold"))
    log_view.tag_configure("muted", foreground=ink_muted)
    log_view.tag_configure("path", foreground=shelf_blue_dark)
    log_view.tag_configure("json", foreground=plum, font=("Consolas", 10, "bold"))
    log_view.tag_configure("summary", foreground=ink, font=("Consolas", 10, "bold"))
    log_view.tag_configure("done", foreground=binding_green, font=("Consolas", 10, "bold"))
    log_view.tag_configure("change", foreground=ink, font=("Consolas", 10, "bold"))

    def repaint_density_toggle() -> None:
        for mode_name, button in density_buttons.items():
            active = log_density_var.get() == mode_name
            button.configure(bg=ink if active else card_soft, fg="white" if active else ink_muted)

    def line_is_compact_worthy(line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        if line in {"SUMMARY", "FILE", "COMPATIBILITY", "JSON"}:
            return True
        if line.startswith(("START ", "DONE ", "UPDATED ", "JSON ", "UNCHANGED ", "SKIP ", "WARNING ", "ERROR ", "FILE ", "COMPATIBILITY ")):
            return True
        if line.startswith("  - "):
            return True
        if "->" in line:
            return True
        return any(stripped.startswith(summary_key) for summary_key in summary_keys)

    def insert_log_line(line: str) -> None:
        insert_index = log_view.index("end-1c")
        log_view.insert("end", line + "\n")
        tag_name = None
        stripped = line.strip()
        if line == "SUMMARY":
            tag_name = "section"
        elif line in {"FILE", "COMPATIBILITY", "JSON"}:
            tag_name = "section"
        elif line.startswith("START "):
            tag_name = "start"
        elif line.startswith("COMPATIBILITY "):
            tag_name = "compat"
        elif line.startswith("FILE "):
            tag_name = "path"
        elif line.startswith("UPDATED "):
            tag_name = "success"
        elif line.startswith("JSON "):
            tag_name = "json"
        elif line.startswith("UNCHANGED "):
            tag_name = "muted"
        elif line.startswith("SKIP ") or line.startswith("WARNING "):
            tag_name = "warning"
        elif line.startswith("ERROR "):
            tag_name = "error"
        elif line.startswith("INFO "):
            tag_name = "muted"
        elif line.startswith("DONE "):
            tag_name = "done"
        elif "->" in line:
            tag_name = "change"
        elif stripped.endswith(":"):
            tag_name = "section"
        elif stripped.startswith("path:") or stripped.startswith("target:"):
            tag_name = "path"
        elif stripped.startswith("mode:") or stripped.startswith("metadata:") or stripped.startswith("note:") or stripped.startswith("status:") or stripped.startswith("cover:"):
            tag_name = "muted"
        elif stripped.startswith("KOReader") or stripped.startswith("Grimmory") or stripped.startswith("Calibre"):
            tag_name = "warning" if "PARTIAL" in stripped else "compat"
        elif stripped.startswith("series source:"):
            tag_name = "muted"
        elif stripped.startswith("OPF files found") or stripped.startswith("Book files found") or stripped.startswith("Files "):
            tag_name = "summary"
        elif line.startswith("  - "):
            tag_name = "path"
        elif line.startswith("  "):
            tag_name = "muted"
        if tag_name:
            log_view.tag_add(tag_name, f"{insert_index} linestart", f"{insert_index} lineend")

    def render_log() -> None:
        log_view.configure(state="normal")
        log_view.delete("1.0", "end")
        for line in log_entries:
            if log_density_var.get() == "detailed" or line_is_compact_worthy(line):
                insert_log_line(line)
        log_view.see("end")
        log_view.configure(state="disabled")
        window.update_idletasks()

    def set_log_density(mode_name: str) -> None:
        log_density_var.set(mode_name)
        repaint_density_toggle()
        render_log()

    for mode_name, label_text in [("compact", "Compact"), ("detailed", "Detailed")]:
        button = tk.Label(
            density_toggle,
            text=label_text,
            bg=card_soft,
            fg=ink_muted,
            font=("Segoe UI", 9, "bold"),
            padx=12,
            pady=7,
            cursor="hand2",
            bd=0,
            relief="flat",
        )
        button.pack(side="left", padx=(0, 8 if mode_name == "compact" else 0))
        button.bind("<Button-1>", lambda _event, mode_name=mode_name: set_log_density(mode_name))
        density_buttons[mode_name] = button
    repaint_density_toggle()

    def append_log(line: str) -> None:
        log_entries.append(line)
        if log_density_var.get() == "detailed" or line_is_compact_worthy(line):
            log_view.configure(state="normal")
            insert_log_line(line)
            log_view.see("end")
            log_view.configure(state="disabled")
        window.update_idletasks()

    def set_run_status(label: str, dot_color: str, chip_color: str) -> None:
        status_var.set(label)
        status_dot.configure(bg=dot_color, fg=dot_color)
        status_chip.configure(bg=chip_color)

    def set_progress(current: int, total: int, book_path: Path, stats: RunStats) -> None:
        if total <= 0:
            progress["value"] = 0
            percent_var.set("0%")
            set_run_status("No files found", brass, brass)
            opf_metric_var.set("0")
            changed_metric_var.set("0 / 0")
            error_metric_var.set("0")
            return
        percent = int(round((current / total) * 100))
        progress["value"] = percent
        percent_var.set(f"{percent}%")
        set_run_status(f"Processing {current}/{total} OPF files", brass, brass)
        opf_metric_var.set(str(stats.opf_files_found))
        changed_metric_var.set(f"{stats.files_updated} / {stats.files_planned}")
        error_metric_var.set(str(stats.parse_errors + stats.write_errors))
        detail_var.set(f"Current: {book_path.parent}")
        window.update_idletasks()

    def set_running(is_running: bool) -> None:
        state["is_running"] = is_running
        for widget in (add_button, remove_button, clear_button, dry_run_button, write_button):
            widget.configure(state="disabled" if is_running else "normal")
        if is_running:
            set_run_status("Running...", brass, brass)
        elif status_var.get() != "Error":
            set_run_status("Finished", binding_green, binding_green)

    def refresh_metrics(stats: RunStats | None = None) -> None:
        folders_metric_var.set(str(len(folder_list.get_children())))
        summary_output_var.set("EPUB + PDF + Grimmory JSON")
        summary_compat_var.set("KOReader / Grimmory / Calibre")
        if stats is None:
            opf_metric_var.set("0")
            changed_metric_var.set("0 / 0")
            error_metric_var.set("0")
            return
        opf_metric_var.set(str(stats.opf_files_found))
        changed_metric_var.set(f"{stats.files_updated} / {stats.files_planned}")
        error_metric_var.set(str(stats.parse_errors + stats.write_errors))

    def collect_valid_roots() -> list[Path]:
        roots = selected_roots()
        if not roots:
            messagebox.showinfo(
                APP_NAME,
                "Please add at least one folder before running.",
                parent=window,
            )
            return []
        valid_roots: list[Path] = []
        invalid: list[str] = []
        for root in roots:
            valid, error_message = validate_root(root)
            if valid:
                valid_roots.append(root)
            else:
                invalid.append(error_message or str(root))
        if invalid:
            messagebox.showerror(
                APP_NAME,
                "Some folders are invalid:\n\n" + "\n".join(invalid),
                parent=window,
            )
            return []
        return valid_roots

    def run_selected(write: bool) -> None:
        if bool(state["is_running"]):
            return

        roots = collect_valid_roots()
        if not roots:
            return

        mode_name = "WRITE" if write else "DRY-RUN"
        state["last_mode"] = mode_name
        summary_mode_var.set("Write Changes" if write else "Dry Run")
        progress["value"] = 0
        percent_var.set("0%")
        set_run_status("Preparing...", shelf_blue, ink)
        detail_var.set(f"Scanning {len(roots)} folder{'s' if len(roots) != 1 else ''}.")
        refresh_metrics()
        reset_folder_statuses()
        set_running(True)

        if log_entries:
            append_log("")
            append_log("=" * 90)
            append_log("")

        append_log(f"START mode={mode_name} | folders={len(roots)}")
        append_log("Folders:")
        for root in roots:
            append_log(f"  - {root}")

        allowed_exts = {ext for ext in normalize_allowed_exts("pdf,epub") if ext in SUPPORTED_EXTS}

        def mark_root_scanning(opf_path: Path) -> None:
            for root in roots:
                try:
                    opf_path.relative_to(root)
                except ValueError:
                    continue
                if folder_stage_map.get(str(root.expanduser())) != "Done":
                    set_folder_status(root, "Scanning")
                    state["active_root"] = root
                break

        def progress_cb(current: int, total: int, opf_path: Path, stats: RunStats) -> None:
            mark_root_scanning(opf_path)
            set_progress(current, total, opf_path, stats)
            detail_var.set(f"Current OPF: {opf_path}")

        def folder_done_cb(root: Path) -> None:
            set_folder_status(root, "Done")
            state["active_root"] = None

        try:
            stats = scan_libraries(
                roots=roots,
                allowed_exts=allowed_exts,
                write=write,
                log=append_log,
                progress_cb=progress_cb,
                folder_done_cb=folder_done_cb,
            )
        except Exception as exc:  # noqa: BLE001
            append_log(f"ERROR unexpected failure :: {exc}")
            set_running(False)
            set_run_status("Error", rose, rose)
            active_root = state.get("active_root")
            if isinstance(active_root, Path):
                set_folder_status(active_root, "Error")
            detail_var.set(str(exc))
            messagebox.showerror(
                APP_NAME,
                f"Unexpected error:\n{exc}",
                parent=window,
            )
            return

        progress["value"] = 100
        percent_var.set("100%")
        append_log("")
        print_summary(stats, append_log)
        append_log("")
        append_log("DONE review the log above.")
        detail_var.set(
            f"Updated={stats.files_updated} | Unchanged={stats.files_unchanged} | "
            f"Errors={stats.write_errors + stats.parse_errors}"
        )
        refresh_metrics(stats)
        set_running(False)

    def clear_log() -> None:
        log_entries.clear()
        render_log()
        set_run_status("Log cleared", shelf_blue, ink)
        detail_var.set("Log cleared")
        progress["value"] = 0
        percent_var.set("0%")
        refresh_metrics()

    dry_run_button = ttk.Button(action_row, text="Dry Run", command=lambda: run_selected(False), style="Accent.TButton")
    dry_run_button.pack(side="left", padx=(0, 8))
    write_button = ttk.Button(action_row, text="Write Changes", command=lambda: run_selected(True), style="Success.TButton")
    write_button.pack(side="left", padx=(0, 8))
    clear_log_button = ttk.Button(action_row, text="Clear Log", command=clear_log, style="Soft.TButton")
    clear_log_button.pack(side="left", padx=(0, 8))
    close_button = ttk.Button(action_row, text="Close", command=window.destroy)
    close_button.pack(side="right")

    refresh_folder_count()
    refresh_metrics()
    window.mainloop()
    return 0


def main() -> int:
    configure_console_output()
    argv = sys.argv[1:]
    if not argv:
        return run_gui()

    args = parse_args(argv)
    if args.gui:
        return run_gui()
    return run_cli(args)


if __name__ == "__main__":
    raise SystemExit(main())
