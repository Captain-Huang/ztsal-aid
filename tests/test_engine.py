from __future__ import annotations

from pathlib import Path

import pytest

from lastz_assistant.catalog import ACTION_CATALOG
from lastz_assistant.engine import AutomationEngine
from lastz_assistant.models import (
    ActionSettings,
    ActionSpec,
    EngineEvent,
    EventKind,
    Rect,
    RunSettings,
    TemplateError,
    WindowInfo,
)
from tests.fakes import (
    FakePointer,
    FakeWindows,
    ManualClock,
    blank,
    paint,
    stage,
    unique_patch,
    write_png,
)


def _kinds(events: list[EngineEvent], *wanted: EventKind) -> list[EventKind]:
    return [event.kind for event in events if event.kind in wanted]


def test_two_consecutive_frames_are_required_before_click(tmp_path: Path) -> None:
    scene = stage(tmp_path)
    first = scene.engine.step()
    assert _kinds(first, EventKind.CONFIRMING, EventKind.CLICK) == [EventKind.CONFIRMING]
    assert scene.pointer.clicks == []
    second = scene.engine.step()
    assert _kinds(second, EventKind.CLICK) == [EventKind.CLICK]
    assert scene.pointer.clicks == [scene.click_point]
    assert second[0].screen_x == scene.click_point[0]
    assert second[0].screen_y == scene.click_point[1]


def test_a_missed_frame_resets_the_streak(tmp_path: Path) -> None:
    scene = stage(tmp_path)
    scene.engine.step()
    scene.windows.images[scene.hwnd] = blank(180, 140)
    scene.engine.step()
    scene.show_patch_at(*scene.patch_origin)
    scene.engine.step()
    assert scene.pointer.clicks == []
    scene.engine.step()
    assert scene.pointer.clicks == [scene.click_point]


def test_far_position_jump_does_not_count_as_the_second_frame(tmp_path: Path) -> None:
    scene = stage(tmp_path)
    scene.engine.step()
    scene.show_patch_at(40, 20)
    scene.engine.step()
    assert scene.pointer.clicks == []
    scene.engine.step()
    assert scene.pointer.clicks == [scene.click_point]


def test_small_position_jitter_still_confirms(tmp_path: Path) -> None:
    scene = stage(tmp_path)
    scene.engine.step()
    scene.show_patch_at(12, 21)
    scene.engine.step()
    assert len(scene.pointer.clicks) == 1


def test_cooldown_is_independent_per_action(tmp_path: Path) -> None:
    by_id = {spec.id: spec for spec in ACTION_CATALOG}
    help_spec = by_id["alliance_help"]
    claim_spec = by_id["claim_resources"]
    canvas = blank(220, 160)
    help_patch = unique_patch(20, 16, seed=11)
    claim_patch = unique_patch(22, 18, seed=12)
    paint(canvas, help_patch, 10, 20)
    paint(canvas, claim_patch, 80, 40)
    help_path = tmp_path / "help.png"
    claim_path = tmp_path / "claim.png"
    write_png(help_path, help_patch)
    write_png(claim_path, claim_patch)
    windows = FakeWindows()
    hwnd = 7
    windows.windows[hwnd] = WindowInfo(hwnd, "Last Z", Rect(100, 200, 220, 160))
    windows.images[hwnd] = canvas
    windows.foreground_hwnd = hwnd
    pointer = FakePointer()
    clock = ManualClock()
    engine = AutomationEngine(windows, pointer, clock=clock, catalog=ACTION_CATALOG)
    engine.configure(
        RunSettings(
            hwnd=hwnd,
            interval_sec=0.5,
            dry_run=False,
            actions=(
                ActionSettings("alliance_help", True, str(help_path), 0.85, 5),
                ActionSettings("claim_resources", True, str(claim_path), 0.85, 30),
            ),
        )
    )
    engine.step()
    engine.step()
    assert pointer.clicks == [(100 + 10 + 10, 200 + 20 + 8), (100 + 80 + 11, 200 + 40 + 9)]
    clock.advance(5)
    engine.step()
    engine.step()
    assert len(pointer.clicks) == 3
    assert pointer.clicks[-1] == (120, 228)
    assert help_spec.id == "alliance_help"
    assert claim_spec.default_cooldown_sec == 3


def test_cooldown_blocks_until_it_expires(tmp_path: Path) -> None:
    scene = stage(tmp_path, cooldown=5)
    scene.engine.step()
    scene.engine.step()
    assert len(scene.pointer.clicks) == 1
    scene.clock.advance(4.9)
    during = scene.engine.step()
    assert _kinds(during, EventKind.COOLDOWN, EventKind.CLICK) == [EventKind.COOLDOWN]
    scene.engine.step()
    assert len(scene.pointer.clicks) == 1
    scene.clock.advance(0.1)
    scene.engine.step()
    assert len(scene.pointer.clicks) == 1
    scene.engine.step()
    assert len(scene.pointer.clicks) == 2


