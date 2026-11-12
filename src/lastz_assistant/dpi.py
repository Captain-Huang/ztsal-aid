"""让截图坐标和 Win32 客户区坐标使用同一套物理像素。"""

from __future__ import annotations

import sys

_mode: str | None = None


def enable_dpi_awareness() -> str:
    """在创建 Tk 窗口或调用 Win32 / MSS 之前执行一次。

    未感知 DPI 时，窗口矩形可能是逻辑像素，而屏幕截图是物理像素，
    模板位置会偏到别的控件甚至别的程序上。
    """

    global _mode
    if _mode is not None:
        return _mode
    if sys.platform != "win32":
        _mode = "not-windows"
        return _mode
    _mode = _enable_windows_dpi()
    return _mode


def _enable_windows_dpi() -> str:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = (HANDLE)-4
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return "per-monitor-v2"
    except (AttributeError, OSError):
        pass
    try:
        # PROCESS_PER_MONITOR_DPI_AWARE = 2
        ctypes.windll.shcore.SetProcessDpiAwareness.argtypes = [ctypes.c_int]
        ctypes.windll.shcore.SetProcessDpiAwareness.restype = ctypes.HRESULT
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:
            return "per-monitor"
    except (AttributeError, OSError):
        pass
    try:
        user32.SetProcessDPIAware.restype = wintypes.BOOL
        if user32.SetProcessDPIAware():
            return "system"
    except (AttributeError, OSError):
        pass
    return "unaware"
