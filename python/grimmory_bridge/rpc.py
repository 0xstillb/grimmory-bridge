from __future__ import annotations

import json
from pathlib import Path
import platform
import sys
import threading
from dataclasses import dataclass
from typing import Any, Callable

_WRITE_LOCK = threading.Lock()
_LAST_PLAN_ID: str | None = None
_RUN_CONTEXTS: dict[str, dict[str, Any]] = {}
_RUN_CONTEXTS_LOCK = threading.Lock()
_RUN_MANAGER: Any | None = None

_HISTORY_API: tuple[Callable[..., Any], Callable[..., Any], Callable[..., Any]] | None = None
_PLAN_API: tuple[Callable[..., Any], Callable[..., Any]] | None = None
_RUN_MANAGER_CLASS: Any | None = None
_SCAN_API: Callable[..., Any] | None = None
_SETTINGS_API: tuple[Callable[..., Any], Callable[..., Any]] | None = None


def _configure_stdio_utf8() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


@dataclass
class RpcError(Exception):
    code: int
    message: str
    data: Any | None = None


def _write_json(payload: dict[str, Any]) -> None:
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    with _WRITE_LOCK:
        sys.stdout.write(line)
        sys.stdout.flush()


def _write_error(request_id: Any, err: RpcError) -> None:
    payload: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": err.code, "message": err.message},
    }
    if err.data is not None:
        payload["error"]["data"] = err.data
    _write_json(payload)


def _load_history_api() -> tuple[Callable[..., Any], Callable[..., Any], Callable[..., Any]]:
    global _HISTORY_API
    if _HISTORY_API is None:
        try:
            from .history import get_history, list_history, save_run_record
        except ImportError:  # PyInstaller onefile entrypoint fallback
            from grimmory_bridge.history import get_history, list_history, save_run_record  # type: ignore
        _HISTORY_API = (get_history, list_history, save_run_record)
    return _HISTORY_API


def _load_plan_api() -> tuple[Callable[..., Any], Callable[..., Any]]:
    global _PLAN_API
    if _PLAN_API is None:
        try:
            from .plan import build_plan, get_cached_plan
        except ImportError:  # PyInstaller onefile entrypoint fallback
            from grimmory_bridge.plan import build_plan, get_cached_plan  # type: ignore
        _PLAN_API = (build_plan, get_cached_plan)
    return _PLAN_API


def _load_run_manager_class() -> Any:
    global _RUN_MANAGER_CLASS
    if _RUN_MANAGER_CLASS is None:
        try:
            from .run import RunManager
        except ImportError:  # PyInstaller onefile entrypoint fallback
            from grimmory_bridge.run import RunManager  # type: ignore
        _RUN_MANAGER_CLASS = RunManager
    return _RUN_MANAGER_CLASS


def _load_scan_api() -> Callable[..., Any]:
    global _SCAN_API
    if _SCAN_API is None:
        try:
            from .scan import scan_roots
        except ImportError:  # PyInstaller onefile entrypoint fallback
            from grimmory_bridge.scan import scan_roots  # type: ignore
        _SCAN_API = scan_roots
    return _SCAN_API


def _load_settings_api() -> tuple[Callable[..., Any], Callable[..., Any]]:
    global _SETTINGS_API
    if _SETTINGS_API is None:
        try:
            from .settings import get_settings, set_settings
        except ImportError:  # PyInstaller onefile entrypoint fallback
            from grimmory_bridge.settings import get_settings, set_settings  # type: ignore
        _SETTINGS_API = (get_settings, set_settings)
    return _SETTINGS_API


def _get_run_manager() -> Any:
    global _RUN_MANAGER
    if _RUN_MANAGER is None:
        run_manager_class = _load_run_manager_class()
        _RUN_MANAGER = run_manager_class()
    return _RUN_MANAGER


def _coerce_known_rpc_error(exc: Exception) -> RpcError | None:
    code = getattr(exc, "code", None)
    message = getattr(exc, "message", None)
    data = getattr(exc, "data", None)
    if isinstance(code, int) and isinstance(message, str):
        return RpcError(code=code, message=message, data=data)
    return None


