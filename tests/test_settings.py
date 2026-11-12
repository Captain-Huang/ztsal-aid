from __future__ import annotations

import json
from pathlib import Path

from lastz_assistant.catalog import ACTION_CATALOG
from lastz_assistant.settings_store import default_settings, load_settings, save_settings


def test_missing_or_corrupt_file_falls_back_to_dry_run_defaults(tmp_path: Path) -> None:
    loaded = load_settings(tmp_path / "missing.json", ACTION_CATALOG)
    assert loaded["dry_run"] is True
    assert set(loaded["actions"]) == {"alliance_help", "reconnect"}
    assert loaded["actions"]["alliance_help"]["template_path"] == ""

    corrupt = tmp_path / "bad.json"
    corrupt.write_text("{", encoding="utf-8")
    assert load_settings(corrupt, ACTION_CATALOG)["dry_run"] is True


def test_roundtrip_keeps_known_actions_and_ignores_unknown_ones(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    document = default_settings(ACTION_CATALOG)
    document["dry_run"] = False
    document["interval_sec"] = 0.4
    document["window_title"] = "Last Z"
    document["actions"]["alliance_help"]["template_path"] = "C:/shots/帮助.png"
    document["actions"]["alliance_help"]["threshold"] = 0.91
    document["actions"]["extra_future"] = {"enabled": True, "template_path": "nope.png"}
    save_settings(path, document)

    loaded = load_settings(path, ACTION_CATALOG)
    assert loaded["dry_run"] is False
    assert loaded["interval_sec"] == 0.4
    assert loaded["window_title"] == "Last Z"
    assert loaded["actions"]["alliance_help"]["template_path"] == "C:/shots/帮助.png"
    assert loaded["actions"]["alliance_help"]["threshold"] == 0.91
    assert "extra_future" not in loaded["actions"]
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["actions"]["alliance_help"]["template_path"].endswith("帮助.png")