def test_dry_run_logs_the_point_and_never_clicks(tmp_path: Path) -> None:
    scene = stage(tmp_path, dry_run=True)

    def forbid_click(x: int, y: int) -> None:
        raise AssertionError(f"演练模式不应点击 {(x, y)}")

    scene.pointer.click = forbid_click  # type: ignore[method-assign]
    assert _kinds(scene.engine.step(), EventKind.DRY_RUN) == []
    dry = scene.engine.step()
    assert dry[0].kind == EventKind.DRY_RUN
    assert (dry[0].screen_x, dry[0].screen_y) == scene.click_point
    assert "未实际点击" in dry[0].message
    assert _kinds(scene.engine.step(), EventKind.COOLDOWN, EventKind.DRY_RUN) == [
        EventKind.COOLDOWN
    ]
    scene.clock.advance(5)
    scene.engine.step()
    again = scene.engine.step()
    assert again[0].kind == EventKind.DRY_RUN


def test_background_window_is_not_captured_or_clicked(tmp_path: Path) -> None:
    scene = stage(tmp_path, foreground=False)
    first = scene.engine.step()
    second = scene.engine.step()
    assert scene.windows.capture_calls == 0
    assert scene.pointer.clicks == []
    assert first[0].kind == EventKind.SKIP_NOT_FOREGROUND
    assert second == []
    scene.windows.foreground_hwnd = scene.hwnd
    scene.engine.step()
    assert scene.pointer.clicks == []
    scene.engine.step()
    assert scene.pointer.clicks == [scene.click_point]


def test_losing_foreground_right_before_click_cancels(tmp_path: Path) -> None:
    scene = stage(tmp_path)
    scene.windows.clear_foreground_on_success = 2
    scene.engine.step()
    events = scene.engine.step()
    assert scene.pointer.clicks == []
    assert any(
        "点击前" in event.message and event.kind == EventKind.SKIP_NOT_FOREGROUND
        for event in events
    )
    assert not scene.engine.stopped
    scene.windows.foreground_hwnd = scene.hwnd
    scene.engine.step()
    scene.engine.step()
    assert scene.pointer.clicks == [scene.click_point]


def test_window_move_between_capture_and_click_cancels_that_click(tmp_path: Path) -> None:
    scene = stage(tmp_path)
    scene.windows.move_on_success = (2, 40, 0)
    scene.engine.step()
    events = scene.engine.step()
    assert scene.pointer.clicks == []
    assert any("已变化" in event.message for event in events)
    scene.engine.step()
    scene.engine.step()
    assert scene.pointer.clicks == [(scene.click_point[0] + 40, scene.click_point[1])]


def test_window_disappearing_before_click_stops(tmp_path: Path) -> None:
    scene = stage(tmp_path)
    scene.windows.drop_on_success = 2
    scene.engine.step()
    events = scene.engine.step()
    assert scene.pointer.clicks == []
    assert scene.engine.stopped
    assert any(
        event.kind == EventKind.ERROR and "点击前目标窗口已消失" in event.message
        for event in events
    )
    scene.engine.step()
    assert scene.pointer.clicks == []


def test_missing_window_minimized_window_and_capture_failure_stop(tmp_path: Path) -> None:
    missing = stage(tmp_path, seed=21)
    missing.windows.windows.clear()
    events = missing.engine.step()
    assert any(event.kind == EventKind.ERROR and "消失" in event.message for event in events)
    assert missing.pointer.clicks == []
    assert missing.engine.stopped

    minimized = stage(tmp_path, seed=22)
    current = minimized.windows.windows[minimized.hwnd]
    minimized.windows.windows[minimized.hwnd] = WindowInfo(
        current.hwnd, current.title, current.client, minimized=True
    )
    events = minimized.engine.step()
    assert minimized.windows.capture_calls == 0
    assert any("最小化" in event.message for event in events)
    assert minimized.engine.stopped

    failed = stage(tmp_path, seed=23)
    failed.windows.fail_capture = True
    events = failed.engine.step()
    assert any(event.kind == EventKind.ERROR and "截图失败" in event.message for event in events)
    assert failed.pointer.clicks == []
    failed.engine.step()
    assert failed.pointer.clicks == []


def test_screenshot_size_mismatch_stops(tmp_path: Path) -> None:
    scene = stage(tmp_path, seed=24)
    scene.windows.images[scene.hwnd] = blank(30, 20)
    events = scene.engine.step()
    assert any("不一致" in event.message for event in events)
    assert scene.pointer.clicks == []
    assert scene.engine.stopped


