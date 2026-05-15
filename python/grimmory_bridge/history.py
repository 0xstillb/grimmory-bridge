from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from threading import Lock
from typing import Any


_DB_LOCK = Lock()
_DEFAULT_DB_PATH = Path.cwd() / "runs" / "history.db"


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
  path = db_path if db_path is not None else _DEFAULT_DB_PATH
  path.parent.mkdir(parents=True, exist_ok=True)
  connection = sqlite3.connect(path)
  connection.row_factory = sqlite3.Row
  return connection


def _ensure_schema(connection: sqlite3.Connection) -> None:
  connection.execute(
      """
      CREATE TABLE IF NOT EXISTS runs (
        id TEXT PRIMARY KEY,
        started_at TEXT NOT NULL,
        ended_at TEXT NOT NULL,
        mode TEXT NOT NULL,
        roots_json TEXT NOT NULL,
        summary_json TEXT NOT NULL,
        plan_json TEXT NOT NULL,
        manifest_path TEXT NOT NULL,
        rollback_available INTEGER NOT NULL
      )
      """
  )
  connection.commit()


def save_run_record(
  run_id: str,
  started_at: str,
  ended_at: str,
  mode: str,
  roots: list[str],
  summary: dict[str, Any],
  plan: dict[str, Any],
  manifest_path: str,
  rollback_available: bool,
  db_path: Path | None = None,
) -> None:
  with _DB_LOCK:
    connection = _connect(db_path)
    try:
      _ensure_schema(connection)
      connection.execute(
          """
          INSERT OR REPLACE INTO runs (
            id, started_at, ended_at, mode, roots_json, summary_json, plan_json, manifest_path, rollback_available
          )
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
          """,
          (
              run_id,
              started_at,
              ended_at,
              mode,
              json.dumps(roots, ensure_ascii=False),
              json.dumps(summary, ensure_ascii=False),
              json.dumps(plan, ensure_ascii=False),
              manifest_path,
              1 if rollback_available else 0,
          ),
      )
      connection.commit()
    finally:
      connection.close()


def list_history(limit: int = 50, offset: int = 0, db_path: Path | None = None) -> list[dict[str, Any]]:
  with _DB_LOCK:
    connection = _connect(db_path)
    try:
      _ensure_schema(connection)
      cursor = connection.execute(
          """
          SELECT id, started_at, ended_at, mode, roots_json, summary_json, rollback_available
          FROM runs
          ORDER BY ended_at DESC
          LIMIT ? OFFSET ?
          """,
          (limit, offset),
      )
      rows = cursor.fetchall()
    finally:
      connection.close()

  out: list[dict[str, Any]] = []
  for row in rows:
    out.append(
        {
            "run_id": row["id"],
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
            "mode": row["mode"],
            "roots": json.loads(row["roots_json"]),
            "summary": json.loads(row["summary_json"]),
            "rollback_available": bool(row["rollback_available"]),
        }
    )
  return out


def get_history(run_id: str, db_path: Path | None = None) -> dict[str, Any] | None:
  with _DB_LOCK:
    connection = _connect(db_path)
    try:
      _ensure_schema(connection)
      cursor = connection.execute(
          """
          SELECT id, started_at, ended_at, mode, roots_json, summary_json, plan_json, manifest_path, rollback_available
          FROM runs
          WHERE id = ?
          """,
          (run_id,),
      )
      row = cursor.fetchone()
    finally:
      connection.close()

  if row is None:
    return None

  return {
      "run_id": row["id"],
      "started_at": row["started_at"],
      "ended_at": row["ended_at"],
      "mode": row["mode"],
      "roots": json.loads(row["roots_json"]),
      "summary": json.loads(row["summary_json"]),
      "plan": json.loads(row["plan_json"]),
      "manifest_path": row["manifest_path"],
      "rollback_available": bool(row["rollback_available"]),
  }
