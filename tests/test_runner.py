from __future__ import annotations

import inspect
import queue
import threading
from pathlib import Path

from lastz_assistant import engine as engine_module
from lastz_assistant import runner as runner_module
from lastz_assistant.models import EventKind
from lastz_assistant.runner import run_until_stopped
from lastz_assistant.ui_queue import drain_events
from tests.fakes import stage


def test_runner_and_engine_do_not_touch_tk() -> None:
    assert "tkinter" not in inspect.getsource(runner_module)
    assert "tkinter" not in inspect.getsource(engine_module)


def test_pause_delays_clicks_until_resumed(tmp_path: Path) -> None:
    scene = stage(tmp_path)
    stop = threading.Event()
    pause = threading.Event()
    pause.set()
    events = []

    def wait(seconds: float) -> None:
        if pause.is_set():
            pause.clear()
            return
        if scene.pointer.clicks:
            stop.set()

    run_until_stopped(
        scene.engine,
        stop,
        pause,
        0.2,
        events.append,
        wait=wait,
    )
    assert any(event.message == "已暂停" for event in events)
    assert scene.pointer.clicks == [scene.click_point]
    assert events[-1].kind == EventKind.STOPPED


def test_stop_before_start_does_not_click(tmp_path: Path) -> None:
    scene = stage(tmp_path)
    stop = threading.Event()
    stop.set()
    events = []
    run_until_stopped(scene.engine, stop, threading.Event(), 0.2, events.append)
    assert scene.pointer.clicks == []
    assert events[-1].kind == EventKind.STOPPED


def test_capture_failure_emitted_from_worker_is_handled_on_the_drain_thread(tmp_path: Path) -> None:
    scene = stage(tmp_path)
    scene.windows.fail_capture = True
    messages: queue.Queue = queue.Queue()
    worker = threading.Thread(
        target=run_until_stopped,
        args=(scene.engine, threading.Event(), threading.Event(), 0.2, messages.put),
        name="lastz-automation",
    )
    worker.start()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert worker.ident is not None
    assert worker.ident != threading.get_ident()

    seen: list[int] = []

    class Handler:
        def handle_engine_event(self, event: object) -> None:
            seen.append(threading.get_ident())

        def handle_emergency(self, event: object) -> None:
            seen.append(threading.get_ident())

    handled = drain_events(messages, Handler())
    assert handled >= 1
    assert seen
    assert all(item == threading.get_ident() for item in seen)
    assert scene.pointer.clicks == []
    assert scene.engine.stopped


def test_invalid_interval_stops_without_clicking(tmp_path: Path) -> None:
    scene = stage(tmp_path)
    events = []
    run_until_stopped(scene.engine, threading.Event(), threading.Event(), 0.05, events.append)
    assert scene.pointer.clicks == []
    assert any(event.kind == EventKind.ERROR for event in events)
    assert scene.engine.stopped
