"""配置驱动的扫描状态机。

每次 step 只处理一帧：截取选定窗口的客户区，对每个启用的动作做模板匹配。
连续确认达到动作要求的帧数后，才在点击前再次确认窗口还在、位置没变、并且是前台。
本模块不导入 Tk，也不知道“联盟帮助”和“断线重连”之外的玩法；那两个动作只是目录里的数据。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

from lastz_assistant.backends.protocol import PointerBackend, WindowBackend
from lastz_assistant.catalog import ACTION_CATALOG, index_catalog
from lastz_assistant.matching import find_best_match, load_template_bgr, score_is_match
from lastz_assistant.models import (
    ActionSettings,
    ActionSpec,
    CaptureError,
    EngineEvent,
    EventKind,
    RunSettings,
    TemplateError,
    WindowInfo,
)
from lastz_assistant.validation import validate_run_settings

_POSITION_TOLERANCE_PX = 8
_SCORE_LOG_INTERVAL_SEC = 2.0


@dataclass
class _ActionState:
    spec: ActionSpec
    settings: ActionSettings
    template: np.ndarray
    streak: int = 0
    last_xy: tuple[int, int] | None = None
    cooldown_until: float = 0.0
    cooldown_logged: bool = False
    last_score_log: float = float("-inf")


class AutomationEngine:
    def __init__(
        self,
        windows: WindowBackend,
        pointer: PointerBackend,
        *,
        clock: Callable[[], float] | None = None,
        catalog: Sequence[ActionSpec] | None = None,
    ) -> None:
        import time

        self._windows = windows
        self._pointer = pointer
        self._clock = clock or time.monotonic
        specs = tuple(catalog) if catalog is not None else ACTION_CATALOG
        self._catalog_order = specs
        self._catalog = index_catalog(specs)
        self._hwnd: int | None = None
        self._dry_run = True
        self._actions: list[_ActionState] = []
        self.stop_reason: str | None = None
        self._background_logged = False

    @property
    def dry_run(self) -> bool:
        return self._dry_run

    @property
    def stopped(self) -> bool:
        return self.stop_reason is not None

    def configure(self, settings: RunSettings) -> None:
        validate_run_settings(settings, self._catalog_order)
        prepared: list[_ActionState] = []
        for action in settings.actions:
            if not action.enabled:
                continue
            spec = self._catalog[action.action_id]
            template = load_template_bgr(action.template_path)
            prepared.append(_ActionState(spec=spec, settings=action, template=template))
        self._hwnd = settings.hwnd
        self._dry_run = settings.dry_run
        self._actions = prepared
        self.stop_reason = None
        self._background_logged = False

    def halt(self, message: str, *, error: bool = True) -> list[EngineEvent]:
        if self.stop_reason is None:
            self.stop_reason = message
        if not error:
            return [EngineEvent(EventKind.STOPPED, message)]
        return [
            EngineEvent(EventKind.ERROR, message),
            EngineEvent(EventKind.STOPPED, "已安全停止"),
        ]

    def step(self, should_abort: Callable[[], bool] | None = None) -> list[EngineEvent]:
        aborted = self._abort_events(should_abort)
        if aborted is not None:
            return aborted
        if self.stop_reason is not None:
            return [EngineEvent(EventKind.STOPPED, self.stop_reason)]
        if self._hwnd is None or not self._actions:
            return self.halt("自动化尚未正确配置")

        window = self._windows.find_window(self._hwnd)
        if window is None:
            return self.halt("目标窗口已消失")
        if window.minimized:
            return self.halt("目标窗口已最小化")
        if window.client.width <= 0 or window.client.height <= 0:
            return self.halt("目标窗口客户区无效")
        if not self._windows.is_foreground(self._hwnd):
            self._clear_streaks()
            if not self._background_logged:
                self._background_logged = True
                return [
                    EngineEvent(
                        EventKind.SKIP_NOT_FOREGROUND,
                        "目标窗口不在前台，本帧不识别、不点击",
                    )
                ]
            return []
        self._background_logged = False

        try:
            frame = self._capture_checked(window)
        except (CaptureError, TemplateError) as exc:
            return self.halt(str(exc))

        now = float(self._clock())
        events: list[EngineEvent] = []
        for action in self._actions:
            aborted = self._abort_events(should_abort)
            if aborted is not None:
                return events + aborted
            events.extend(self._step_action(action, frame, window, now, should_abort))
            if self.stop_reason is not None:
                break
        return events

    def _capture_checked(self, window: WindowInfo) -> np.ndarray:
        assert self._hwnd is not None
        try:
            frame = self._windows.capture_client(self._hwnd)
        except CaptureError:
            raise
        except Exception as exc:
            raise CaptureError(f"截图失败：{exc}") from exc
        if not isinstance(frame, np.ndarray) or frame.size == 0 or frame.ndim < 2:
            raise CaptureError("截图失败：得到空画面")
        height, width = int(frame.shape[0]), int(frame.shape[1])
        if width != window.client.width or height != window.client.height:
            raise CaptureError(
                "截图尺寸与窗口客户区不一致"
                f"（截图 {width}×{height}，客户区 {window.client.width}×{window.client.height}）。"
                "请确认程序以监视器 DPI 感知启动，并重新选择窗口。"
            )
        return frame

    def _step_action(
        self,
        action: _ActionState,
        frame: np.ndarray,
        window: WindowInfo,
        now: float,
        should_abort: Callable[[], bool] | None,
    ) -> list[EngineEvent]:
        if now < action.cooldown_until:
            if action.cooldown_logged:
                return []
            action.cooldown_logged = True
            remaining = action.cooldown_until - now
            return [
                EngineEvent(
                    EventKind.COOLDOWN,
                    f"{action.spec.name} 冷却中，剩余 {remaining:.1f} 秒",
                    action.spec.id,
                )
            ]
        action.cooldown_logged = False

        try:
            hit = find_best_match(frame, action.template)
        except TemplateError as exc:
            return self.halt(f"{action.spec.name}：{exc}")

        if not score_is_match(hit.score, action.settings.threshold):
            action.streak = 0
            action.last_xy = None
            return self._score_notice(action, hit.score, now)

        if action.last_xy is None or _close(action.last_xy, (hit.x, hit.y)):
            action.streak += 1
        else:
            action.streak = 1
        action.last_xy = (hit.x, hit.y)

        if action.streak < action.spec.confirm_frames:
            return [
                EngineEvent(
                    EventKind.CONFIRMING,
                    (
                        f"{action.spec.name} 匹配 {hit.score:.3f}"
                        f"（{action.streak}/{action.spec.confirm_frames}），等待下一帧确认"
                    ),
                    action.spec.id,
                    score=hit.score,
                )
            ]

        aborted = self._abort_events(should_abort)
        if aborted is not None:
            return aborted

        latest = self._windows.find_window(self._hwnd or 0)
        if latest is None:
            return self.halt("点击前目标窗口已消失")
        if latest.minimized:
            return self.halt("点击前目标窗口已最小化")
        if not latest.client.same_geometry(window.client):
            action.streak = 0
            action.last_xy = None
            return [
                EngineEvent(
                    EventKind.LOG,
                    f"{action.spec.name} 点击前窗口位置或大小已变化，已取消本次点击",
                    action.spec.id,
                    score=hit.score,
                )
            ]
        if not self._windows.is_foreground(self._hwnd or 0):
            action.streak = 0
            action.last_xy = None
            return [
                EngineEvent(
                    EventKind.SKIP_NOT_FOREGROUND,
                    f"{action.spec.name} 点击前目标窗口不在前台，已取消点击",
                    action.spec.id,
                    score=hit.score,
                )
            ]

        aborted = self._abort_events(should_abort)
        if aborted is not None:
            return aborted

        center_x, center_y = hit.center
        screen_x = window.client.left + center_x
        screen_y = window.client.top + center_y
        if not window.client.contains(screen_x, screen_y):
            return self.halt(f"{action.spec.name} 点击坐标落在客户区之外")

        action.streak = 0
        action.last_xy = None
        action.cooldown_until = now + action.settings.cooldown_sec
        action.cooldown_logged = False

        if self._dry_run:
            return [
                EngineEvent(
                    EventKind.DRY_RUN,
                    (
                        f"{action.spec.name} 演练：将点击屏幕坐标 ({screen_x}, {screen_y})，"
                        f"分数 {hit.score:.3f}，未实际点击"
                    ),
                    action.spec.id,
                    score=hit.score,
                    screen_x=screen_x,
                    screen_y=screen_y,
                )
            ]

        try:
            self._pointer.click(screen_x, screen_y)
        except Exception as exc:
            if type(exc).__name__ == "FailSafeException":
                return self.halt("鼠标移到屏幕角落，已触发安全停止", error=False)
            return self.halt(f"{action.spec.name} 点击失败：{exc}")
        return [
            EngineEvent(
                EventKind.CLICK,
                (f"{action.spec.name} 点击屏幕坐标 ({screen_x}, {screen_y})，分数 {hit.score:.3f}"),
                action.spec.id,
                score=hit.score,
                screen_x=screen_x,
                screen_y=screen_y,
            )
        ]

    def _score_notice(self, action: _ActionState, score: float, now: float) -> list[EngineEvent]:
        if now - action.last_score_log < _SCORE_LOG_INTERVAL_SEC:
            return []
        action.last_score_log = now
        if not math.isfinite(score):
            message = f"{action.spec.name} 无法计算相似度（画面过于平坦）"
        else:
            message = (
                f"{action.spec.name} 最高分 {score:.3f}，低于阈值 {action.settings.threshold:.2f}"
            )
        return [EngineEvent(EventKind.SCORE, message, action.spec.id, score=score)]

    def _abort_events(self, should_abort: Callable[[], bool] | None) -> list[EngineEvent] | None:
        if should_abort is not None and should_abort():
            return self.halt("已紧急停止", error=False)
        return None

    def _clear_streaks(self) -> None:
        for action in self._actions:
            action.streak = 0
            action.last_xy = None


def _close(previous: tuple[int, int], current: tuple[int, int]) -> bool:
    return (
        abs(previous[0] - current[0]) <= _POSITION_TOLERANCE_PX
        and abs(previous[1] - current[1]) <= _POSITION_TOLERANCE_PX
    )
