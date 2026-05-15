from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Any
from xml.etree import ElementTree as ET


ISBN10_RE = re.compile(r"(?i)\b(?:ISBN(?:-1[03])?:?\s*)?([0-9][0-9\- ]{8,}[0-9Xx])\b")
ISBN13_RE = re.compile(r"(?i)\b(?:ISBN(?:-1[03])?:?\s*)?(97[89][0-9\- ]{9,}[0-9])\b")


OpfData = dict[str, Any]


def local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def first_text(elements: list[ET.Element]) -> str | None:
    for element in elements:
        text = clean_text("".join(element.itertext()))
        if text:
            return text
    return None


def all_text(elements: list[ET.Element]) -> list[str]:
    out: list[str] = []
    for element in elements:
        text = clean_text("".join(element.itertext()))
        if text:
            out.append(text)
    return out


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
            return parsed.date().isoformat()
        except ValueError:
            continue
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date().isoformat()
    except ValueError:
        return text


def _isbn13_check_digit(first_12: str) -> str:
    total = 0
    for index, char in enumerate(first_12):
        digit = int(char)
        total += digit if index % 2 == 0 else digit * 3
    return str((10 - (total % 10)) % 10)


def is_valid_isbn13(value: str) -> bool:
    if len(value) != 13 or not value.isdigit():
        return False
    return _isbn13_check_digit(value[:12]) == value[12]


def is_valid_isbn10(value: str) -> bool:
    if len(value) != 10:
        return False
    total = 0
    for index, char in enumerate(value[:9]):
        if not char.isdigit():
            return False
        total += (10 - index) * int(char)
    check_char = value[9]
    check = 10 if check_char == "X" else int(check_char) if check_char.isdigit() else -1
    if check < 0:
        return False
    total += check
    return total % 11 == 0


def isbn10_to_isbn13(value: str) -> str | None:
    if not is_valid_isbn10(value):
        return None
    core = "978" + value[:9]
    return core + _isbn13_check_digit(core)


def isbn13_to_isbn10(value: str) -> str | None:
    if not is_valid_isbn13(value) or not value.startswith("978"):
        return None
    core = value[3:12]
    total = 0
    for index, char in enumerate(core):
        total += (10 - index) * int(char)
    remainder = total % 11
    check_value = (11 - remainder) % 11
    check = "X" if check_value == 10 else str(check_value)
    return core + check


def normalize_isbn(raw: str | None) -> tuple[str | None, str | None, str | None]:
    if not raw:
        return (None, None, None)
    candidate = raw.strip()
    if not candidate:
        return (None, None, None)

    match13 = ISBN13_RE.search(candidate)
    if match13:
        digits = re.sub(r"[^0-9]", "", match13.group(1))
        if len(digits) == 13 and is_valid_isbn13(digits):
            return digits, isbn13_to_isbn10(digits), digits

    match10 = ISBN10_RE.search(candidate)
    if match10:
        digits = re.sub(r"[^0-9Xx]", "", match10.group(1)).upper()
        if len(digits) == 10 and is_valid_isbn10(digits):
            return isbn10_to_isbn13(digits) or digits, digits, isbn10_to_isbn13(digits)

    return (None, None, None)


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
        isbn = normalize_isbn(text)
        if isbn[0] or isbn[1] or isbn[2]:
            return isbn
    return None


def parse_numeric(value: str) -> int | float | None:
    text = value.strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        try:
            return float(text)
        except ValueError:
            return None


def parse_opf(path: str | Path) -> OpfData:
    tree = ET.parse(Path(path))
    root = tree.getroot()
    metadata = None
    for child in root.iter():
        if local_name(child.tag) == "metadata":
            metadata = child
            break
    if metadata is None:
        raise ValueError("Missing metadata element")

    def metadata_elements(name: str) -> list[ET.Element]:
        return [element for element in metadata if local_name(element.tag) == name]

    fields: OpfData = {}
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
        series_data: dict[str, Any] = {}
        if series_name:
            series_data["name"] = series_name
        if series_number_raw:
            number = parse_numeric(series_number_raw)
            if number is not None:
                series_data["number"] = number
        if series_data:
            fields["series"] = series_data

    rating_raw = extract_meta_value(metadata, "calibre:rating")
    if rating_raw:
        rating = parse_numeric(rating_raw)
        if rating is not None:
            fields["rating"] = rating

    return fields