def test_invalid_template_stops_before_any_click(tmp_path: Path) -> None:
    scene = stage(tmp_path, configure=False)
    missing = RunSettings(
        hwnd=scene.hwnd,
        interval_sec=0.5,
        dry_run=False,
        actions=(ActionSettings(scene.spec.id, True, str(tmp_path / "nope.png"), 0.85, 5),),
    )
    with pytest.raises(TemplateError, match="不存在"):
        scene.engine.configure(missing)
    assert scene.pointer.clicks == []

    corrupt = tmp_path / "corrupt.png"
    corrupt.write_bytes(b"not-a-png")
    with pytest.raises(TemplateError):
        scene.engine.configure(
            RunSettings(
                hwnd=scene.hwnd,
                interval_sec=0.5,
                dry_run=False,
                actions=(ActionSettings(scene.spec.id, True, str(corrupt), 0.85, 5),),
            )
        )

    oversized = unique_patch(80, 80, seed=5)
    oversized_path = tmp_path / "big.png"
    write_png(oversized_path, oversized)
    small = stage(tmp_path, seed=25, canvas=(40, 40), patch_size=(12, 12), patch_at=(2, 2))
    small.engine.configure(
        RunSettings(
            hwnd=small.hwnd,
            interval_sec=0.5,
            dry_run=False,
            actions=(ActionSettings(small.spec.id, True, str(oversized_path), 0.85, 5),),
        )
    )
    events = small.engine.step()
    assert small.engine.stopped
    assert small.pointer.clicks == []
    assert any("大于" in event.message for event in events)


def test_disabled_action_with_empty_template_is_ignored(tmp_path: Path) -> None:
    scene = stage(tmp_path, configure=False)
    engine = AutomationEngine(
        scene.windows,
        scene.pointer,
        clock=scene.clock,
        catalog=ACTION_CATALOG,
    )
    engine.configure(
        RunSettings(
            hwnd=scene.hwnd,
            interval_sec=0.5,
            dry_run=False,
            actions=(
                ActionSettings("alliance_help", True, str(scene.template_path), 0.85, 5),
                ActionSettings("claim_resources", False, "", 0.85, 3),
            ),
        )
    )
    engine.step()
    engine.step()
    assert scene.pointer.clicks == [scene.click_point]


def test_low_score_does_not_click_and_reports_periodically(tmp_path: Path) -> None:
    scene = stage(tmp_path)
    scene.windows.images[scene.hwnd] = blank(180, 140)
    first = scene.engine.step()
    assert scene.pointer.clicks == []
    assert first[0].kind == EventKind.SCORE
    assert scene.engine.step() == []
    scene.clock.advance(2)
    assert scene.engine.step()[0].kind == EventKind.SCORE


def test_emergency_abort_after_capture_does_not_click(tmp_path: Path) -> None:
    scene = stage(tmp_path)
    flag = {"stop": False}

    def arm(windows: FakeWindows) -> None:
        if windows.successful_captures >= 2:
            flag["stop"] = True

    scene.windows.after_success = arm
    scene.engine.step(should_abort=lambda: flag["stop"])
    events = scene.engine.step(should_abort=lambda: flag["stop"])
    assert scene.pointer.clicks == []
    assert scene.engine.stopped
    assert events[0].kind == EventKind.STOPPED
    assert "紧急" in events[0].message


def test_pointer_failure_and_failsafe_stop_without_a_successful_click(tmp_path: Path) -> None:
    class FailSafeException(Exception):
        pass

    scene = stage(tmp_path, seed=31)
    scene.engine.step()

    def explode(x: int, y: int) -> None:
        raise RuntimeError("device busy")

    scene.pointer.click = explode  # type: ignore[method-assign]
    events = scene.engine.step()
    assert scene.engine.stopped
    assert any(event.kind == EventKind.ERROR and "点击失败" in event.message for event in events)

    other = stage(tmp_path, seed=32)
    other.engine.step()

    def corner(x: int, y: int) -> None:
        raise FailSafeException("corner")

    other.pointer.click = corner  # type: ignore[method-assign]
    events = other.engine.step()
    assert other.pointer.clicks == []
    assert other.engine.stopped
    assert events[0].kind == EventKind.STOPPED
    assert "角落" in events[0].message


def test_custom_catalog_action_uses_the_same_engine(tmp_path: Path) -> None:
    spec = ActionSpec(
        id="extra_button",
        name="额外按钮",
        description="用来证明引擎不写死两个游戏功能",
        confirm_frames=3,
        default_threshold=0.9,
        default_cooldown_sec=4,
    )
    scene = stage(tmp_path, spec=spec, seed=41)
    scene.engine.step()
    scene.engine.step()
    assert scene.pointer.clicks == []
    scene.engine.step()
    assert scene.pointer.clicks == [scene.click_point]


def test_unconfigured_engine_stops(tmp_path: Path) -> None:
    scene = stage(tmp_path, configure=False)
    events = scene.engine.step()
    assert scene.engine.stopped
    assert any(event.kind == EventKind.ERROR for event in events)
    assert scene.pointer.clicks == []
