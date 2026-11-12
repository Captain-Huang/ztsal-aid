"""在调用方提供的线程里跑扫描循环。只通过 emit 交出事件，不接触界面控件。"""

from __future__ import annotations

import threading
from collections.abc import Callable

from lastz_assistant.engine import AutomationEngine
from lastz_assistant.models import EngineEvent, EventKind


def run_until_stopped(
    engine: AutomationEngine,
    stop_event: threading.Event,
    pause_event: threading.Event,
    interval_sec: float,
    emit: Callable[[EngineEvent], None],
    *,
    wait: Callable[[float], None] | None = None,
) -> None:
    if interval_sec < 0.2 or interval_sec > 30:
        for event in engine.halt("扫描间隔需在 0.2 到 30 秒之间"):
            emit(event)
        return

    def sleep(seconds: float) -> None:
        if wait is not None:
            wait(seconds)
            return
        stop_event.wait(timeout=max(0.0, seconds))

    announced: str | None = None
    while not stop_event.is_set():
        if pause_event.is_set():
            if announced != "paused":
                emit(EngineEvent(EventKind.LOG, "已暂停"))
                announced = "paused"
            sleep(0.1)
            continue
        if announced != "running":
            text = "运行中（演练，不会点击）" if engine.dry_run else "运行中"
            emit(EngineEvent(EventKind.LOG, text))
            announced = "running"
        if stop_event.is_set():
            break
        try:
            events = engine.step(should_abort=stop_event.is_set)
        except Exception as exc:
            events = engine.halt(f"未预期错误：{exc}")
        for event in events:
            emit(event)
        if engine.stopped or stop_event.is_set():
            break
        sleep(interval_sec)
    if not engine.stopped:
        emit(EngineEvent(EventKind.STOPPED, "已停止"))
