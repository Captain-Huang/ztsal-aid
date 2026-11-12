from __future__ import annotations

import pytest

from lastz_assistant.catalog import ACTION_CATALOG
from lastz_assistant.models import ActionSettings, ConfigError, RunSettings
from lastz_assistant.validation import validate_run_settings


def _settings(**overrides: object) -> RunSettings:
    base = {
        "hwnd": 10,
        "interval_sec": 0.5,
        "dry_run": True,
        "actions": (
            ActionSettings("alliance_help", True, "help.png", 0.85, 5),
            ActionSettings("reconnect", False, "", 0.88, 8),
        ),
    }
    base.update(overrides)
    return RunSettings(**base)  # type: ignore[arg-type]


def test_accepts_a_single_enabled_action() -> None:
    validate_run_settings(_settings(), ACTION_CATALOG)


def test_rejects_bad_interval_threshold_cooldown_and_missing_pieces() -> None:
    with pytest.raises(ConfigError, match="目标窗口"):
        validate_run_settings(_settings(hwnd=0), ACTION_CATALOG)
    with pytest.raises(ConfigError, match="扫描间隔"):
        validate_run_settings(_settings(interval_sec=0.19), ACTION_CATALOG)
    with pytest.raises(ConfigError, match="至少启用一个"):
        validate_run_settings(
            _settings(
                actions=(
                    ActionSettings("alliance_help", False, "", 0.85, 5),
                    ActionSettings("reconnect", False, "", 0.88, 8),
                )
            ),
            ACTION_CATALOG,
        )
    with pytest.raises(ConfigError, match="模板"):
        validate_run_settings(
            _settings(actions=(ActionSettings("alliance_help", True, "  ", 0.85, 5),)),
            ACTION_CATALOG,
        )
    with pytest.raises(ConfigError, match="阈值"):
        validate_run_settings(
            _settings(actions=(ActionSettings("alliance_help", True, "a.png", 0.49, 5),)),
            ACTION_CATALOG,
        )
    with pytest.raises(ConfigError, match="阈值"):
        validate_run_settings(
            _settings(actions=(ActionSettings("alliance_help", True, "a.png", 1, 5),)),
            ACTION_CATALOG,
        )
    with pytest.raises(ConfigError, match="冷却"):
        validate_run_settings(
            _settings(actions=(ActionSettings("alliance_help", True, "a.png", 0.85, 0.4),)),
            ACTION_CATALOG,
        )
    with pytest.raises(ConfigError, match="未知动作"):
        validate_run_settings(
            _settings(actions=(ActionSettings("not_a_real_action", True, "a.png", 0.85, 5),)),
            ACTION_CATALOG,
        )
