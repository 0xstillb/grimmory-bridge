from __future__ import annotations

from pathlib import Path
import tempfile

import grimmory_bridge.history as history_mod
from grimmory_bridge.rpc import RpcError, _dispatch


def test_history_store_list_get_roundtrip(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "runs" / "history.db"
        monkeypatch.setattr(history_mod, "_DEFAULT_DB_PATH", db_path)

        history_mod.save_run_record(
            run_id="r_abc",
            started_at="2026-05-14T10:00:00Z",
            ended_at="2026-05-14T10:00:10Z",
            mode="dry",
            roots=["C:/Books"],
            summary={"run_id": "r_abc", "written": 0, "skipped": 1, "failed": 0},
            plan={"plan_id": "p_123", "books": []},
            manifest_path="C:/runs/r_abc/manifest.json",
            rollback_available=False,
        )

        rows = history_mod.list_history(limit=10, offset=0)
        assert len(rows) == 1
        assert rows[0]["run_id"] == "r_abc"
        assert rows[0]["mode"] == "dry"
        assert rows[0]["roots"] == ["C:/Books"]

        detail = history_mod.get_history("r_abc")
        assert detail is not None
        assert detail["run_id"] == "r_abc"
        assert detail["plan"]["plan_id"] == "p_123"


def test_history_dispatch_calls_data_layer(monkeypatch) -> None:
    monkeypatch.setattr("grimmory_bridge.rpc.list_history", lambda limit=50, offset=0: [{"run_id": "r_one", "mode": "dry"}])
    monkeypatch.setattr(
        "grimmory_bridge.rpc.get_history",
        lambda run_id: {"run_id": run_id, "plan": {"plan_id": "p_a"}} if run_id == "r_ok" else None,
    )

    rows = _dispatch("history.list", {"limit": 5, "offset": 0})
    assert isinstance(rows, list)
    assert rows[0]["run_id"] == "r_one"

    detail = _dispatch("history.get", {"run_id": "r_ok"})
    assert detail["run_id"] == "r_ok"
    assert detail["plan"]["plan_id"] == "p_a"

    try:
        _dispatch("history.get", {"run_id": "r_missing"})
        assert False, "expected RpcError"
    except RpcError as err:
        assert err.code == 1006