def _app_version() -> dict[str, Any]:
    return {
        "app": "grimmory-bridge",
        "version": "0.1.0",
        "python": platform.python_version(),
        "capabilities": [
            "rpc.app_version",
            "rpc.scan",
            "rpc.plan",
            "rpc.compat_check",
            "rpc.history_list",
            "rpc.history_get",
            "rpc.settings_get",
            "rpc.settings_set",
            "rpc.run",
            "rpc.rollback",
        ],
    }


def _manifest_path_for_run(run_id: str) -> str:
    return str(Path.cwd() / "runs" / run_id / "manifest.json")


def _persist_history_from_event(method_name: str, method_params: dict[str, Any]) -> None:
    if method_name not in {"run_done", "run_halted"}:
        return

    run_id = method_params.get("run_id")
    summary = method_params.get("summary")
    if not isinstance(run_id, str) or not isinstance(summary, dict):
        return

    with _RUN_CONTEXTS_LOCK:
        context = _RUN_CONTEXTS.pop(run_id, None)
    if context is None:
        return

    plan_snapshot = context.get("plan")
    roots = context.get("roots")
    if not isinstance(plan_snapshot, dict):
        return
    if not isinstance(roots, list):
        roots = []

    _, _, save_run_record = _load_history_api()
    save_run_record(
        run_id=run_id,
        started_at=str(summary.get("started_at", "")),
        ended_at=str(summary.get("ended_at", "")),
        mode=str(summary.get("mode", "dry")),
        roots=[str(root) for root in roots],
        summary=summary,
        plan=plan_snapshot,
        manifest_path=_manifest_path_for_run(run_id),
        rollback_available=bool(summary.get("rollback_available")),
    )


