"""窗口、截图和鼠标的最小接口。测试用假实现，Windows 上用真实现。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

import numpy as np

from lastz_assistant.models import WindowInfo


class WindowBackend(Protocol):
    def list_windows(self) -> list[WindowInfo]:
        """列出可选的顶层窗口。"""

    def find_window(self, hwnd: int) -> WindowInfo | None:
        """窗口已关闭或不再可见时返回 None。"""

    def is_foreground(self, hwnd: int) -> bool:
        """该窗口是否为当前前台窗口。"""

    def capture_client(self, hwnd: int) -> np.ndarray:
        """截取客户区可见像素，返回 BGR uint8 数组。失败时抛出 CaptureError。"""


class PointerBackend(Protocol):
    def click(self, x: int, y: int) -> None:
        """在屏幕坐标点击一次左键。调用方必须先确认坐标落在目标窗口内。"""


class HotkeyBackend(Protocol):
    def start(self, on_trigger: Callable[[], None]) -> str | None:
        """注册紧急停止热键。失败时返回给用户看的原因，成功返回 None。

        on_trigger 会在热键线程调用，必须尽快返回，不能操作 Tk，也不能反过来停止热键线程。
        """

    def stop(self) -> None:
        """释放热键并等线程退出。可重复调用。"""
