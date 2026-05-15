from __future__ import annotations

from pathlib import Path
import tempfile

import grimmory_bridge.settings as settings_mod
from grimmory_bridge.rpc import _dispatch


def test_settings_get_set_persist_roundtrip(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "runs" / "settings.db"
        monkeypatch.setattr(settings_mod, "_DEFAULT_DB_PATH", db_path)

        defaults = settings_mod.get_settings()
        assert defaults["theme"] == "dark"
        assert defaults["density"] == "comfy"
        assert defaults["accent"] == "indigo"

        updated = settings_mod.set_settings({"theme": "light", "density": "compact", "accent": "teal", "enabled_kinds": ["epub"]})
        assert updated["theme"] == "light"
        assert updated["density"] == "compact"
        assert updated["accent"] == "teal"
        assert updated["enabled_kinds"] == ["epub"]

        again = settings_mod.get_settings()
        assert again["theme"] == "light"
        assert again["density"] == "compact"
        assert again["accent"] == "teal"


def test_settings_dispatch_calls_data_layer(monkeypatch) -> None:
    monkeypatch.setattr("grimmory_bridge.rpc.get_settings", lambda: {"theme": "dark"})
    monkeypatch.setattr("grimmory_bridge.rpc.set_settings", lambda patch: {"theme": patch.get("theme", "dark")})

    current = _dispatch("settings.get", {})
    assert current["theme"] == "dark"

    changed = _dispatch("settings.set", {"theme": "light"})
    assert changed["theme"] == "light"
