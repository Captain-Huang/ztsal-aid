"""启动入口。DPI 感知必须先于 Tk 和任何窗口坐标调用。"""

from __future__ import annotations

import sys


def main() -> int:
    from lastz_assistant.dpi import enable_dpi_awareness

    enable_dpi_awareness()
    if sys.platform != "win32":
        print(
            "Last Z 助手只能在 Windows 上操作游戏窗口。当前系统已拒绝启动。",
            file=sys.stderr,
        )
        return 2
    from lastz_assistant.gui import launch

    launch()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
