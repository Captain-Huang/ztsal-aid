"""Tk 界面。后台线程只往队列放事件，控件只在主线程更新。"""

from __future__ import annotations

import queue
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from lastz_assistant.backends.protocol import HotkeyBackend, PointerBackend, WindowBackend
from lastz_assistant.catalog import ACTION_CATALOG
from lastz_assistant.engine import AutomationEngine
from lastz_assistant.models import (
    ActionSettings,
    ActionSpec,
    AssistantError,
    ConfigError,
    EngineEvent,
    EventKind,
    RunSettings,
    WindowInfo,
)
from lastz_assistant.runner import run_until_stopped
from lastz_assistant.settings_store import default_settings_path, load_settings, save_settings
from lastz_assistant.ui_queue import EmergencyStop, drain_events
from lastz_assistant.validation import validate_run_settings

_WARNING = (
    "外部辅助：只对你选中的窗口做截图模板匹配和模拟点击。"
    "不读内存、不注入、不抓包、不绕过反作弊。"
    "可能违反游戏规则，请先使用演练模式。"
)
_RUNNING_LOGS = {"已暂停", "运行中", "运行中（演练，不会点击）"}


@dataclass
class ActionForm:
    enabled: tk.BooleanVar
    path: tk.StringVar
    threshold: tk.StringVar
    cooldown: tk.StringVar


