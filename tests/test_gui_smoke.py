from __future__ import annotations

import os
import threading
import time
import tkinter as tk
from collections.abc import Callable
from pathlib import Path

import pytest

from lastz_assistant.catalog import ACTION_CATALOG
from lastz_assistant.gui import AssistantApp
from lastz_assistant.settings_store import load_settings
from tests.fakes import stage


class FakeHotkey:
    def __init__(self, fail_message: str | None = None) -> None:
        self.fail_message = fail_message
        self.start_count = 0
        self.stop_count = 0
        self.callback: Callable[[], None] | None = None

    def start(self, on_trigger: Callable[[], None]) -> str | None:
        self.start_count += 1
        self.callback = on_trigger
        return self.fail_message

    def stop(self) -> None:
        self.stop_count += 1


@pytest.fixture
def tk_root():
    if not os.environ.get("DISPLAY"):
        pytest.skip("没有图形界面")
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk 不可用：{exc}")
    root.withdraw()
    yield root
    try:
        if root.winfo_exists():
            root.destroy()
    except tk.TclError:
        pass


def _pump(root: tk.Tk, predicate: Callable[[], bool], timeout: float = 4.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if predicate():
            return True
        time.sleep(0.02)
    return False


def _only(app: AssistantApp, action_id: str) -> None:
    for current_id, form in app.forms.items():
        form.enabled.set(current_id == action_id)


def _app(root: tk.Tk, scene, hotkey: FakeHotkey, settings_path: Path) -> AssistantApp:
    return AssistantApp(
        root,
        windows=scene.windows,
        pointer=scene.pointer,
        hotkey=hotkey,
        settings_path=settings_path,
        dpi_mode="not-windows",
        interactive=False,
    )


def test_gui_dry_run_then_real_click_and_close_releases_worker(
    tmp_path: Path, tk_root: tk.Tk
) -> None:
    scene = stage(tmp_path, configure=False, title="Last Z")
    hotkey = FakeHotkey()
    app = _app(tk_root, scene, hotkey, tmp_path / "settings.json")
    app.window_combo.current(0)
    _only(app, "alliance_help")
    app.forms["alliance_help"].path.set(str(scene.template_path))
    app.interval_var.set("0.2")
    app.dry_run_var.set(True)

    app.start_button.invoke()
    assert _pump(tk_root, lambda: "未实际点击" in app.log_text.get("1.0", "end"))
    assert scene.pointer.clicks == []
    assert hotkey.start_count == 1

    app.stop_button.invoke()
    assert app._worker is None

    app.dry_run_var.set(False)
    app.start_button.invoke()
    assert _pump(tk_root, lambda: len(scene.pointer.clicks) == 1)
    assert scene.pointer.clicks == [scene.click_point]

    app.close()
    assert "lastz-automation" not in [thread.name for thread in threading.enumerate()]
    assert hotkey.stop_count >= 1
    loaded = load_settings(tmp_path / "settings.json", ACTION_CATALOG)
    assert loaded["dry_run"] is False
    assert loaded["actions"]["alliance_help"]["template_path"] == str(scene.template_path)
    assert loaded["actions"]["claim_resources"]["enabled"] is False
    assert loaded["window_title"] == "Last Z"


def test_gui_reports_template_and_hotkey_errors_without_a_worker(
    tmp_path: Path, tk_root: tk.Tk
) -> None:
    scene = stage(tmp_path, configure=False, seed=8)
    app = _app(tk_root, scene, FakeHotkey(), tmp_path / "settings.json")
    app.start_button.invoke()
    assert "请选择目标窗口" in app.log_text.get("1.0", "end")
    assert app._worker is None

    app.window_combo.current(0)
    _only(app, "alliance_help")
    app.forms["alliance_help"].path.set(str(tmp_path / "missing.png"))
    app.start_button.invoke()
    assert "不存在" in app.log_text.get("1.0", "end")
    assert app._worker is None

    app.forms["alliance_help"].path.set(str(scene.template_path))
    broken = FakeHotkey(fail_message="无法注册 Ctrl+F12")
    app._hotkey = broken
    app.start_button.invoke()
    assert "无法注册 Ctrl+F12" in app.log_text.get("1.0", "end")
    assert app._worker is None
    assert broken.stop_count >= 1
    app.close()


def test_gui_shows_capture_failure_and_stops(tmp_path: Path, tk_root: tk.Tk) -> None:
    scene = stage(tmp_path, configure=False, seed=15)
    scene.windows.fail_capture = True
    hotkey = FakeHotkey()
    app = _app(tk_root, scene, hotkey, tmp_path / "settings.json")
    app.window_combo.current(0)
    _only(app, "alliance_help")
    app.forms["alliance_help"].path.set(str(scene.template_path))
    app.interval_var.set("0.2")
    app.start_button.invoke()
    assert _pump(tk_root, lambda: app._status_var.get().startswith("错误：截图失败"))
    assert scene.pointer.clicks == []
    assert app._worker is None
    assert hotkey.stop_count >= 1
    assert "lastz-automation" not in [thread.name for thread in threading.enumerate()]
    app.close()


def test_emergency_stop_from_another_thread_does_not_deadlock(
    tmp_path: Path, tk_root: tk.Tk
) -> None:
    scene = stage(tmp_path, configure=False, seed=9)
    hotkey = FakeHotkey()
    app = _app(tk_root, scene, hotkey, tmp_path / "settings.json")
    app.window_combo.current(0)
    _only(app, "alliance_help")
    app.forms["alliance_help"].path.set(str(scene.template_path))
    app.interval_var.set("0.2")
    app.start_button.invoke()
    assert _pump(tk_root, lambda: "运行中" in app.log_text.get("1.0", "end"))

    caller = threading.Thread(target=app._on_emergency, name="fake-f12")
    caller.start()
    caller.join(timeout=1)
    assert not caller.is_alive()
    assert _pump(tk_root, lambda: app._status_var.get() == "已紧急停止")
    assert app._worker is None
    assert "lastz-automation" not in [thread.name for thread in threading.enumerate()]
    app.close()
