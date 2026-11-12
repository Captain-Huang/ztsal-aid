"""启动前的配置校验。界面和引擎共用，避免两套规则。"""

from __future__ import annotations

import math
from collections.abc import Sequence

from lastz_assistant.models import ActionSettings, ActionSpec, ConfigError, RunSettings


def validate_run_settings(settings: RunSettings, catalog: Sequence[ActionSpec]) -> None:
    if settings.hwnd <= 0:
        raise ConfigError("请选择目标窗口")
    if not math.isfinite(settings.interval_sec) or not 0.2 <= settings.interval_sec <= 30:
        raise ConfigError("扫描间隔需在 0.2 到 30 秒之间")
    by_id = {spec.id: spec for spec in catalog}
    if len(by_id) != len(tuple(catalog)):
        raise ConfigError("动作目录存在重复 id")
    enabled = 0
    seen: set[str] = set()
    for action in settings.actions:
        if action.action_id in seen:
            raise ConfigError(f"动作重复：{action.action_id}")
        seen.add(action.action_id)
        spec = by_id.get(action.action_id)
        if spec is None:
            raise ConfigError(f"未知动作：{action.action_id}")
        if action.enabled:
            enabled += 1
            _validate_enabled(action, spec)
    if enabled == 0:
        raise ConfigError("请至少启用一个动作")


def _validate_enabled(action: ActionSettings, spec: ActionSpec) -> None:
    if not action.template_path.strip():
        raise ConfigError(f"请为「{spec.name}」选择模板 PNG")
    if not math.isfinite(action.threshold) or not 0.5 <= action.threshold <= 0.99:
        raise ConfigError(f"「{spec.name}」的匹配阈值需在 0.50 到 0.99 之间")
    if not math.isfinite(action.cooldown_sec) or not 0.5 <= action.cooldown_sec <= 600:
        raise ConfigError(f"「{spec.name}」的冷却时间需在 0.5 到 600 秒之间")
    if spec.confirm_frames < 2:
        raise ConfigError(f"「{spec.name}」至少需要连续 2 帧确认")