def _dispatch(method: str, params: Any) -> Any:
    global _LAST_PLAN_ID

    if method == "app.version":
        return _app_version()
    if method == "scan":
        scan_roots = _load_scan_api()
        roots = params.get("roots", []) if isinstance(params, dict) else []
        ext = params.get("ext") if isinstance(params, dict) else None
        return scan_roots(roots=roots, ext_kinds=ext)
    if method == "plan":
        build_plan, _ = _load_plan_api()
        roots = params.get("roots", []) if isinstance(params, dict) else []
        ext = params.get("ext") if isinstance(params, dict) else None
        source_priority = params.get("source_priority") if isinstance(params, dict) else None

        def _progress(scan_id: str, current: int, total: int) -> None:
            _write_json(
                {
                    "jsonrpc": "2.0",
                    "method": "plan_progress",
                    "params": {
                        "scan_id": scan_id,
                        "current": current,
                        "total": total,
                    },
                }
            )

        result = build_plan(
            roots=roots,
            ext_kinds=ext,
            source_priority=source_priority,
            progress_cb=_progress,
        )
        _LAST_PLAN_ID = str(result.get("plan_id"))
        return result
    if method == "compat.check":
        _, get_cached_plan = _load_plan_api()
        if not isinstance(params, dict):
            raise RpcError(-32602, "Invalid params", {"reason": "params must be an object"})

        book_id = params.get("book_id")
        if not isinstance(book_id, str) or not book_id:
            raise RpcError(-32602, "Invalid params", {"reason": "book_id is required"})

        plan_id = params.get("plan_id")
        if not isinstance(plan_id, str) or not plan_id:
            plan_id = _LAST_PLAN_ID
        if not isinstance(plan_id, str) or not plan_id:
            raise RpcError(1003, "PLAN_STALE", {"reason": "No plan has been built in this session"})

        plan = get_cached_plan(plan_id)
        if plan is None:
            raise RpcError(1003, "PLAN_STALE", {"plan_id": plan_id})

        for book in plan.get("books", []):
            if book.get("book_id") == book_id:
                compat = book.get("compat", [])
                return compat if isinstance(compat, list) else []
        raise RpcError(1005, "BOOK_NOT_FOUND", {"book_id": book_id, "plan_id": plan_id})
    if method == "history.list":
        _, list_history, _ = _load_history_api()
        if not isinstance(params, dict):
            params = {}
        limit = params.get("limit", 50)
        offset = params.get("offset", 0)
        try:
            limit_int = max(1, min(500, int(limit)))
            offset_int = max(0, int(offset))
        except Exception as exc:
            raise RpcError(-32602, "Invalid params", {"reason": "limit/offset must be numeric", "cause": str(exc)})
        return list_history(limit=limit_int, offset=offset_int)
    if method == "history.get":
        get_history, _, _ = _load_history_api()
        if not isinstance(params, dict):
            raise RpcError(-32602, "Invalid params", {"reason": "params must be an object"})
        run_id = params.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise RpcError(-32602, "Invalid params", {"reason": "run_id is required"})
        detail = get_history(run_id)
        if detail is None:
            raise RpcError(1006, "RUN_NOT_FOUND", {"run_id": run_id})
        return detail
    if method == "settings.get":
        get_settings, _ = _load_settings_api()
        return get_settings()
    if method == "settings.set":
        _, set_settings = _load_settings_api()
        if not isinstance(params, dict):
            raise RpcError(-32602, "Invalid params", {"reason": "patch must be an object"})
        return set_settings(params)
    if method == "run":
        _, get_cached_plan = _load_plan_api()
        plan_id = params.get("plan_id") if isinstance(params, dict) else None
        mode = params.get("mode") if isinstance(params, dict) else None
        books = params.get("books") if isinstance(params, dict) else None
        settings = params.get("settings") if isinstance(params, dict) else None
        if not isinstance(plan_id, str) or not isinstance(mode, str):
            raise RpcError(-32602, "Invalid params", {"reason": "plan_id and mode are required"})
        if settings is not None and not isinstance(settings, dict):
            raise RpcError(-32602, "Invalid params", {"reason": "settings must be an object"})
        plan_snapshot = get_cached_plan(plan_id)
        if plan_snapshot is None:
            raise RpcError(1003, "PLAN_STALE", {"plan_id": plan_id})
        roots = plan_snapshot.get("roots", [])
        if not isinstance(roots, list):
            roots = []

        def _notify(method_name: str, method_params: dict[str, Any]) -> None:
            _write_json({"jsonrpc": "2.0", "method": method_name, "params": method_params})
            try:
                _persist_history_from_event(method_name, method_params)
            except Exception:
                pass

        run_manager = _get_run_manager()
        started = run_manager.start(
            plan_id=plan_id,
            mode=mode,
            books=books,
            settings=settings,
            notify=_notify,
        )
        run_id = started.get("run_id")
        if isinstance(run_id, str):
            with _RUN_CONTEXTS_LOCK:
                _RUN_CONTEXTS[run_id] = {"plan": plan_snapshot, "roots": roots}
        return started
    if method == "rollback":
        if not isinstance(params, dict):
            raise RpcError(-32602, "Invalid params", {"reason": "params must be an object"})
        run_id = params.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise RpcError(-32602, "Invalid params", {"reason": "run_id is required"})
        run_manager = _get_run_manager()
        return run_manager.rollback(run_id)
    raise RpcError(-32601, "Method not found", {"method": method})


def run() -> None:
    _configure_stdio_utf8()
    print("[grimmory-bridge-py] sidecar started", file=sys.stderr, flush=True)
    for line in sys.stdin:
        text = line.strip()
        if not text:
            continue

        request_id: Any = None
        try:
            req = json.loads(text)
            if req.get("jsonrpc") != "2.0":
                raise RpcError(-32600, "Invalid Request", {"reason": "jsonrpc must be 2.0"})

            request_id = req.get("id")
            method = req.get("method")
            if not isinstance(method, str):
                raise RpcError(-32600, "Invalid Request", {"reason": "method must be string"})

            print(f"[grimmory-bridge-py] method={method}", file=sys.stderr, flush=True)
            result = _dispatch(method, req.get("params", {}))
            _write_json({"jsonrpc": "2.0", "id": request_id, "result": result})
        except RpcError as err:
            _write_error(request_id, err)
        except json.JSONDecodeError:
            _write_error(request_id, RpcError(-32700, "Parse error"))
        except Exception as exc:  # defensive: keep sidecar alive for malformed calls
            mapped = _coerce_known_rpc_error(exc)
            if mapped is not None:
                _write_error(request_id, mapped)
            else:
                _write_error(request_id, RpcError(-32603, "Internal error", {"cause": str(exc)}))


if __name__ == "__main__":
    run()
