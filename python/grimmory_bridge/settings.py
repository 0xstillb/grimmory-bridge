from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from threading import Lock
from typing import Any


_DB_LOCK = Lock()
_DEFAULT_DB_PATH = Path.cwd() / "runs" / "settings.db"
_SCHEMA_VERSION = 1
_TARGETS = ("calibre", "grimmory", "koreader")
_KINDS = ("epub", "pdf", "cbz", "azw3", "mobi", "other")
_THEMES = ("light", "dark")
_DENSITIES = ("compact", "regular", "comfy")
_ACCENTS = ("indigo", "violet", "teal", "amber", "ink")

DEFAULT_SETTINGS: dict[str, Any] = {
    "always_dry_run_first": True,
    "confirm_before_write": True,
    "auto_refresh_grimmory": True,
    "source_priority": ["calibre", "grimmory", "koreader"],
    "enabled_kinds": ["epub", "pdf"],
    "backup_before_write": True,
    "backup_extension": ".bak",
    "sidecar_metadata_name": ".metadata.json",
    "sidecar_cover_name": ".cover.jpg",
    "overwrite_sidecars": True,
    "prefer_embedded_over_sidecar": False,
    "pdf_password": "",
    "pdf_user_password": "",
    "pdf_owner_password": "",
    "pdf_reencrypt": True,
    "pdf_encrypt_algorithm": "",
    "theme": "dark",
    "density": "comfy",
    "accent": "indigo",
}


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path if db_path is not None else _DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
          id INTEGER PRIMARY KEY CHECK (id = 1),
          schema_version INTEGER NOT NULL,
          payload_json TEXT NOT NULL
        )
        """
    )
    connection.commit()


def _normalize_priority(value: Any) -> list[str]:
    if not isinstance(value, list):
        return list(DEFAULT_SETTINGS["source_priority"])
    out: list[str] = []
    for item in value:
        text = str(item).lower().strip()
        if text in _TARGETS and text not in out:
            out.append(text)
    for target in _TARGETS:
        if target not in out:
            out.append(target)
    return out


def _normalize_kinds(value: Any) -> list[str]:
    if not isinstance(value, list):
        return list(DEFAULT_SETTINGS["enabled_kinds"])
    out: list[str] = []
    for item in value:
        text = str(item).lower().strip()
        if text in _KINDS and text not in out:
            out.append(text)
    return out if out else list(DEFAULT_SETTINGS["enabled_kinds"])


def _normalize_settings(raw: dict[str, Any]) -> dict[str, Any]:
    out = dict(DEFAULT_SETTINGS)
    out["always_dry_run_first"] = bool(raw.get("always_dry_run_first", out["always_dry_run_first"]))
    out["confirm_before_write"] = bool(raw.get("confirm_before_write", out["confirm_before_write"]))
    out["auto_refresh_grimmory"] = bool(raw.get("auto_refresh_grimmory", out["auto_refresh_grimmory"]))
    out["source_priority"] = _normalize_priority(raw.get("source_priority"))
    out["enabled_kinds"] = _normalize_kinds(raw.get("enabled_kinds"))
    out["backup_before_write"] = bool(raw.get("backup_before_write", out["backup_before_write"]))
    out["backup_extension"] = str(raw.get("backup_extension", out["backup_extension"])) or ".bak"
    out["sidecar_metadata_name"] = str(raw.get("sidecar_metadata_name", out["sidecar_metadata_name"])) or ".metadata.json"
    out["sidecar_cover_name"] = str(raw.get("sidecar_cover_name", out["sidecar_cover_name"])) or ".cover.jpg"
    out["overwrite_sidecars"] = bool(raw.get("overwrite_sidecars", out["overwrite_sidecars"]))
    out["prefer_embedded_over_sidecar"] = bool(raw.get("prefer_embedded_over_sidecar", out["prefer_embedded_over_sidecar"]))
    out["pdf_password"] = str(raw.get("pdf_password", out["pdf_password"]))
    out["pdf_user_password"] = str(raw.get("pdf_user_password", out["pdf_user_password"]))
    out["pdf_owner_password"] = str(raw.get("pdf_owner_password", out["pdf_owner_password"]))
    out["pdf_reencrypt"] = bool(raw.get("pdf_reencrypt", out["pdf_reencrypt"]))
    out["pdf_encrypt_algorithm"] = str(raw.get("pdf_encrypt_algorithm", out["pdf_encrypt_algorithm"])).strip()

    theme = str(raw.get("theme", out["theme"])).lower().strip()
    density = str(raw.get("density", out["density"])).lower().strip()
    accent = str(raw.get("accent", out["accent"])).lower().strip()
    out["theme"] = theme if theme in _THEMES else out["theme"]
    out["density"] = density if density in _DENSITIES else out["density"]
    out["accent"] = accent if accent in _ACCENTS else out["accent"]
    return out


def get_settings(db_path: Path | None = None) -> dict[str, Any]:
    with _DB_LOCK:
        connection = _connect(db_path)
        try:
            _ensure_schema(connection)
            row = connection.execute("SELECT schema_version, payload_json FROM settings WHERE id = 1").fetchone()
            if row is None:
                payload = dict(DEFAULT_SETTINGS)
                connection.execute(
                    "INSERT INTO settings (id, schema_version, payload_json) VALUES (1, ?, ?)",
                    (_SCHEMA_VERSION, json.dumps(payload, ensure_ascii=False)),
                )
                connection.commit()
                return payload

            payload = json.loads(row["payload_json"])
            if not isinstance(payload, dict):
                payload = {}
            return _normalize_settings(payload)
        finally:
            connection.close()


def set_settings(patch: dict[str, Any], db_path: Path | None = None) -> dict[str, Any]:
    if not isinstance(patch, dict):
        patch = {}

    with _DB_LOCK:
        connection = _connect(db_path)
        try:
            _ensure_schema(connection)
            row = connection.execute("SELECT payload_json FROM settings WHERE id = 1").fetchone()
            current: dict[str, Any]
            if row is None:
                current = dict(DEFAULT_SETTINGS)
            else:
                value = json.loads(row["payload_json"])
                current = value if isinstance(value, dict) else dict(DEFAULT_SETTINGS)

            merged = dict(current)
            for key, value in patch.items():
                if key in DEFAULT_SETTINGS:
                    merged[key] = value
            normalized = _normalize_settings(merged)

            connection.execute(
                """
                INSERT INTO settings (id, schema_version, payload_json)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  schema_version=excluded.schema_version,
                  payload_json=excluded.payload_json
                """,
                (_SCHEMA_VERSION, json.dumps(normalized, ensure_ascii=False)),
            )
            connection.commit()
            return normalized
        finally:
            connection.close()