class AssistantApp:
    def __init__(
        self,
        root: tk.Tk,
        *,
        windows: WindowBackend,
        pointer: PointerBackend,
        hotkey: HotkeyBackend,
        catalog: tuple[ActionSpec, ...] = ACTION_CATALOG,
        settings_path: Path | None = None,
        dpi_mode: str = "",
        interactive: bool = True,
    ) -> None:
        self.root = root
        self._windows = windows
        self._pointer = pointer
        self._hotkey = hotkey
        self._catalog = catalog
        self._catalog_by_id = {spec.id: spec for spec in catalog}
        self._settings_path = default_settings_path() if settings_path is None else settings_path
        self._interactive = interactive
        self._dpi_mode = dpi_mode
        self._document = load_settings(self._settings_path, self._catalog)
        self._queue: queue.Queue[EngineEvent | EmergencyStop] = queue.Queue()
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._window_cache: list[WindowInfo] = []
        self._config_widgets: list[tk.Widget] = []
        self._closing = False
        self.forms: dict[str, ActionForm] = {}

        self.root.title("Last Z 助手")
        self.root.minsize(760, 680)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        self._load_form()
        self.refresh_windows()
        self._set_running(False)
        self._set_status("就绪")
        self._append_log(f"DPI 感知：{dpi_mode or '未设置'}")
        self._append_log("默认演练：只记录不点击。确认分数稳定后再取消演练。")
        self._append_log("F12 只在自动点击运行期间占用，停止或关闭窗口后释放。")
        self.root.after(100, self._poll)

    def refresh_windows(self) -> None:
        previous = self._selected_window()
        preferred = (
            previous.title if previous is not None else str(self._document.get("window_title", ""))
        )
        try:
            windows = self._windows.list_windows()
        except Exception as exc:
            self._report(f"无法枚举窗口：{exc}", title="窗口列表")
            return
        self._window_cache = windows
        self.window_combo["values"] = [_format_window(item) for item in windows]
        matches = [
            index for index, item in enumerate(windows) if preferred and item.title == preferred
        ]
        if len(matches) == 1:
            self.window_combo.current(matches[0])
        elif len(matches) > 1:
            self.window_combo.current(matches[0])
            self._append_log("有多个同名窗口，已选中第一个，请确认是游戏窗口")
        else:
            self.window_combo.set("")

    def start_automation(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            self._report("请先停止当前任务")
            return
        # 上一轮停止时，线程可能已经把“已停止”放进队列。清掉再启动，
        # 避免主线程稍后把过期的停止事件套到新任务上。
        self._discard_pending()
        try:
            settings = self._collect_settings()
            validate_run_settings(settings, self._catalog)
            window = self._windows.find_window(settings.hwnd)
            if window is None:
                raise ConfigError("目标窗口不存在或已关闭")
            if window.minimized:
                raise ConfigError("目标窗口已最小化，请先恢复窗口")
            engine = AutomationEngine(self._windows, self._pointer, catalog=self._catalog)
            engine.configure(settings)
        except AssistantError as exc:
            self._report(str(exc))
            return

        hotkey_error = self._arm_hotkey()
        if hotkey_error:
            self._report(hotkey_error)
            return

        self._stop_event.clear()
        self._pause_event.clear()
        self.pause_button.configure(text="暂停")
        self._worker = threading.Thread(
            target=run_until_stopped,
            args=(
                engine,
                self._stop_event,
                self._pause_event,
                settings.interval_sec,
                self._emit,
            ),
            name="lastz-automation",
            daemon=True,
        )
        try:
            self._worker.start()
        except Exception as exc:
            self._safe_stop_hotkey()
            self._worker = None
            self._report(f"自动化线程没有启动：{exc}")
            return
        self._set_running(True)
        names = [
            self._catalog_by_id[action.action_id].name
            for action in settings.actions
            if action.enabled
        ]
        self._append_log(f"开始监视「{window.title}」。间隔 {settings.interval_sec:.2f} 秒。")
        self._append_log("启用动作：" + "、".join(names))

    def toggle_pause(self) -> None:
        if self._worker is None or not self._worker.is_alive():
            return
        if self._pause_event.is_set():
            self._pause_event.clear()
            self.pause_button.configure(text="暂停")
        else:
            self._pause_event.set()
            self.pause_button.configure(text="继续")

    def stop_automation(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            self._append_log("正在停止…")
        self._enter_idle("已停止")

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._stop_event.set()
        worker = self._worker
        if worker is not None and worker.is_alive() and threading.current_thread() is not worker:
            worker.join(timeout=3.0)
        self._safe_stop_hotkey()
        try:
            self._save_settings()
        except Exception as exc:
            print(f"保存设置失败：{exc}", file=sys.stderr)
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def handle_engine_event(self, event: EngineEvent) -> None:
        if event.kind == EventKind.LOG and event.message in _RUNNING_LOGS:
            self._set_status(event.message)
            self._append_log(event.message)
            return
        if event.kind == EventKind.ERROR:
            self._set_status(f"错误：{event.message}")
            self._append_log(event.message)
            return
        if event.kind == EventKind.STOPPED:
            self._append_log(event.message)
            current = self._status_var.get()
            if current.startswith("错误") or current == "已紧急停止":
                self._enter_idle(current)
            else:
                label = "已停止" if event.message == "已停止" else event.message
                self._enter_idle(label)
            return
        self._append_log(event.message)

    def handle_emergency(self, event: EmergencyStop) -> None:
        self._append_log(event.message)
        self._enter_idle("已紧急停止")

    def _build(self) -> None:
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)

        warning = ttk.Label(outer, text=_WARNING, wraplength=720, justify="left")
        warning.pack(fill="x", pady=(0, 8))

        target = ttk.LabelFrame(outer, text="目标窗口", padding=8)
        target.pack(fill="x", pady=(0, 8))
        target_row = ttk.Frame(target)
        target_row.pack(fill="x")
        self.window_combo = ttk.Combobox(target_row, state="readonly", width=62)
        self.window_combo.pack(side="left", fill="x", expand=True)
        self.refresh_button = ttk.Button(target_row, text="刷新", command=self.refresh_windows)
        self.refresh_button.pack(side="left", padx=(8, 0))
        self._config_widgets.append(self.window_combo)
        self._config_widgets.append(self.refresh_button)
        hint = ttk.Label(target, text="只截取并点击这个窗口的客户区，不会点到其他窗口。")
        hint.pack(anchor="w", pady=(6, 0))

        actions = ttk.Frame(outer)
        actions.pack(fill="x")
        for spec in self._catalog:
            self._build_action(actions, spec)

        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=(8, 4))
        ttk.Label(controls, text="扫描间隔（秒）").pack(side="left")
        self.interval_var = tk.StringVar(value="0.60")
        interval = ttk.Spinbox(
            controls,
            textvariable=self.interval_var,
            from_=0.2,
            to=30,
            increment=0.1,
            width=6,
        )
        interval.pack(side="left", padx=(4, 12))
        self._config_widgets.append(interval)
        self.dry_run_var = tk.BooleanVar(value=True)
        dry_run = ttk.Checkbutton(
            controls,
            text="演练（只记录不点击）",
            variable=self.dry_run_var,
        )
        dry_run.pack(side="left")
        self._config_widgets.append(dry_run)

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(4, 4))
        self.start_button = ttk.Button(buttons, text="开始", command=self.start_automation)
        self.pause_button = ttk.Button(buttons, text="暂停", command=self.toggle_pause)
        self.stop_button = ttk.Button(buttons, text="停止", command=self.stop_automation)
        self.start_button.pack(side="left")
        self.pause_button.pack(side="left", padx=6)
        self.stop_button.pack(side="left")
        self._status_var = tk.StringVar(value="就绪")
        self._status_label = ttk.Label(buttons, textvariable=self._status_var)
        self._status_label.pack(side="left", padx=(12, 0))

        note = ttk.Label(
            outer,
            text="连续至少两帧确认后才动作。各动作冷却独立。点击前会再次确认窗口仍在且为前台。",
            wraplength=720,
        )
        note.pack(anchor="w", pady=(0, 6))

        log_frame = ttk.LabelFrame(outer, text="状态日志", padding=4)
        log_frame.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(log_frame)
        scroll.pack(side="right", fill="y")
        self.log_text = tk.Text(log_frame, height=14, wrap="word", yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.configure(command=self.log_text.yview)
        self.log_text.configure(state="disabled")

    def _build_action(self, parent: ttk.Frame, spec: ActionSpec) -> None:
        frame = ttk.LabelFrame(parent, text=spec.name, padding=8)
        frame.pack(fill="x", pady=(0, 8))
        ttk.Label(frame, text=spec.description, wraplength=700).pack(anchor="w")
        form = ActionForm(
            enabled=tk.BooleanVar(value=True),
            path=tk.StringVar(value=""),
            threshold=tk.StringVar(value=f"{spec.default_threshold:.2f}"),
            cooldown=tk.StringVar(value=f"{spec.default_cooldown_sec:.1f}"),
        )
        self.forms[spec.id] = form

        path_row = ttk.Frame(frame)
        path_row.pack(fill="x", pady=(6, 0))
        ttk.Label(path_row, text="模板 PNG").pack(side="left")
        entry = ttk.Entry(path_row, textvariable=form.path)
        entry.pack(side="left", fill="x", expand=True, padx=6)
        browse = ttk.Button(
            path_row,
            text="浏览…",
            command=lambda action_id=spec.id: self._browse(action_id),
        )
        browse.pack(side="left")
        self._config_widgets.extend([entry, browse])

        option_row = ttk.Frame(frame)
        option_row.pack(fill="x", pady=(6, 0))
        enabled = ttk.Checkbutton(option_row, text="启用", variable=form.enabled)
        enabled.pack(side="left")
        ttk.Label(option_row, text="阈值").pack(side="left", padx=(12, 0))
        threshold = ttk.Spinbox(
            option_row,
            textvariable=form.threshold,
            from_=0.5,
            to=0.99,
            increment=0.01,
            width=6,
        )
        threshold.pack(side="left", padx=(4, 12))
        ttk.Label(option_row, text="冷却（秒）").pack(side="left")
        cooldown = ttk.Spinbox(
            option_row,
            textvariable=form.cooldown,
            from_=0.5,
            to=600,
            increment=0.5,
            width=6,
        )
        cooldown.pack(side="left", padx=(4, 12))
        ttk.Label(option_row, text=f"确认帧：{spec.confirm_frames}").pack(side="left")
        self._config_widgets.extend([enabled, threshold, cooldown])

    def _load_form(self) -> None:
        self.interval_var.set(f"{float(self._document['interval_sec']):.2f}")
        self.dry_run_var.set(bool(self._document["dry_run"]))
        saved = self._document["actions"]
        for spec in self._catalog:
            form = self.forms[spec.id]
            slot = saved.get(spec.id, {})
            form.enabled.set(bool(slot.get("enabled", True)))
            form.path.set(str(slot.get("template_path", "")))
            form.threshold.set(f"{float(slot.get('threshold', spec.default_threshold)):.2f}")
            form.cooldown.set(f"{float(slot.get('cooldown_sec', spec.default_cooldown_sec)):.1f}")

    def _browse(self, action_id: str) -> None:
        spec = self._catalog_by_id[action_id]
        current = self.forms[action_id].path.get().strip()
        initial = str(Path(current).parent) if current else str(Path.cwd())
        if not Path(initial).is_dir():
            initial = str(Path.cwd())
        selected = filedialog.askopenfilename(
            parent=self.root,
            title=f"选择「{spec.name}」模板",
            initialdir=initial,
            filetypes=[("PNG 图片", "*.png"), ("所有文件", "*.*")],
        )
        if selected:
            self.forms[action_id].path.set(selected)

    def _collect_settings(self) -> RunSettings:
        window = self._selected_window()
        if window is None:
            raise ConfigError("请选择目标窗口")
        interval = _read_float(self.interval_var.get(), "扫描间隔")
        actions: list[ActionSettings] = []
        for spec in self._catalog:
            form = self.forms[spec.id]
            if not bool(form.enabled.get()):
                actions.append(
                    ActionSettings(
                        spec.id,
                        False,
                        "",
                        spec.default_threshold,
                        spec.default_cooldown_sec,
                    )
                )
                continue
            actions.append(
                ActionSettings(
                    action_id=spec.id,
                    enabled=True,
                    template_path=form.path.get().strip(),
                    threshold=_read_float(form.threshold.get(), f"「{spec.name}」的阈值"),
                    cooldown_sec=_read_float(form.cooldown.get(), f"「{spec.name}」的冷却"),
                )
            )
        return RunSettings(
            hwnd=window.hwnd,
            interval_sec=interval,
            dry_run=bool(self.dry_run_var.get()),
            actions=tuple(actions),
        )

    def _selected_window(self) -> WindowInfo | None:
        index = self.window_combo.current()
        if index < 0 or index >= len(self._window_cache):
            return None
        return self._window_cache[index]

    def _save_settings(self) -> None:
        document = load_settings(self._settings_path, self._catalog)
        document["dry_run"] = bool(self.dry_run_var.get())
        try:
            document["interval_sec"] = float(self.interval_var.get())
        except ValueError:
            pass
        window = self._selected_window()
        document["window_title"] = window.title if window is not None else ""
        for spec in self._catalog:
            form = self.forms[spec.id]
            slot = document["actions"][spec.id]
            slot["enabled"] = bool(form.enabled.get())
            slot["template_path"] = form.path.get().strip()
            try:
                slot["threshold"] = float(form.threshold.get())
            except ValueError:
                pass
            try:
                slot["cooldown_sec"] = float(form.cooldown.get())
            except ValueError:
                pass
        save_settings(self._settings_path, document)
        self._document = document

    def _arm_hotkey(self) -> str | None:
        try:
            error = self._hotkey.start(self._on_emergency)
        except Exception as exc:
            self._safe_stop_hotkey()
            return f"注册热键失败：{exc}"
        if error:
            self._safe_stop_hotkey()
            return error
        return None

    def _on_emergency(self) -> None:
        worker = self._worker
        if worker is None or not worker.is_alive():
            self._queue.put(EngineEvent(EventKind.LOG, "当前没有在运行，已忽略 F12"))
            return
        self._stop_event.set()
        self._queue.put(EmergencyStop())

    def _emit(self, event: EngineEvent) -> None:
        self._queue.put(event)

    def _discard_pending(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return

    def _enter_idle(self, status: str) -> None:
        self._stop_event.set()
        worker = self._worker
        if worker is not None and worker.is_alive() and threading.current_thread() is not worker:
            worker.join(timeout=3.0)
        if worker is not None and worker.is_alive():
            self._set_status("正在停止…")
            self._append_log("自动化线程尚未退出")
            return
        self._worker = None
        self._pause_event.clear()
        self.pause_button.configure(text="暂停")
        self._safe_stop_hotkey()
        self._set_running(False)
        self._set_status(status)

    def _safe_stop_hotkey(self) -> None:
        try:
            self._hotkey.stop()
        except Exception as exc:
            self._append_log(f"释放热键失败：{exc}")

    def _poll(self) -> None:
        if self._closing:
            return
        try:
            drain_events(self._queue, self)
        except Exception as exc:
            self._append_log(f"界面更新失败：{exc}")
        if not self._closing:
            try:
                if self.root.winfo_exists():
                    self.root.after(100, self._poll)
            except tk.TclError:
                return

    def _set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        for widget in self._config_widgets:
            if widget is self.window_combo:
                widget.configure(state="disabled" if running else "readonly")
            else:
                widget.configure(state=state)
        self.start_button.configure(state="disabled" if running else "normal")
        self.pause_button.configure(state="normal" if running else "disabled")
        self.stop_button.configure(state="normal" if running else "disabled")

    def _set_status(self, text: str) -> None:
        self._status_var.set(text)
        if text.startswith("错误") or "失败" in text:
            color = "#a1260d"
        elif "暂停" in text:
            color = "#9a6700"
        elif text.startswith("运行"):
            color = "#1a7f37"
        else:
            color = "#333333"
        self._status_label.configure(foreground=color)

    def _append_log(self, text: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{stamp}] {text}\n")
        line_count = int(self.log_text.index("end-1c").split(".", maxsplit=1)[0])
        if line_count > 400:
            self.log_text.delete("1.0", f"{line_count - 400}.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _report(self, message: str, *, title: str = "无法启动") -> None:
        self._set_status(f"错误：{message}")
        self._append_log(message)
        if self._interactive:
            messagebox.showerror(title, message, parent=self.root)


def launch() -> None:
    from lastz_assistant.backends import create_platform
    from lastz_assistant.dpi import enable_dpi_awareness

    dpi_mode = enable_dpi_awareness()
    windows, pointer, hotkey = create_platform()
    root = tk.Tk()
    AssistantApp(
        root,
        windows=windows,
        pointer=pointer,
        hotkey=hotkey,
        dpi_mode=dpi_mode,
    )
    root.mainloop()


def _format_window(window: WindowInfo) -> str:
    title = window.title if len(window.title) <= 80 else window.title[:77] + "…"
    suffix = "（最小化）" if window.minimized else ""
    return f"{title}{suffix}  [{window.hwnd}]"


def _read_float(raw: str, label: str) -> float:
    try:
        return float(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"{label} 不是有效数字") from exc
