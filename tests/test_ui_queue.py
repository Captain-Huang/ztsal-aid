from __future__ import annotations

import queue

import pytest

from lastz_assistant.models import EngineEvent, EventKind
from lastz_assistant.ui_queue import EmergencyStop, drain_events


class Recorder:
    def __init__(self) -> None:
        self.events: list[object] = []

    def handle_engine_event(self, event: EngineEvent) -> None:
        self.events.append(event)

    def handle_emergency(self, event: EmergencyStop) -> None:
        self.events.append(event)


def test_drain_respects_limit_and_dispatches_both_message_types() -> None:
    events: queue.Queue[EngineEvent | EmergencyStop] = queue.Queue()
    events.put(EngineEvent(EventKind.LOG, "一条"))
    events.put(EmergencyStop("F12 紧急停止"))
    events.put(EngineEvent(EventKind.CLICK, "点了"))
    recorder = Recorder()
    assert drain_events(events, recorder, limit=2) == 2
    assert drain_events(events, recorder, limit=5) == 1
    assert isinstance(recorder.events[0], EngineEvent)
    assert isinstance(recorder.events[1], EmergencyStop)
    assert isinstance(recorder.events[2], EngineEvent)


def test_unknown_queue_item_is_rejected() -> None:
    events: queue.Queue[object] = queue.Queue()
    events.put("nope")
    with pytest.raises(TypeError, match="未知界面消息"):
        drain_events(events, Recorder())  # type: ignore[arg-type]
