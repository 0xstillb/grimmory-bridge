from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
import threading
from typing import Any, Callable
import uuid

try:
    from .epub import embed_epub
except ImportError:  # PyInstaller onefile entrypoint fallback
    from grimmory_bridge.epub import embed_epub  # type: ignore

try:
    from .opf import parse_opf
except ImportError:  # PyInstaller onefile entrypoint fallback
    from grimmory_bridge.opf import parse_opf  # type: ignore

try:
    from .plan import get_cached_plan
except ImportError:  # PyInstaller onefile entrypoint fallback
    from grimmory_bridge.plan import get_cached_plan  # type: ignore

try:
    from .pdf import embed_pdf
except ImportError:  # PyInstaller onefile entrypoint fallback
    from grimmory_bridge.pdf import embed_pdf  # type: ignore

try:
    from .sidecar import write_sidecars
except ImportError:  # PyInstaller onefile entrypoint fallback
    from grimmory_bridge.sidecar import write_sidecars  # type: ignore


NotifyCallback = Callable[[str, dict[str, Any]], None]


@dataclass
class RunError(Exception):
    code: int
    message: str
    data: dict[str, Any] | None = None


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _resolve_opf_path(book_path: Path) -> Path | None:
    same_stem = book_path.with_suffix(".opf")
    if same_stem.exists():
        return same_stem

    metadata = book_path.parent / "metadata.opf"
    if metadata.exists():
        return metadata
    return None


def _resolve_primary_output(outputs: list[dict[str, Any]]) -> tuple[str, Path] | None:
    for output in outputs:
        kind = output.get("kind")
        if kind in {"epub", "pdf"}:
            return str(kind), Path(str(output.get("path")))
    return None


