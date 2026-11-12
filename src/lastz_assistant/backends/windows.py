"""Windows 上的窗口枚举、客户区截图、前台判断、模拟点击和 F12 热键。

只使用屏幕上已经可见的像素和普通鼠标点击。不读取游戏进程内存，不注入，不抓包。
"""

from __future__ import annotations

import ctypes
import os
import threading
from collections.abc import Callable
from ctypes import wintypes

import cv2
import mss
import numpy as np
import win32con
import win32gui
import win32process

from lastz_assistant.models import CaptureError, Rect, WindowInfo

_HOTKEY_ID = 1
_VK_F12 = 0x7B
_MOD_NOREPEAT = 0x4000
_WM_HOTKEY = 0x0312
_PM_REMOVE = 0x0001
_DWMWA_CLOAKED = 14


class WindowsWindowBackend:
    def list_windows(self) -> list[WindowInfo]:
        found: list[WindowInfo] = []
        current_pid = os.getpid()

        def callback(hwnd: int, _extra: object) -> bool:
            info = _describe_window(hwnd, current_pid)
            if info is not None:
                found.append(info)
            return True

        win32gui.EnumWindows(callback, None)
        found.sort(key=lambda item: item.title.casefold())
        return found

    def find_window(self, hwnd: int) -> WindowInfo | None:
        return _describe_window(int(hwnd), os.getpid(), allow_minimized=True)

    def is_foreground(self, hwnd: int) -> bool:
        try:
            return int(win32gui.GetForegroundWindow()) == int(hwnd)
        except win32gui.error:
            return False

    def capture_client(self, hwnd: int) -> np.ndarray:
        info = self.find_window(hwnd)
        if info is None:
            raise CaptureError("截图失败：窗口不存在")
        if info.minimized or info.client.width <= 0 or info.client.height <= 0:
            raise CaptureError("截图失败：窗口已最小化或客户区无效")
        region = {
            "left": int(info.client.left),
            "top": int(info.client.top),
            "width": int(info.client.width),
            "height": int(info.client.height),
        }
        try:
            with mss.mss() as sct:
                shot = sct.grab(region)
                # 在 mss 缓冲区还活着时复制成 BGR，避免返回悬空视图。
                raw = np.array(shot, dtype=np.uint8, copy=True)
        except Exception as exc:
            raise CaptureError(f"截图失败：{exc}") from exc
        if raw.size == 0 or raw.ndim != 3 or raw.shape[2] < 3:
            raise CaptureError("截图失败：得到空画面")
        if raw.shape[2] == 4:
            frame = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)
        else:
            frame = np.ascontiguousarray(raw[:, :, :3])
        if frame.shape[1] != region["width"] or frame.shape[0] != region["height"]:
            raise CaptureError(
                "截图失败：像素尺寸与客户区不一致"
                f"（截图 {frame.shape[1]}×{frame.shape[0]}，"
                f"客户区 {region['width']}×{region['height']}）"
            )
        return np.ascontiguousarray(frame)


class PyAutoGuiPointer:
    def click(self, x: int, y: int) -> None:
        import pyautogui

        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0
        pyautogui.click(x=int(x), y=int(y), clicks=1, interval=0, button="left")


class WindowsHotkeyService:
    """在独立线程注册 F12。回调返回前不能调用 stop，否则会和本线程死锁。"""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._callback_error: BaseException | None = None

    def start(self, on_trigger: Callable[[], None]) -> str | None:
        self.stop()
        if self._thread is not None and self._thread.is_alive():
            return "热键线程未能及时退出"
        stop_event = threading.Event()
        self._stop = stop_event
        registered = threading.Event()
        error_box: list[str | None] = [None]

        def loop() -> None:
            did_register = False
            user32 = ctypes.windll.user32
            user32.RegisterHotKey.argtypes = [
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_uint,
                ctypes.c_uint,
            ]
            user32.RegisterHotKey.restype = wintypes.BOOL
            user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.UnregisterHotKey.restype = wintypes.BOOL
            user32.PeekMessageW.argtypes = [
                ctypes.POINTER(wintypes.MSG),
                wintypes.HWND,
                wintypes.UINT,
                wintypes.UINT,
                wintypes.UINT,
            ]
            user32.PeekMessageW.restype = wintypes.BOOL
            try:
                if not user32.RegisterHotKey(None, _HOTKEY_ID, _MOD_NOREPEAT, _VK_F12):
                    error_box[0] = "无法注册 F12 全局热键（可能被其他程序占用）"
                    registered.set()
                    return
                did_register = True
                registered.set()
                message = wintypes.MSG()
                while not stop_event.is_set():
                    while user32.PeekMessageW(ctypes.byref(message), None, 0, 0, _PM_REMOVE):
                        if message.message == _WM_HOTKEY and message.wParam == _HOTKEY_ID:
                            try:
                                on_trigger()
                            except Exception as exc:
                                self._callback_error = exc
                    stop_event.wait(0.05)
            except Exception as exc:
                error_box[0] = error_box[0] or f"热键线程异常：{exc}"
                registered.set()
            finally:
                if did_register:
                    try:
                        user32.UnregisterHotKey(None, _HOTKEY_ID)
                    except Exception as exc:
                        if error_box[0] is None:
                            error_box[0] = f"释放热键失败：{exc}"

        self._thread = threading.Thread(target=loop, name="lastz-hotkey", daemon=False)
        self._thread.start()
        if not registered.wait(2.0):
            stop_event.set()
            self._thread.join(timeout=2.0)
            return error_box[0] or "注册 F12 超时"
        return error_box[0]

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and threading.current_thread() is not thread:
            thread.join(timeout=2.0)
        if thread is None or not thread.is_alive():
            self._thread = None


def _describe_window(
    hwnd: int, current_pid: int, *, allow_minimized: bool = False
) -> WindowInfo | None:
    try:
        if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
            return None
        title = win32gui.GetWindowText(hwnd).strip()
        if not title:
            return None
        _thread_id, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid == current_pid:
            return None
        if _is_tool_window(hwnd) or _is_cloaked(hwnd):
            return None
        minimized = bool(win32gui.IsIconic(hwnd))
        if minimized and not allow_minimized:
            client = Rect(0, 0, 0, 0)
            return WindowInfo(hwnd=int(hwnd), title=title, client=client, minimized=True)
        client = _client_rect(hwnd)
        if client is None:
            if minimized and allow_minimized:
                return WindowInfo(
                    hwnd=int(hwnd), title=title, client=Rect(0, 0, 0, 0), minimized=True
                )
            return None
        return WindowInfo(hwnd=int(hwnd), title=title, client=client, minimized=minimized)
    except win32gui.error:
        return None


def _client_rect(hwnd: int) -> Rect | None:
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    width = int(right - left)
    height = int(bottom - top)
    if width <= 0 or height <= 0:
        return None
    origin_x, origin_y = win32gui.ClientToScreen(hwnd, (0, 0))
    return Rect(int(origin_x), int(origin_y), width, height)


def _is_tool_window(hwnd: int) -> bool:
    try:
        style = int(win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE))
    except win32gui.error:
        return False
    return bool(style & win32con.WS_EX_TOOLWINDOW)


def _is_cloaked(hwnd: int) -> bool:
    value = ctypes.c_int(0)
    try:
        dwmapi = ctypes.windll.dwmapi
        dwmapi.DwmGetWindowAttribute.argtypes = [
            wintypes.HWND,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long
        result = dwmapi.DwmGetWindowAttribute(
            int(hwnd),
            _DWMWA_CLOAKED,
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
    except (AttributeError, OSError):
        return False
    return result == 0 and value.value != 0
