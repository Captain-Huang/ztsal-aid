"""把界面上的路径、阈值和演练开关记到本地 JSON。不保存截图。"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from lastz_assistant.models import ActionSpec


def default_settings_path() -> Path:
    return Path.cwd() / "lastz-assistant-settings.json"


def default_settings(catalog: Sequence[ActionSpec]) -> dict[str, Any]:
    return {
        "version": 1,
        "interval_sec": 0.6,
        "dry_run": True,
        "window_title": "",
        "actions": {
            spec.id: {
                "enabled": True,
                "template_path": "",
                "threshold": spec.default_threshold,
                "cooldown_sec": spec.default_cooldown_sec,
            }
            for spec in catalog
        },
    }


def load_settings(path: Path, catalog: Sequence[ActionSpec]) -> dict[str, Any]:
    document = default_settings(catalog)
    if not path.is_file():
        return document
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return document
    if not isinstance(raw, dict):
        return document
    interval = raw.get("interval_sec", document["interval_sec"])
    if isinstance(interval, int | float) and math.isfinite(float(interval)):
        document["interval_sec"] = float(interval)
    if isinstance(raw.get("dry_run"), bool):
        document["dry_run"] = raw["dry_run"]
    if isinstance(raw.get("window_title"), str):
        document["window_title"] = raw["window_title"]
    saved_actions = raw.get("actions")
    if isinstance(saved_actions, dict):
        for spec in catalog:
            current = document["actions"][spec.id]
            saved = saved_actions.get(spec.id)
            if not isinstance(saved, dict):
                continue
            if isinstance(saved.get("enabled"), bool):
                current["enabled"] = saved["enabled"]
            template_path = saved.get("template_path")
            if isinstance(template_path, str):
                current["template_path"] = template_path
            threshold = saved.get("threshold")
            if isinstance(threshold, int | float) and math.isfinite(float(threshold)):
                current["threshold"] = float(threshold)
            cooldown = saved.get("cooldown_sec")
            if isinstance(cooldown, int | float) and math.isfinite(float(cooldown)):
                current["cooldown_sec"] = float(cooldown)
    return document


def save_settings(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
