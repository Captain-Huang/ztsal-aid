"""后台线程把事件放进队列，主线程再取出来更新界面。"""

from __future__ import annotations

import queue
from dataclasses import dataclass
from typing import Protocol

from lastz_assistant.models import EngineEvent


@dataclass(frozen=True)
class EmergencyStop:
    message: str = "F12 紧急停止"


class UiHandler(Protocol):
    def handle_engine_event(self, event: EngineEvent) -> None:
        """在主线程处理一条引擎事件。"""

    def handle_emergency(self, event: EmergencyStop) -> None:
        """在主线程处理紧急停止。"""


def drain_events(
    events: queue.Queue[EngineEvent | EmergencyStop],
    handler: UiHandler,
    *,
    limit: int = 200,
) -> int:
    handled = 0
    while handled < limit:
        try:
            item = events.get_nowait()
        except queue.Empty:
            break
        if isinstance(item, EmergencyStop):
            handler.handle_emergency(item)
        elif isinstance(item, EngineEvent):
            handler.handle_engine_event(item)
        else:
            raise TypeError(f"未知界面消息：{type(item)!r}")
        handled += 1
    return handled
