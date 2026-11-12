"""界面与状态机共用的数据结构。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

_ACTION_ID = re.compile(r"^[a-z][a-z0-9_]{1,40}$")


class AssistantError(Exception):
    """需要告诉用户、并且不能继续自动点击的错误。"""


class ConfigError(AssistantError):
    """配置不完整或不合法。"""


class TemplateError(AssistantError):
    """模板缺失、损坏，或无法用于当前画面。"""


class CaptureError(AssistantError):
    """截取窗口客户区失败。"""


class EventKind(StrEnum):
    CONFIRMING = "confirming"
    CLICK = "click"
    DRY_RUN = "dry_run"
    SKIP_NOT_FOREGROUND = "skip_not_foreground"
    COOLDOWN = "cooldown"
    SCORE = "score"
    ERROR = "error"
    STOPPED = "stopped"
    LOG = "log"


@dataclass(frozen=True)
class EngineEvent:
    kind: EventKind
    message: str
    action_id: str | None = None
    score: float | None = None
    screen_x: int | None = None
    screen_y: int | None = None


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    width: int
    height: int

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x < self.left + self.width and self.top <= y < self.top + self.height

    def same_geometry(self, other: Rect) -> bool:
        return (
            self.left == other.left
            and self.top == other.top
            and self.width == other.width
            and self.height == other.height
        )


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    client: Rect
    minimized: bool = False


@dataclass(frozen=True)
class ActionSpec:
    """一个可开关的界面动作。引擎不认识具体游戏功能，只消费这份描述。"""

    id: str
    name: str
    description: str
    default_threshold: float = 0.85
    default_cooldown_sec: float = 5.0
    confirm_frames: int = 2

    def __post_init__(self) -> None:
        if _ACTION_ID.fullmatch(self.id) is None:
            raise ValueError(f"动作 id 不合法：{self.id}")
        if not self.name.strip():
            raise ValueError("动作名称不能为空")
        if self.confirm_frames < 2:
            raise ValueError(f"「{self.name}」至少需要连续 2 帧确认")
        if not 0.5 <= self.default_threshold <= 0.99:
            raise ValueError(f"「{self.name}」的默认阈值需在 0.50 到 0.99 之间")
        if not 0.5 <= self.default_cooldown_sec <= 600:
            raise ValueError(f"「{self.name}」的默认冷却需在 0.5 到 600 秒之间")


@dataclass(frozen=True)
class ActionSettings:
    action_id: str
    enabled: bool
    template_path: str
    threshold: float
    cooldown_sec: float


@dataclass(frozen=True)
class RunSettings:
    hwnd: int
    interval_sec: float
    dry_run: bool
    actions: tuple[ActionSettings, ...]
