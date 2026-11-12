"""可在 Linux 上运行的窗口、截图和鼠标替身。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np

from lastz_assistant.engine import AutomationEngine
from lastz_assistant.models import (
    ActionSettings,
    ActionSpec,
    CaptureError,
    Rect,
    RunSettings,
    WindowInfo,
)


class ManualClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakePointer:
    def __init__(self) -> None:
        self.clicks: list[tuple[int, int]] = []

    def click(self, x: int, y: int) -> None:
        self.clicks.append((int(x), int(y)))


class FakeWindows:
    def __init__(self) -> None:
        self.windows: dict[int, WindowInfo] = {}
        self.images: dict[int, np.ndarray] = {}
        self.foreground_hwnd: int | None = None
        self.capture_calls = 0
        self.successful_captures = 0
        self.fail_capture = False
        self.move_on_success: tuple[int, int, int] | None = None
        self.drop_on_success: int | None = None
        self.clear_foreground_on_success: int | None = None
        self.after_success: Callable[[FakeWindows], None] | None = None

    def list_windows(self) -> list[WindowInfo]:
        return list(self.windows.values())

    def find_window(self, hwnd: int) -> WindowInfo | None:
        return self.windows.get(int(hwnd))

    def is_foreground(self, hwnd: int) -> bool:
        return self.foreground_hwnd == int(hwnd)

    def capture_client(self, hwnd: int) -> np.ndarray:
        self.capture_calls += 1
        if self.fail_capture:
            raise CaptureError("截图失败：模拟设备无画面")
        info = self.windows.get(int(hwnd))
        image = self.images.get(int(hwnd))
        if info is None or image is None:
            raise CaptureError("截图失败：窗口不存在")
        self.successful_captures += 1
        if self.move_on_success is not None and self.successful_captures >= self.move_on_success[0]:
            _dx = self.move_on_success[1]
            _dy = self.move_on_success[2]
            self._shift(int(hwnd), _dx, _dy)
            self.move_on_success = None
        if self.drop_on_success is not None and self.successful_captures >= self.drop_on_success:
            self.windows.pop(int(hwnd), None)
            self.drop_on_success = None
        if (
            self.clear_foreground_on_success is not None
            and self.successful_captures >= self.clear_foreground_on_success
        ):
            self.foreground_hwnd = None
            self.clear_foreground_on_success = None
        if self.after_success is not None:
            self.after_success(self)
        return image

    def _shift(self, hwnd: int, dx: int, dy: int) -> None:
        window = self.windows[hwnd]
        client = window.client
        self.windows[hwnd] = WindowInfo(
            hwnd=window.hwnd,
            title=window.title,
            client=Rect(client.left + dx, client.top + dy, client.width, client.height),
            minimized=window.minimized,
        )


def unique_patch(width: int, height: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)


def blank(width: int, height: int, color: tuple[int, int, int] = (24, 26, 28)) -> np.ndarray:
    image = np.empty((height, width, 3), dtype=np.uint8)
    image[:] = color
    return image


def paint(canvas: np.ndarray, patch: np.ndarray, x: int, y: int) -> None:
    height, width = patch.shape[:2]
    canvas[y : y + height, x : x + width] = patch


def write_png(path: Path, image: np.ndarray) -> None:
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError(f"无法编码 PNG：{path}")
    path.write_bytes(encoded.tobytes())


class Scene:
    def __init__(
        self,
        *,
        engine: AutomationEngine,
        windows: FakeWindows,
        pointer: FakePointer,
        clock: ManualClock,
        hwnd: int,
        origin: tuple[int, int],
        patch_origin: tuple[int, int],
        patch_size: tuple[int, int],
        template: np.ndarray,
        template_path: Path,
        spec: ActionSpec,
    ) -> None:
        self.engine = engine
        self.windows = windows
        self.pointer = pointer
        self.clock = clock
        self.hwnd = hwnd
        self.origin = origin
        self.patch_origin = patch_origin
        self.patch_size = patch_size
        self.template = template
        self.template_path = template_path
        self.spec = spec

    @property
    def click_point(self) -> tuple[int, int]:
        screen_x = self.origin[0] + self.patch_origin[0] + self.patch_size[0] // 2
        screen_y = self.origin[1] + self.patch_origin[1] + self.patch_size[1] // 2
        return screen_x, screen_y

    def show_patch_at(self, x: int, y: int) -> None:
        current = self.windows.images[self.hwnd]
        image = blank(current.shape[1], current.shape[0])
        paint(image, self.template, x, y)
        self.windows.images[self.hwnd] = image
        self.patch_origin = (x, y)


def stage(
    directory: Path,
    *,
    seed: int = 1,
    origin: tuple[int, int] = (100, 200),
    patch_at: tuple[int, int] = (10, 20),
    patch_size: tuple[int, int] = (20, 16),
    canvas: tuple[int, int] = (180, 140),
    foreground: bool = True,
    dry_run: bool = False,
    threshold: float = 0.85,
    cooldown: float = 5.0,
    hwnd: int = 1001,
    spec: ActionSpec | None = None,
    configure: bool = True,
    title: str = "Last Z",
) -> Scene:
    spec = spec or ActionSpec(
        id="alliance_help",
        name="联盟帮助",
        description="测试用动作",
        default_threshold=threshold,
        default_cooldown_sec=cooldown,
        confirm_frames=2,
    )
    patch = unique_patch(patch_size[0], patch_size[1], seed)
    image = blank(canvas[0], canvas[1])
    paint(image, patch, patch_at[0], patch_at[1])
    path = directory / f"{spec.id}-{seed}.png"
    write_png(path, patch)
    windows = FakeWindows()
    windows.windows[hwnd] = WindowInfo(
        hwnd=hwnd,
        title=title,
        client=Rect(origin[0], origin[1], canvas[0], canvas[1]),
    )
    windows.images[hwnd] = image
    windows.foreground_hwnd = hwnd if foreground else None
    pointer = FakePointer()
    clock = ManualClock()
    engine = AutomationEngine(windows, pointer, clock=clock, catalog=(spec,))
    if configure:
        engine.configure(
            RunSettings(
                hwnd=hwnd,
                interval_sec=0.5,
                dry_run=dry_run,
                actions=(
                    ActionSettings(
                        action_id=spec.id,
                        enabled=True,
                        template_path=str(path),
                        threshold=threshold,
                        cooldown_sec=cooldown,
                    ),
                ),
            )
        )
    return Scene(
        engine=engine,
        windows=windows,
        pointer=pointer,
        clock=clock,
        hwnd=hwnd,
        origin=origin,
        patch_origin=patch_at,
        patch_size=patch_size,
        template=patch,
        template_path=path,
        spec=spec,
    )