class RunManager:
    def __init__(self, runs_root: str | Path | None = None) -> None:
        self._lock = threading.Lock()
        self._active_run_id: str | None = None
        self._active_thread: threading.Thread | None = None
        self._runs_root = Path(runs_root) if runs_root is not None else Path.cwd() / "runs"

    def _manifest_path(self, run_id: str) -> Path:
        return self._runs_root / run_id / "manifest.json"

    def _append_manifest_entry(self, run_id: str, entry: dict[str, Any]) -> None:
        manifest_path = self._manifest_path(run_id)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "run_id": run_id,
            "updated_at": _iso_now(),
            "entries": [],
        }
        if manifest_path.exists():
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))

        payload.setdefault("entries", []).append(entry)
        payload["updated_at"] = _iso_now()
        manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def rollback(self, run_id: str) -> dict[str, Any]:
        manifest_path = self._manifest_path(run_id)
        if not manifest_path.exists():
            raise RunError(1012, "WRITE_FAILED", {"reason": "manifest missing", "run_id": run_id})

        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = payload.get("entries", [])
        if not isinstance(entries, list):
            entries = []

        restored = 0
        failed: list[dict[str, Any]] = []
        changed_files: list[str] = []

        for idx, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            if bool(entry.get("rolled_back")):
                continue

            outputs = entry.get("outputs", [])
            if not isinstance(outputs, list):
                outputs = []

            primary = _resolve_primary_output(outputs)
            backup_path_raw = entry.get("backup_path")
            if primary is not None and isinstance(backup_path_raw, str) and backup_path_raw:
                primary_path = primary[1]
                backup_path = Path(backup_path_raw)
                try:
                    if not backup_path.exists():
                        raise RuntimeError(f"missing backup: {backup_path}")
                    shutil.copy2(backup_path, primary_path)
                    restored += 1
                    changed_files.append(str(primary_path))
                except Exception as exc:
                    failed.append({"book_id": entry.get("book_id"), "path": str(primary_path), "cause": str(exc)})

            for output in outputs:
                if not isinstance(output, dict):
                    continue
                if output.get("kind") not in {"sidecar_json", "sidecar_cover"}:
                    continue
                if output.get("op") != "create":
                    continue
                path_raw = output.get("path")
                if not isinstance(path_raw, str) or not path_raw:
                    continue
                path = Path(path_raw)
                try:
                    if path.exists():
                        path.unlink()
                        changed_files.append(str(path))
                except Exception as exc:
                    failed.append({"book_id": entry.get("book_id"), "path": str(path), "cause": str(exc)})

            entries[idx]["rolled_back"] = True
            entries[idx]["rolled_back_at"] = _iso_now()

        payload["entries"] = entries
        payload["updated_at"] = _iso_now()
        manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        total = len(entries)
        summary = {
            "run_id": run_id,
            "started_at": payload.get("updated_at", _iso_now()),
            "ended_at": _iso_now(),
            "mode": "write",
            "total": total,
            "written": restored,
            "skipped": max(0, total - restored - len(failed)),
            "failed": len(failed),
            "changed_files": changed_files,
            "rollback_available": False,
        }

        if failed:
            raise RunError(1012, "WRITE_FAILED", {"run_id": run_id, "failures": failed, "summary": summary})
        return summary

    def start(
        self,
        plan_id: str,
        mode: str,
        books: list[str] | None,
        settings: dict[str, Any] | None,
        notify: NotifyCallback,
    ) -> dict[str, Any]:
        with self._lock:
            if self._active_thread is not None and self._active_thread.is_alive():
                raise RunError(1002, "RUN_IN_PROGRESS")

            plan = get_cached_plan(plan_id)
            if plan is None:
                raise RunError(1003, "PLAN_STALE", {"plan_id": plan_id})

            if mode not in {"dry", "write"}:
                raise RunError(-32602, "Invalid params", {"reason": "mode must be 'dry' or 'write'"})

            plan_books = plan.get("books", [])
            if books is not None and not isinstance(books, list):
                raise RunError(-32602, "Invalid params", {"reason": "books must be an array of book ids"})
            if books:
                allowed = {book_id for book_id in books if isinstance(book_id, str)}
                selected_books = [book for book in plan_books if book.get("book_id") in allowed]
            else:
                selected_books = list(plan_books)

            run_id = f"r_{uuid.uuid4().hex[:12]}"
            started_at = _iso_now()
            total = len(selected_books)

            worker = threading.Thread(
                target=self._run_worker,
                args=(run_id, started_at, mode, selected_books, settings or {}, notify),
                daemon=True,
            )

            self._active_run_id = run_id
            self._active_thread = worker
            worker.start()

            return {"run_id": run_id, "total": total}

    def _run_worker(
        self,
        run_id: str,
        started_at: str,
        mode: str,
        selected_books: list[dict[str, Any]],
        settings: dict[str, Any],
        notify: NotifyCallback,
    ) -> None:
        total = len(selected_books)
        skipped = 0
        failed = 0
        written = 0
        changed_files: list[str] = []
        manifest_entries = 0
        backup_before_write = bool(settings.get("backup_before_write", True))
        backup_extension = str(settings.get("backup_extension", ".bak"))
        overwrite_sidecars = bool(settings.get("overwrite_sidecars", True))

        try:
            notify("progress", {"run_id": run_id, "current": 0, "total": total, "phase": "verifying"})

            for current, plan_book in enumerate(selected_books, start=1):
                outputs = plan_book.get("outputs", [])
                notify(
                    "progress",
                    {
                        "run_id": run_id,
                        "current": current,
                        "total": total,
                        "phase": "writing" if mode == "write" else "verifying",
                    },
                )

                if mode == "dry":
                    skipped += 1
                    notify(
                        "book_done",
                        {
                            "run_id": run_id,
                            "book_id": plan_book.get("book_id"),
                            "status": "skipped",
                            "outputs": outputs,
                        },
                    )
                    continue

                if plan_book.get("errors"):
                    skipped += 1
                    notify(
                        "book_done",
                        {
                            "run_id": run_id,
                            "book_id": plan_book.get("book_id"),
                            "status": "skipped",
                            "outputs": outputs,
                        },
                    )
                    continue

                primary = _resolve_primary_output(outputs)
                if primary is None:
                    skipped += 1
                    notify(
                        "book_done",
                        {
                            "run_id": run_id,
                            "book_id": plan_book.get("book_id"),
                            "status": "skipped",
                            "outputs": outputs,
                        },
                    )
                    continue

                kind, book_path = primary
                book_id = plan_book.get("book_id")

                try:
                    opf_path = _resolve_opf_path(book_path)
                    if opf_path is None:
                        raise RuntimeError("Missing OPF source")

                    metadata = parse_opf(opf_path)
                    backup_path: str | None = None

                    if backup_before_write:
                        backup_file = Path(str(book_path) + backup_extension)
                        shutil.copy2(book_path, backup_file)
                        backup_path = str(backup_file)

                    if kind == "epub":
                        embed_epub(book_path, metadata, {})
                    elif kind == "pdf":
                        pdf_opts = {
                            "pdf_password": settings.get("pdf_password"),
                            "pdf_user_password": settings.get("pdf_user_password"),
                            "pdf_owner_password": settings.get("pdf_owner_password"),
                            "pdf_passwords": settings.get("pdf_passwords"),
                            "pdf_reencrypt": settings.get("pdf_reencrypt", True),
                            "pdf_encrypt_algorithm": settings.get("pdf_encrypt_algorithm"),
                        }
                        embed_pdf(book_path, metadata, pdf_opts)
                    else:
                        raise RuntimeError(f"Unsupported write kind: {kind}")

                    write_sidecars(book_path, metadata, {"overwrite": overwrite_sidecars})

                    written += 1
                    for output in outputs:
                        changed_files.append(str(output.get("path")))

                    entry = {
                        "book_id": book_id,
                        "status": "written",
                        "at": _iso_now(),
                        "outputs": outputs,
                        "backup_path": backup_path,
                    }
                    self._append_manifest_entry(run_id, entry)
                    manifest_entries += 1

                    notify(
                        "book_done",
                        {
                            "run_id": run_id,
                            "book_id": book_id,
                            "status": "written",
                            "outputs": outputs,
                        },
                    )
                except Exception as exc:
                    failed += 1
                    notify(
                        "book_done",
                        {
                            "run_id": run_id,
                            "book_id": book_id,
                            "status": "failed",
                            "outputs": outputs,
                            "error": {"code": 1011, "message": "WRITE_HALTED", "data": {"cause": str(exc)}},
                        },
                    )
                    summary = {
                        "run_id": run_id,
                        "started_at": started_at,
                        "ended_at": _iso_now(),
                        "mode": mode,
                        "total": total,
                        "written": written,
                        "skipped": skipped,
                        "failed": failed,
                        "changed_files": changed_files,
                        "rollback_available": manifest_entries > 0,
                    }
                    notify(
                        "run_halted",
                        {
                            "run_id": run_id,
                            "at_book_id": book_id,
                            "error": {"code": 1011, "message": "WRITE_HALTED", "data": {"cause": str(exc)}},
                            "summary": summary,
                        },
                    )
                    return

                notify(
                    "log",
                    {"run_id": run_id, "level": "info", "message": f"Processed {current}/{total}", "ts": _iso_now()},
                )

            summary = {
                "run_id": run_id,
                "started_at": started_at,
                "ended_at": _iso_now(),
                "mode": mode,
                "total": total,
                "written": written,
                "skipped": skipped,
                "failed": failed,
                "changed_files": changed_files,
                "rollback_available": manifest_entries > 0,
            }
            notify("run_done", {"run_id": run_id, "summary": summary})
        except Exception as exc:
            summary = {
                "run_id": run_id,
                "started_at": started_at,
                "ended_at": _iso_now(),
                "mode": mode,
                "total": total,
                "written": written,
                "skipped": skipped,
                "failed": max(1, failed),
                "changed_files": changed_files,
                "rollback_available": manifest_entries > 0,
            }
            notify(
                "run_halted",
                {
                    "run_id": run_id,
                    "at_book_id": None,
                    "error": {"code": 1011, "message": "WRITE_HALTED", "data": {"cause": str(exc)}},
                    "summary": summary,
                },
            )
        finally:
            with self._lock:
                if self._active_run_id == run_id:
                    self._active_run_id = None
                self._active_thread = None
