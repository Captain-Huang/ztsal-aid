"""按当前系统创建窗口、鼠标和热键实现。"""

from __future__ import annotations

import sys

from lastz_assistant.backends.protocol import HotkeyBackend, PointerBackend, WindowBackend


def create_platform() -> tuple[WindowBackend, PointerBackend, HotkeyBackend]:
    if sys.platform != "win32":
        raise RuntimeError("需要在 Windows 上运行 Last Z 助手。")
    try:
        from lastz_assistant.backends.windows import (
            PyAutoGuiPointer,
            WindowsHotkeyService,
            WindowsWindowBackend,
        )
    except ImportError as exc:
        raise RuntimeError("缺少 Windows 依赖。请确认已安装 pywin32、mss 和 PyAutoGUI。") from exc
    return WindowsWindowBackend(), PyAutoGuiPointer(), WindowsHotkeyService()
