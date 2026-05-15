from __future__ import annotations

from pathlib import Path
import json
import tempfile
import threading

import pytest

from grimmory_bridge.plan import build_plan, clear_cached_plans
from grimmory_bridge.run import RunError, RunManager
import grimmory_bridge.run as run_mod


OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Book</dc:title>
    <dc:creator>Author</dc:creator>
  </metadata>
</package>
"""


def _seed_epub(root: Path, name: str) -> None:
    book = root / f"{name}.epub"
    book.write_bytes(b"epub")
    book.with_suffix(".opf").write_text(OPF, encoding="utf-8")


def test_run_dry_emits_notifications_and_summary() -> None:
    clear_cached_plans()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for idx in range(3):
            _seed_epub(root, f"Book-{idx}")
        plan = build_plan([str(root)], ext_kinds=["epub"])

    manager = RunManager()
    done = threading.Event()
    events: list[tuple[str, dict]] = []

    def _notify(method: str, params: dict) -> None:
        events.append((method, params))
        if method == "run_done":
            done.set()

    started = manager.start(plan_id=plan["plan_id"], mode="dry", books=None, settings=None, notify=_notify)
    assert started["run_id"].startswith("r_")
    assert started["total"] == 3
    assert done.wait(5)

    methods = [method for method, _ in events]
    assert methods.count("book_done") == 3
    assert "progress" in methods
    assert "run_done" in methods

    run_done = [params for method, params in events if method == "run_done"][0]
    summary = run_done["summary"]
    assert summary["mode"] == "dry"
    assert summary["total"] == 3
    assert summary["written"] == 0
    assert summary["skipped"] == 3
    assert summary["failed"] == 0


def test_run_plan_stale_raises_error() -> None:
    manager = RunManager()

    with pytest.raises(RunError) as exc:
        manager.start(plan_id="p_not_found", mode="dry", books=None, settings=None, notify=lambda *_: None)

    assert exc.value.code == 1003
    assert exc.value.message == "PLAN_STALE"


def test_run_write_creates_backup_and_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_cached_plans()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        runs_root = root / "runs-out"
        _seed_epub(root, "Book-0")
        plan = build_plan([str(root)], ext_kinds=["epub"])

        monkeypatch.setattr(run_mod, "parse_opf", lambda _path: {"title": "Book"})
        monkeypatch.setattr(run_mod, "embed_epub", lambda _book, _opf, _opts: True)
        monkeypatch.setattr(run_mod, "write_sidecars", lambda _book, _opf, _opts: True)

        manager = RunManager(runs_root=runs_root)
        done = threading.Event()
        events: list[tuple[str, dict]] = []

        def _notify(method: str, params: dict) -> None:
            events.append((method, params))
            if method == "run_done":
                done.set()

        started = manager.start(
            plan_id=plan["plan_id"],
            mode="write",
            books=None,
            settings={"backup_before_write": True, "backup_extension": ".bak"},
            notify=_notify,
        )
        assert done.wait(5)

        run_done = [params for method, params in events if method == "run_done"][0]
        summary = run_done["summary"]
        assert summary["mode"] == "write"
        assert summary["written"] == 1
        assert summary["failed"] == 0
        assert summary["rollback_available"] is True

        backup_path = root / "Book-0.epub.bak"
        assert backup_path.exists()

        manifest_path = runs_root / started["run_id"] / "manifest.json"
        assert manifest_path.exists()
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert len(payload["entries"]) == 1
        assert payload["entries"][0]["status"] == "written"


def test_run_write_failure_emits_halt_and_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_cached_plans()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        runs_root = root / "runs-out"
        _seed_epub(root, "Book-0")
        plan = build_plan([str(root)], ext_kinds=["epub"])

        monkeypatch.setattr(run_mod, "parse_opf", lambda _path: {"title": "Book"})

        def _boom(_book, _opf, _opts):
            raise RuntimeError("boom")

        monkeypatch.setattr(run_mod, "embed_epub", _boom)
        monkeypatch.setattr(run_mod, "write_sidecars", lambda _book, _opf, _opts: True)

        manager = RunManager(runs_root=runs_root)
        halted = threading.Event()
        events: list[tuple[str, dict]] = []

        def _notify(method: str, params: dict) -> None:
            events.append((method, params))
            if method == "run_halted":
                halted.set()

        manager.start(
            plan_id=plan["plan_id"],
            mode="write",
            books=None,
            settings={"backup_before_write": True, "backup_extension": ".bak"},
            notify=_notify,
        )
        assert halted.wait(5)

        methods = [method for method, _ in events]
        assert "run_halted" in methods
        assert "run_done" not in methods

        halted_event = [params for method, params in events if method == "run_halted"][0]
        assert halted_event["error"]["message"] == "WRITE_HALTED"
        assert halted_event["summary"]["failed"] == 1


def test_rollback_restores_backup_and_marks_manifest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        runs_root = root / "runs-out"
        run_id = "r_testrollback"
        run_dir = runs_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        book_path = root / "Book-0.epub"
        book_path.write_bytes(b"changed")
        backup_path = root / "Book-0.epub.bak"
        backup_path.write_bytes(b"original")
        sidecar_path = root / "Book-0.metadata.json"
        sidecar_path.write_text("{}", encoding="utf-8")

        manifest_path = run_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "updated_at": "2026-05-14T00:00:00Z",
                    "entries": [
                        {
                            "book_id": "b1",
                            "status": "written",
                            "at": "2026-05-14T00:00:00Z",
                            "backup_path": str(backup_path),
                            "outputs": [
                                {"kind": "epub", "path": str(book_path), "op": "write"},
                                {"kind": "sidecar_json", "path": str(sidecar_path), "op": "create"},
                            ],
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        manager = RunManager(runs_root=runs_root)
        summary = manager.rollback(run_id)
        assert summary["run_id"] == run_id
        assert summary["written"] == 1
        assert summary["failed"] == 0
        assert summary["rollback_available"] is False
        assert book_path.read_bytes() == b"original"
        assert not sidecar_path.exists()

        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert payload["entries"][0]["rolled_back"] is True
