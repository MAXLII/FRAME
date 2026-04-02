from __future__ import annotations

from bisect import bisect_left
from datetime import datetime
import json
from pathlib import Path
import math
import tkinter as tk
from tkinter import filedialog, ttk


REDRAW_MS = 40
LIST_REFRESH_MS = 120
MIN_ZOOM_SPAN_SECONDS = 0.2
MIN_ZOOM_SPAN_VALUE = 1e-6
SHIFT_MASK = 0x0001
CTRL_MASK = 0x0004
WAVE_FILE_EXTENSION = ".sda_wave"
WAVE_FILE_FORMAT = "serial_debug_assistant.waveform"
WAVE_FILE_VERSION = 1
WINDOW_OPTIONS = {
    "最近10秒": 10.0,
    "最近30秒": 30.0,
    "最近1分钟": 60.0,
    "最近10分钟": 600.0,
    "全部": None,
}
SERIES_COLORS = (
    "#2563eb",
    "#dc2626",
    "#16a34a",
    "#d97706",
    "#7c3aed",
    "#0891b2",
    "#be123c",
    "#65a30d",
)


class WaveformTab(ttk.Frame):
    def __init__(
        self,
        master,
        *,
        on_apply_period,
        on_toggle_run,
        on_clear,
        export_dir: Path,
        on_status,
    ) -> None:
        super().__init__(master, style="Panel.TFrame", padding=12)
        self.on_apply_period = on_apply_period
        self.on_toggle_run = on_toggle_run
        self.on_clear = on_clear
        self.export_dir = export_dir
        self.on_status = on_status

        self.period_var = tk.StringVar(value="300")
        self.window_var = tk.StringVar(value="最近30秒")
        self.marker_var = tk.StringVar()
        self.selected_search_var = tk.StringVar()
        self.status_var = tk.StringVar(value="当前处于停止状态")
        self.view_var = tk.StringVar(value="查看窗口: 最近30秒")
        self.cursor_var = tk.StringVar(value="把鼠标移动到图上即可查看该时刻的数据")
        self.run_button_text = tk.StringVar(value="开始")
        self.pause_button_text = tk.StringVar(value="暂停显示")

        self.selected_names: list[str] = []
        self.visible_names: set[str] = set()
        self.latest_values: dict[str, str] = {}
        self.series_data: dict[str, list[tuple[float, float | None]]] = {}
        self.markers: list[tuple[float, str]] = []

        self._row_widgets: dict[str, tuple[tk.Frame, tk.Checkbutton, tk.Label]] = {}
        self._row_vars: dict[str, tk.BooleanVar] = {}
        self._latest_widgets: dict[str, tuple[tk.Frame, tk.Canvas, tk.Label, tk.Label]] = {}
        self._latest_empty_label: tk.Label | None = None
        self._list_refresh_job: str | None = None
        self._latest_refresh_job: str | None = None
        self._redraw_job: str | None = None
        self._plot_bounds: tuple[float, float, float, float] | None = None
        self._x_range: tuple[float, float] | None = None
        self._y_range: tuple[float, float] | None = None
        self._manual_range: tuple[float, float] | None = None
        self._manual_y_range: tuple[float, float] | None = None
        self._frozen_x_range: tuple[float, float] | None = None
        self._frozen_y_range: tuple[float, float] | None = None
        self._paused_view = False
        self._alt_pressed = False
        self._last_hover_index: int | None = None
        self._drag_last_x: float | None = None
        self._drag_mode: str | None = None
        self._drag_anchor: tuple[float, float] | None = None
        self._drag_start_x_range: tuple[float, float] | None = None
        self._drag_start_y_range: tuple[float, float] | None = None
        self._zoom_rect_start: tuple[float, float] | None = None
        self._zoom_rect_end: tuple[float, float] | None = None
        self._cached_visible_series: dict[str, list[tuple[float, float | None]]] = {}

        self._build()
        self.window_var.trace_add("write", self._on_window_changed)
        self.selected_search_var.trace_add("write", self._on_selected_search_changed)
        self.bind_all("<KeyPress-f>", self._on_show_all_shortcut, add=True)
        self.bind_all("<KeyPress-F>", self._on_show_all_shortcut, add=True)
        self.bind_all("<KeyPress-r>", self._on_apply_period_shortcut, add=True)
        self.bind_all("<KeyPress-R>", self._on_apply_period_shortcut, add=True)
        self.bind_all("<KeyPress-p>", self._on_pause_shortcut, add=True)
        self.bind_all("<KeyPress-P>", self._on_pause_shortcut, add=True)
        self.bind_all("<KeyPress-l>", self._on_back_to_live_shortcut, add=True)
        self.bind_all("<KeyPress-L>", self._on_back_to_live_shortcut, add=True)
        self.bind_all("<Control-e>", self._on_export_shortcut, add=True)
        self.bind_all("<Control-E>", self._on_export_shortcut, add=True)
        self.bind_all("<Control-i>", self._on_import_shortcut, add=True)
        self.bind_all("<Control-I>", self._on_import_shortcut, add=True)
        self.bind_all("<KeyPress-m>", self._on_marker_shortcut, add=True)
        self.bind_all("<KeyPress-M>", self._on_marker_shortcut, add=True)
        self.bind_all("<KeyPress-Alt_L>", self._on_alt_press, add=True)
        self.bind_all("<KeyPress-Alt_R>", self._on_alt_press, add=True)
        self.bind_all("<KeyRelease-Alt_L>", self._on_alt_release, add=True)
        self.bind_all("<KeyRelease-Alt_R>", self._on_alt_release, add=True)

    def _build(self) -> None:
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=0, minsize=280)
        self.columnconfigure(1, weight=1)

        top = ttk.Frame(self, style="Panel.TFrame")
        top.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        top.columnconfigure(9, weight=1)

        row1 = ttk.Frame(top, style="Panel.TFrame")
        row1.grid(row=0, column=0, sticky="ew")
        row1.columnconfigure(9, weight=1)
        ttk.Label(row1, text="上报周期(ms):", style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(row1, textvariable=self.period_var, width=10).grid(row=0, column=1, padx=(6, 8))
        ttk.Button(row1, text="应用周期 R", command=self.on_apply_period).grid(row=0, column=2)
        ttk.Button(row1, textvariable=self.run_button_text, command=self.on_toggle_run, style="Accent.TButton").grid(
            row=0,
            column=3,
            padx=(8, 8),
        )
        ttk.Button(row1, text="暂停/继续 P", command=self.toggle_pause_view).grid(row=0, column=4)
        ttk.Button(row1, text="回到实时 L", command=self.back_to_live).grid(row=0, column=5, padx=(8, 0))
        ttk.Button(row1, text="显示全部 F", command=self.show_all).grid(row=0, column=6, padx=(8, 0))
        ttk.Button(row1, text="清空", command=self.on_clear).grid(row=0, column=7, padx=(8, 0))
        ttk.Label(row1, textvariable=self.status_var, style="Header.TLabel").grid(row=0, column=8, sticky="w", padx=(16, 12))
        ttk.Label(row1, textvariable=self.view_var).grid(row=0, column=9, sticky="e")

        row2 = ttk.Frame(top, style="Panel.TFrame")
        row2.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        row2.columnconfigure(7, weight=1)
        ttk.Label(row2, text="查看窗口:", style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            row2,
            textvariable=self.window_var,
            values=tuple(WINDOW_OPTIONS.keys()),
            state="readonly",
            width=12,
        ).grid(row=0, column=1, padx=(6, 12), sticky="w")
        ttk.Button(row2, text="导出 Ctrl+E", command=self.export_waveform_file).grid(row=0, column=2)
        ttk.Button(row2, text="导入 Ctrl+I", command=self.import_waveform_file).grid(row=0, column=3, padx=(8, 0))
        ttk.Entry(row2, textvariable=self.marker_var, width=18).grid(row=0, column=4, padx=(12, 6), sticky="w")
        ttk.Button(row2, text="添加标记 M", command=self.add_marker).grid(row=0, column=5)
        ttk.Label(
            row2,
            text="提示: Alt 显示当前点值",
            style="Status.TLabel",
        ).grid(row=0, column=7, sticky="e")

        left = ttk.LabelFrame(self, text="已选参数", style="Section.TLabelframe", padding=10)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 12))
        left.rowconfigure(3, weight=1)
        left.columnconfigure(0, weight=1)

        ttk.Label(left, text="在“参数读写”页勾选波形显示后，这里会自动列出已选择的参数。").grid(
            row=0,
            column=0,
            sticky="w",
            pady=(0, 8),
        )

        search_row = ttk.Frame(left, style="Panel.TFrame")
        search_row.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        search_row.columnconfigure(1, weight=1)
        ttk.Label(search_row, text="搜索:", style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(search_row, textvariable=self.selected_search_var).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        header = ttk.Frame(left, style="Panel.TFrame")
        header.grid(row=2, column=0, sticky="ew", pady=(0, 4))
        ttk.Label(header, text="显示", width=5).grid(row=0, column=0, padx=(2, 8))
        ttk.Label(header, text="参数名").grid(row=0, column=1, sticky="w")

        self.series_canvas = tk.Canvas(left, bg="#ffffff", highlightthickness=1, highlightbackground="#cbd5e1", relief="flat")
        self.series_canvas.grid(row=3, column=0, sticky="nsew")
        self.series_list_frame = tk.Frame(self.series_canvas, bg="#ffffff")
        self.series_window = self.series_canvas.create_window((0, 0), window=self.series_list_frame, anchor="nw")
        self.series_list_frame.bind("<Configure>", self._on_series_frame_configure)
        self.series_canvas.bind("<Configure>", self._on_series_canvas_configure)
        self.series_canvas.bind("<MouseWheel>", self._on_series_canvas_mousewheel)

        left_scroll = ttk.Scrollbar(left, orient="vertical", command=self.series_canvas.yview)
        left_scroll.grid(row=3, column=1, sticky="ns")
        self.series_canvas.configure(yscrollcommand=left_scroll.set)

        right = ttk.LabelFrame(self, text="实时波形", style="Section.TLabelframe", padding=10)
        right.grid(row=1, column=1, sticky="nsew")
        right.rowconfigure(0, weight=1)
        right.rowconfigure(1, weight=0)
        right.columnconfigure(0, weight=1)
        right.columnconfigure(1, weight=0, minsize=250)

        self.canvas = tk.Canvas(right, bg="#ffffff", highlightthickness=0, relief="flat")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda _event: self._queue_redraw())
        self.canvas.bind("<Motion>", self._on_canvas_motion)
        self.canvas.bind("<Leave>", self._on_canvas_leave)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<ButtonPress-1>", self._on_drag_start)
        self.canvas.bind("<B1-Motion>", self._on_drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._on_drag_end)

        latest_frame = ttk.LabelFrame(right, text="最新值", style="Section.TLabelframe", padding=8)
        latest_frame.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        latest_frame.rowconfigure(0, weight=1)
        latest_frame.columnconfigure(0, weight=1)

        self.latest_canvas = tk.Canvas(
            latest_frame,
            bg="#ffffff",
            highlightthickness=1,
            highlightbackground="#cbd5e1",
            relief="flat",
            width=240,
        )
        self.latest_canvas.grid(row=0, column=0, sticky="nsew")
        self.latest_list_frame = tk.Frame(self.latest_canvas, bg="#ffffff")
        self.latest_window = self.latest_canvas.create_window((0, 0), window=self.latest_list_frame, anchor="nw")
        self.latest_list_frame.bind("<Configure>", self._on_latest_frame_configure)
        self.latest_canvas.bind("<Configure>", self._on_latest_canvas_configure)
        self.latest_canvas.bind("<MouseWheel>", self._on_latest_canvas_mousewheel)

        latest_scroll = ttk.Scrollbar(latest_frame, orient="vertical", command=self.latest_canvas.yview)
        latest_scroll.grid(row=0, column=1, sticky="ns")
        self.latest_canvas.configure(yscrollcommand=latest_scroll.set)

        ttk.Label(right, textvariable=self.cursor_var, style="Status.TLabel", anchor="w", justify="left").grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(8, 0),
        )

    def set_period(self, period_ms: int) -> None:
        self.period_var.set(str(period_ms))

    def set_running(self, running: bool) -> None:
        self.status_var.set("当前处于运行状态" if running else "当前处于停止状态")
        self.run_button_text.set("停止" if running else "开始")

    def set_selected_parameters(self, names: list[str]) -> None:
        self.selected_names = list(names)
        current_names = set(names)
        self.visible_names &= current_names
        for name in names:
            self.series_data.setdefault(name, [])
            if name not in self._row_widgets:
                row_var = tk.BooleanVar(value=name in self.visible_names)
                row = tk.Frame(self.series_list_frame, bg="#ffffff", highlightthickness=0, bd=0)
                checkbox = tk.Checkbutton(
                    row,
                    variable=row_var,
                    bg="#ffffff",
                    activebackground="#ffffff",
                    highlightthickness=0,
                    bd=0,
                    relief="flat",
                    command=lambda item=name: self._on_row_toggle(item),
                )
                checkbox.grid(row=0, column=0, padx=(4, 8))
                label = tk.Label(row, text=name, anchor="w", bg="#ffffff", fg="#0f172a")
                label.grid(row=0, column=1, sticky="w", padx=(0, 6))
                row.columnconfigure(1, weight=1)
                row.pack(fill="x", padx=2, pady=1)
                for widget in (row, checkbox, label):
                    widget.bind("<MouseWheel>", self._on_series_canvas_mousewheel)
                self._row_vars[name] = row_var
                self._row_widgets[name] = (row, checkbox, label)

        for stale_name in list(self.series_data):
            if stale_name not in current_names:
                del self.series_data[stale_name]
                self.latest_values.pop(stale_name, None)
                self.visible_names.discard(stale_name)
        for stale_name in list(self._row_widgets):
            if stale_name not in current_names:
                row, _check, _label = self._row_widgets.pop(stale_name)
                row.destroy()
                self._row_vars.pop(stale_name, None)

        self._refresh_series_order()
        self._queue_list_refresh()
        self._queue_latest_refresh()
        self._queue_redraw()

    def update_latest_value(self, name: str, value_text: str) -> None:
        self.latest_values[name] = value_text
        self._queue_list_refresh()
        self._queue_latest_refresh()

    def append_batch(self, batch: dict[str, float], batch_time: float | None = None) -> None:
        timestamp = batch_time if batch_time is not None else datetime.now().timestamp()
        for name in self.selected_names:
            self.series_data.setdefault(name, []).append((timestamp, batch.get(name)))
        for name, value in batch.items():
            self.latest_values[name] = self._format_numeric(value)
        self._queue_list_refresh()
        self._queue_latest_refresh()
        self._queue_redraw()

    def clear_plot(self) -> None:
        for data in self.series_data.values():
            data.clear()
        self.latest_values.clear()
        self.markers.clear()
        self._last_hover_index = None
        self._manual_range = None
        self._manual_y_range = None
        self._frozen_x_range = None
        self._frozen_y_range = None
        self._paused_view = False
        self._alt_pressed = False
        self._drag_last_x = None
        self._drag_mode = None
        self._drag_anchor = None
        self._drag_start_x_range = None
        self._drag_start_y_range = None
        self._zoom_rect_start = None
        self._zoom_rect_end = None
        self.pause_button_text.set("暂停显示")
        self.cursor_var.set("把鼠标移动到图上即可查看该时刻的数据")
        self._queue_list_refresh()
        self._queue_latest_refresh()
        self._queue_redraw()

    def _checkbox_text(self, name: str) -> str:
        return "☑" if name in self.visible_names else "☐"

    def toggle_pause_view(self) -> None:
        self._paused_view = not self._paused_view
        self.pause_button_text.set("继续显示" if self._paused_view else "暂停显示")
        if self._paused_view:
            if self._x_range:
                self._frozen_x_range = self._x_range
                self._manual_range = self._x_range
            if self._y_range:
                self._frozen_y_range = self._y_range
                self._manual_y_range = self._y_range
        else:
            self._manual_range = None
            self._manual_y_range = None
            self._frozen_x_range = None
            self._frozen_y_range = None
        self._queue_redraw()

    def back_to_live(self) -> None:
        self._paused_view = False
        self._manual_range = None
        self._manual_y_range = None
        self._frozen_x_range = None
        self._frozen_y_range = None
        self.pause_button_text.set("暂停显示")
        self._queue_redraw()

    def show_all(self) -> None:
        self._paused_view = True
        self._manual_range = None
        self._manual_y_range = None
        self._frozen_x_range = None
        self._frozen_y_range = None
        self.window_var.set("全部")
        self.pause_button_text.set("继续显示")
        self.on_status("已切换为显示全部波形", False)
        self._queue_redraw()

    def add_marker(self) -> None:
        timestamp = self._latest_timestamp()
        if timestamp is None:
            self.on_status("当前还没有波形数据可添加标记", True)
            return
        label = self.marker_var.get().strip() or f"标记{len(self.markers) + 1}"
        self.markers.append((timestamp, label))
        self.marker_var.set("")
        self.on_status(f"已添加标记: {label}", False)
        self._queue_redraw()

    def export_waveform_file(self) -> None:
        if not any(self.series_data.values()):
            self.on_status("当前没有可导出的波形数据", True)
            return
        self.export_dir.mkdir(parents=True, exist_ok=True)
        default_path = self.export_dir / f"waveform_{datetime.now():%Y%m%d_%H%M%S}{WAVE_FILE_EXTENSION}"
        path = filedialog.asksaveasfilename(
            title="导出波形文件",
            initialdir=str(self.export_dir),
            initialfile=default_path.name,
            defaultextension=WAVE_FILE_EXTENSION,
            filetypes=[("波形数据文件", f"*{WAVE_FILE_EXTENSION}"), ("所有文件", "*.*")],
        )
        if not path:
            self.on_status("已取消导出波形文件", False)
            return

        file_path = Path(path)
        payload = {
            "format": WAVE_FILE_FORMAT,
            "version": WAVE_FILE_VERSION,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "period_ms": self.period_var.get(),
            "selected_names": self.selected_names,
            "visible_names": sorted(self.visible_names),
            "markers": [{"timestamp": timestamp, "label": label} for timestamp, label in self.markers],
            "series_data": {
                name: [
                    {"timestamp": timestamp, "value": value}
                    for timestamp, value in self.series_data.get(name, [])
                ]
                for name in self.selected_names
            },
        }
        file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.on_status(f"已导出波形文件: {file_path}", False)

    def import_waveform_file(self) -> None:
        self.export_dir.mkdir(parents=True, exist_ok=True)
        path = filedialog.askopenfilename(
            title="导入波形文件",
            initialdir=str(self.export_dir),
            filetypes=[("波形数据文件", f"*{WAVE_FILE_EXTENSION}"), ("所有文件", "*.*")],
        )
        if not path:
            self.on_status("已取消导入波形文件", False)
            return

        file_path = Path(path)
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.on_status(f"导入波形文件失败: {exc}", True)
            return

        if payload.get("format") != WAVE_FILE_FORMAT:
            self.on_status("导入失败: 文件格式不匹配", True)
            return

        series_payload = payload.get("series_data", {})
        selected_names = [str(name) for name in payload.get("selected_names", [])]
        if not selected_names and isinstance(series_payload, dict):
            selected_names = [str(name) for name in series_payload.keys()]

        imported_series: dict[str, list[tuple[float, float | None]]] = {}
        for name in selected_names:
            samples = series_payload.get(name, [])
            restored: list[tuple[float, float | None]] = []
            for item in samples:
                try:
                    timestamp = float(item["timestamp"])
                except (KeyError, TypeError, ValueError):
                    continue
                raw_value = item.get("value")
                if raw_value is None:
                    restored.append((timestamp, None))
                    continue
                try:
                    restored.append((timestamp, float(raw_value)))
                except (TypeError, ValueError):
                    restored.append((timestamp, None))
            imported_series[name] = restored

        self.selected_names = []
        self.visible_names = {str(name) for name in payload.get("visible_names", []) if str(name) in selected_names}
        self.series_data = {}
        self.latest_values.clear()
        self.markers = []
        self._last_hover_index = None
        self._manual_range = None
        self._manual_y_range = None
        self._frozen_x_range = None
        self._frozen_y_range = None
        self._paused_view = False
        self.pause_button_text.set("暂停显示")
        self.cursor_var.set("把鼠标移动到图上即可查看该时刻的数据")

        for marker in payload.get("markers", []):
            try:
                timestamp = float(marker["timestamp"])
                label = str(marker["label"])
            except (KeyError, TypeError, ValueError):
                continue
            self.markers.append((timestamp, label))

        period_ms = str(payload.get("period_ms", self.period_var.get()))
        if period_ms.isdigit():
            self.period_var.set(period_ms)

        self.set_selected_parameters(selected_names)
        for name, samples in imported_series.items():
            self.series_data[name] = samples
            for _timestamp, value in reversed(samples):
                if value is not None and math.isfinite(value):
                    self.latest_values[name] = self._format_numeric(value)
                    break

        self._queue_list_refresh()
        self._queue_latest_refresh()
        self._queue_redraw()
        self.on_status(f"已导入波形文件: {file_path}", False)

    def _marker_map(self) -> dict[float, str]:
        return {timestamp: label for timestamp, label in self.markers}

    def _latest_timestamp(self) -> float | None:
        timestamps = [series[-1][0] for series in self.series_data.values() if series]
        return max(timestamps) if timestamps else None

    def _exact_sample(self, series: list[tuple[float, float | None]], timestamp: float) -> tuple[float, float | None] | None:
        for item in series:
            if item[0] == timestamp:
                return item
        return None

    def _refresh_series_order(self) -> None:
        for name in self.selected_names:
            widgets = self._row_widgets.get(name)
            if widgets:
                row = widgets[0]
                row.pack_forget()
                if self._matches_selected_filter(name):
                    row.pack(fill="x", padx=2, pady=1)

    def _matches_selected_filter(self, name: str) -> bool:
        keyword = self.selected_search_var.get().strip().lower()
        return not keyword or keyword in name.lower()

    def _queue_list_refresh(self) -> None:
        if self._list_refresh_job is not None:
            return
        self._list_refresh_job = self.after(LIST_REFRESH_MS, self._run_list_refresh)

    def _run_list_refresh(self) -> None:
        self._list_refresh_job = None
        self._refresh_series_order()
        for name in self.selected_names:
            self._refresh_row_widget(name)

    def _on_selected_search_changed(self, *_args) -> None:
        self._queue_list_refresh()

    def _queue_latest_refresh(self) -> None:
        if self._latest_refresh_job is not None:
            return
        self._latest_refresh_job = self.after(LIST_REFRESH_MS, self._run_latest_refresh)

    def _run_latest_refresh(self) -> None:
        self._latest_refresh_job = None
        visible_names = [name for name in self.selected_names if name in self.visible_names]
        if not visible_names:
            for stale_name, widgets in list(self._latest_widgets.items()):
                widgets[0].destroy()
                del self._latest_widgets[stale_name]
            if self._latest_empty_label is None:
                self._latest_empty_label = tk.Label(
                    self.latest_list_frame,
                    text="当前没有勾选显示的参数。",
                    anchor="w",
                    justify="left",
                    bg="#ffffff",
                    fg="#64748b",
                )
                self._latest_empty_label.pack(fill="x", padx=8, pady=8)
            return
        if self._latest_empty_label is not None:
            self._latest_empty_label.destroy()
            self._latest_empty_label = None

        for idx, name in enumerate(visible_names):
            color = SERIES_COLORS[idx % len(SERIES_COLORS)]
            value_text = self.latest_values.get(name, "-")
            widgets = self._latest_widgets.get(name)
            if widgets is None:
                row = tk.Frame(self.latest_list_frame, bg="#ffffff", highlightthickness=0, bd=0)
                swatch = tk.Canvas(row, width=12, height=12, bg="#ffffff", highlightthickness=0, bd=0)
                swatch.grid(row=0, column=0, padx=(0, 6), sticky="n")
                name_label = tk.Label(
                    row,
                    text=name,
                    anchor="w",
                    justify="left",
                    bg="#ffffff",
                    fg="#0f172a",
                    wraplength=130,
                )
                name_label.grid(row=0, column=1, sticky="w")
                value_label = tk.Label(
                    row,
                    text=value_text,
                    anchor="e",
                    justify="right",
                    bg="#ffffff",
                    fg="#334155",
                    font=("Consolas", 10),
                )
                value_label.grid(row=0, column=2, sticky="e", padx=(8, 0))
                row.columnconfigure(1, weight=1)
                for widget in (row, swatch, name_label, value_label):
                    widget.bind("<MouseWheel>", self._on_latest_canvas_mousewheel)
                self._latest_widgets[name] = (row, swatch, name_label, value_label)
                widgets = self._latest_widgets[name]
            row, swatch, name_label, value_label = widgets
            row.pack_forget()
            row.pack(fill="x", padx=6, pady=2)
            swatch.delete("all")
            swatch.create_line(1, 6, 11, 6, fill=color, width=3)
            name_label.configure(text=name)
            value_label.configure(text=value_text)

        for stale_name, widgets in list(self._latest_widgets.items()):
            if stale_name not in visible_names:
                widgets[0].destroy()
                del self._latest_widgets[stale_name]

    def _series_color(self, name: str) -> str:
        try:
            index = self.selected_names.index(name)
        except ValueError:
            index = 0
        return SERIES_COLORS[index % len(SERIES_COLORS)]

    def _refresh_row_widget(self, name: str) -> None:
        widgets = self._row_widgets.get(name)
        if not widgets:
            return
        row, checkbox, label = widgets
        visible = name in self.visible_names
        bg = "#eaf2ff" if visible else "#ffffff"
        fg = "#0f172a" if visible else "#334155"
        row.configure(bg=bg)
        checkbox.configure(bg=bg, activebackground=bg, selectcolor=bg)
        label.configure(bg=bg, fg=fg)
        row_var = self._row_vars.get(name)
        if row_var is not None:
            row_var.set(visible)

    def _on_row_toggle(self, name: str) -> None:
        if name in self.visible_names:
            self.visible_names.remove(name)
        else:
            self.visible_names.add(name)
        self._refresh_row_widget(name)
        self._last_hover_index = None
        self.cursor_var.set("把鼠标移动到图上即可查看该时刻的数据")
        self._queue_redraw()
        self.on_status(f"{'显示' if name in self.visible_names else '隐藏'}波形: {name}", False)

    def _on_series_frame_configure(self, _event) -> None:
        self.series_canvas.configure(scrollregion=self.series_canvas.bbox("all"))

    def _on_series_canvas_configure(self, event) -> None:
        self.series_canvas.itemconfigure(self.series_window, width=event.width)

    def _on_series_canvas_mousewheel(self, event) -> None:
        self.series_canvas.yview_scroll(int(-event.delta / 120), "units")

    def _on_latest_frame_configure(self, _event) -> None:
        self.latest_canvas.configure(scrollregion=self.latest_canvas.bbox("all"))

    def _on_latest_canvas_configure(self, event) -> None:
        self.latest_canvas.itemconfigure(self.latest_window, width=event.width)

    def _on_latest_canvas_mousewheel(self, event) -> None:
        self.latest_canvas.yview_scroll(int(-event.delta / 120), "units")

    def _queue_redraw(self) -> None:
        if self._redraw_job is not None:
            return
        self._redraw_job = self.after(REDRAW_MS, self._run_redraw)

    def _run_redraw(self) -> None:
        self._redraw_job = None
        self.redraw()

    def redraw(self) -> None:
        self.canvas.delete("all")
        self._plot_bounds = None
        self._x_range = None
        self._y_range = None
        self._cached_visible_series = {}

        width = max(self.canvas.winfo_width(), 100)
        height = max(self.canvas.winfo_height(), 100)
        pad_left = 72
        pad_right = 24
        pad_top = 20
        pad_bottom = 52
        plot_left = pad_left
        plot_top = pad_top
        plot_right = width - pad_right
        plot_bottom = height - pad_bottom
        self.canvas.create_rectangle(plot_left, plot_top, plot_right, plot_bottom, outline="#cbd5e1")

        if not self.selected_names:
            self.canvas.create_text(width / 2, height / 2, text="还没有选择任何波形参数，请先在参数页勾选。", fill="#64748b", font=("Segoe UI", 12))
            self.view_var.set("查看窗口: 无数据")
            return

        full_samples: list[tuple[float, float]] = []
        visible_names = [name for name in self.selected_names if name in self.visible_names]
        if not visible_names:
            self.canvas.create_text(width / 2, height / 2, text="当前没有勾选任何可显示的波形，请先在左侧勾选。", fill="#64748b", font=("Segoe UI", 12))
            self.view_var.set("查看窗口: 已全部隐藏")
            return

        for name in visible_names:
            for timestamp, value in self.series_data.get(name, ()):
                if value is not None and math.isfinite(value):
                    full_samples.append((timestamp, value))
        if not full_samples:
            self.canvas.create_text(width / 2, height / 2, text="已选择参数，但暂时还没有收到波形数据。", fill="#64748b", font=("Segoe UI", 12))
            self.view_var.set("查看窗口: 等待数据")
            return

        data_x_min = min(ts for ts, _ in full_samples)
        data_x_max = max(ts for ts, _ in full_samples)
        x_min, x_max = self._resolve_x_range(data_x_min, data_x_max)

        visible_samples: list[tuple[float, float]] = []
        for timestamp, value in full_samples:
            if x_min <= timestamp <= x_max:
                visible_samples.append((timestamp, value))
        if not visible_samples:
            visible_samples = full_samples
            x_min, x_max = data_x_min, data_x_max

        y_min, y_max = self._resolve_y_range(visible_samples)
        self._plot_bounds = (plot_left, plot_top, plot_right, plot_bottom)
        self._x_range = (x_min, x_max)
        self._y_range = (y_min, y_max)
        self.view_var.set(self._build_view_text(x_min, x_max))

        for index in range(5):
            ratio = index / 4
            y = plot_top + (plot_bottom - plot_top) * ratio
            self.canvas.create_line(plot_left, y, plot_right, y, fill="#cbd5e1", dash=(3, 3))
            value = y_max - (y_max - y_min) * ratio
            self.canvas.create_text(plot_left - 8, y, text=self._format_numeric(value), anchor="e", fill="#475569")

        for tick in range(5):
            ratio = tick / 4
            x = plot_left + (plot_right - plot_left) * ratio
            self.canvas.create_line(x, plot_top, x, plot_bottom, fill="#e2e8f0", dash=(3, 3))
            tick_ts = x_min + (x_max - x_min) * ratio
            self.canvas.create_text(x, plot_bottom + 18, text=datetime.fromtimestamp(tick_ts).strftime("%H:%M:%S"), fill="#475569")

        if y_min <= 0.0 <= y_max:
            zero_y = plot_bottom - (0.0 - y_min) / max(y_max - y_min, 1e-9) * (plot_bottom - plot_top)
            self.canvas.create_line(plot_left, zero_y, plot_right, zero_y, fill="#94a3b8", width=1)
            self.canvas.create_text(plot_left - 8, zero_y, text="0", anchor="e", fill="#334155", font=("Segoe UI", 9, "bold"))

        self._draw_markers(plot_left, plot_top, plot_bottom, x_min, x_max)

        latest_points: list[tuple[str, str, float]] = []
        for idx, name in enumerate(visible_names):
            color = SERIES_COLORS[idx % len(SERIES_COLORS)]
            visible_series = [
                (timestamp, value)
                for timestamp, value in self.series_data.get(name, [])
                if x_min <= timestamp <= x_max
            ]
            self._cached_visible_series[name] = visible_series
            if len(visible_series) < 2:
                continue

            points: list[float] = []
            latest_xy: tuple[float, float] | None = None
            active_segment = False
            for timestamp, value in visible_series:
                if value is None or not math.isfinite(value):
                    if active_segment and len(points) >= 4:
                        self.canvas.create_line(*points, fill=color, width=2, smooth=False)
                    points = []
                    active_segment = False
                    continue
                x = plot_left + (timestamp - x_min) / max(x_max - x_min, 1e-9) * (plot_right - plot_left)
                y = plot_bottom - (value - y_min) / max(y_max - y_min, 1e-9) * (plot_bottom - plot_top)
                points.extend((x, y))
                latest_xy = (x, y)
                active_segment = True

            if active_segment and len(points) >= 4:
                self.canvas.create_line(*points, fill=color, width=2, smooth=False)

            if latest_xy is not None:
                last_x, last_y = latest_xy
                self.canvas.create_oval(last_x - 3, last_y - 3, last_x + 3, last_y + 3, fill=color, outline="")
                latest_points.append((name, color, last_y))

        self._draw_view_hint(plot_left, plot_top)

        if self._zoom_rect_start and self._zoom_rect_end:
            self._draw_zoom_rectangle()
        if self._last_hover_index is not None:
            self._draw_hover_overlay(self._last_hover_index)

    def _resolve_x_range(self, data_x_min: float, data_x_max: float) -> tuple[float, float]:
        if abs(data_x_max - data_x_min) < 1e-6:
            return data_x_min - 0.5, data_x_max + 0.5
        source_range = self._frozen_x_range if self._paused_view and self._frozen_x_range is not None else self._manual_range
        if source_range is not None:
            start, end = source_range
            width = max(end - start, MIN_ZOOM_SPAN_SECONDS)
            if start < data_x_min:
                start = data_x_min
                end = start + width
            if end > data_x_max:
                end = data_x_max
                start = end - width
            if start < data_x_min:
                start = data_x_min
            if end <= start:
                end = start + MIN_ZOOM_SPAN_SECONDS
            resolved = (start, end)
            if self._paused_view:
                self._frozen_x_range = resolved
            return resolved
        duration = WINDOW_OPTIONS.get(self.window_var.get(), 30.0)
        if duration is None:
            return data_x_min, data_x_max
        end = data_x_max
        start = max(data_x_min, end - duration)
        return start, end

    def _resolve_y_range(self, visible_samples: list[tuple[float, float]]) -> tuple[float, float]:
        source_range = self._frozen_y_range if self._paused_view and self._frozen_y_range is not None else self._manual_y_range
        if source_range is not None:
            y_min, y_max = source_range
            if y_max <= y_min:
                y_max = y_min + 1.0
            resolved = (y_min, y_max)
            if self._paused_view:
                self._frozen_y_range = resolved
            return resolved
        values = [value for _, value in visible_samples]
        y_min = min(values)
        y_max = max(values)
        if abs(y_max - y_min) < 1e-9:
            y_min -= 1.0
            y_max += 1.0
        else:
            margin = (y_max - y_min) * 0.1
            y_min -= margin
            y_max += margin
        return y_min, y_max

    def _build_view_text(self, x_min: float, x_max: float) -> str:
        mode = "历史查看" if self._paused_view or self._manual_range is not None or self._manual_y_range is not None else "实时跟随"
        return f"查看窗口: {mode} {max(x_max - x_min, 0.0):.1f}s"

    def _draw_view_hint(self, plot_left: float, plot_top: float) -> None:
        self.canvas.create_text(
            plot_left + 6,
            plot_top - 8,
            text="拖动框选区域缩放，Shift+拖动缩放横轴，Ctrl+拖动缩放纵轴，Shift+滚轮横向移动，Ctrl+滚轮纵向移动。",
            anchor="nw",
            fill="#64748b",
            font=("Segoe UI", 9),
        )

    def _draw_value_labels(self, latest_points: list[tuple[str, str, float]], label_x: float, plot_top: float, plot_bottom: float) -> None:
        if not latest_points:
            return
        legend_items = [(name, color) for name, color, _ in latest_points]
        line_height = 18
        padding = 8
        max_visible = max(1, int((plot_bottom - plot_top - 20) // line_height))
        hidden_count = max(0, len(legend_items) - max_visible)
        visible_items = legend_items[:max_visible]
        box_height = padding * 2 + len(visible_items) * line_height + (line_height if hidden_count else 0)
        box_width = 150
        box_x0 = label_x - 6
        box_y0 = plot_top + 8
        self.canvas.create_rectangle(box_x0, box_y0, box_x0 + box_width, box_y0 + box_height, fill="#ffffff", outline="#cbd5e1")
        self.canvas.create_text(box_x0 + padding, box_y0 + padding - 1, text="图例", anchor="nw", fill="#475569", font=("Segoe UI", 9, "bold"))
        base_y = box_y0 + padding + 16
        for idx, (name, color) in enumerate(visible_items):
            y = base_y + idx * line_height
            self.canvas.create_line(box_x0 + padding, y + 6, box_x0 + padding + 14, y + 6, fill=color, width=3)
            self.canvas.create_text(box_x0 + padding + 20, y + 6, text=name, anchor="w", fill="#0f172a", font=("Segoe UI", 9))
        if hidden_count:
            more_y = base_y + len(visible_items) * line_height
            self.canvas.create_text(box_x0 + padding, more_y + 6, text=f"还有 {hidden_count} 条", anchor="w", fill="#64748b", font=("Segoe UI", 9))

    def _draw_markers(self, plot_left: float, plot_top: float, plot_bottom: float, x_min: float, x_max: float) -> None:
        plot_right = self._plot_bounds[2] if self._plot_bounds else plot_left
        for timestamp, label in self.markers:
            if timestamp < x_min or timestamp > x_max:
                continue
            x = plot_left + (timestamp - x_min) / max(x_max - x_min, 1e-9) * (plot_right - plot_left)
            self.canvas.create_line(x, plot_top, x, plot_bottom, fill="#f59e0b", dash=(2, 4), width=2)
            self.canvas.create_text(x + 4, plot_top + 6, text=label, anchor="nw", fill="#b45309", font=("Segoe UI", 9, "bold"))

    def _draw_zoom_rectangle(self) -> None:
        if not self._zoom_rect_start or not self._zoom_rect_end:
            return
        x0, y0 = self._zoom_rect_start
        x1, y1 = self._zoom_rect_end
        self.canvas.create_rectangle(x0, y0, x1, y1, outline="#2563eb", dash=(4, 2), width=2)

    def _on_window_changed(self, *_args) -> None:
        if self._manual_range is None and not self._paused_view:
            self._queue_redraw()

    def _on_show_all_shortcut(self, _event) -> None:
        self.show_all()

    def _on_apply_period_shortcut(self, _event) -> str:
        self.on_apply_period()
        return "break"

    def _on_toggle_run_shortcut(self, _event) -> str:
        self.on_toggle_run()
        return "break"

    def _on_pause_shortcut(self, _event) -> str:
        self.toggle_pause_view()
        return "break"

    def _on_back_to_live_shortcut(self, _event) -> str:
        self.back_to_live()
        return "break"

    def _on_clear_shortcut(self, _event) -> str:
        self.on_clear()
        return "break"

    def _on_export_shortcut(self, _event) -> str:
        self.export_waveform_file()
        return "break"

    def _on_import_shortcut(self, _event) -> str:
        self.import_waveform_file()
        return "break"

    def _on_marker_shortcut(self, _event) -> str:
        self.add_marker()
        return "break"

    def _on_alt_press(self, _event) -> None:
        if self._alt_pressed:
            return
        self._alt_pressed = True
        if self._last_hover_index is not None:
            self._queue_redraw()

    def _on_alt_release(self, _event) -> None:
        if not self._alt_pressed:
            return
        self._alt_pressed = False
        if self._last_hover_index is not None:
            self._queue_redraw()

    def _on_mousewheel(self, event) -> None:
        if not self._plot_bounds or not self._x_range or not self._y_range:
            return
        plot_left, plot_top, plot_right, plot_bottom = self._plot_bounds
        if not (plot_left <= event.x <= plot_right and plot_top <= event.y <= plot_bottom):
            return
        delta_sign = -1 if event.delta > 0 else 1
        if event.state & SHIFT_MASK:
            self._enter_manual_view()
            x_min, x_max = self._x_range
            span = max(x_max - x_min, MIN_ZOOM_SPAN_SECONDS)
            offset = span * 0.12 * delta_sign
            self._manual_range = (x_min + offset, x_max + offset)
            self._frozen_x_range = self._manual_range
            self._manual_y_range = self._y_range
            self._frozen_y_range = self._y_range
            self._queue_redraw()
        elif event.state & CTRL_MASK:
            self._enter_manual_view()
            y_min, y_max = self._y_range
            span = max(y_max - y_min, MIN_ZOOM_SPAN_VALUE)
            offset = span * 0.12 * delta_sign
            self._manual_y_range = (y_min + offset, y_max + offset)
            self._frozen_y_range = self._manual_y_range
            self._queue_redraw()

    def _on_drag_start(self, event) -> None:
        if not self._plot_bounds or not self._x_range or not self._y_range:
            return
        plot_left, plot_top, plot_right, plot_bottom = self._plot_bounds
        if not (plot_left <= event.x <= plot_right and plot_top <= event.y <= plot_bottom):
            return
        self._drag_anchor = (event.x, event.y)
        self._drag_start_x_range = self._x_range
        self._drag_start_y_range = self._y_range
        if event.state & SHIFT_MASK:
            self._drag_mode = "xzoom"
            self._drag_last_x = event.x
        elif event.state & CTRL_MASK:
            self._drag_mode = "yzoom"
            self._drag_last_x = None
        else:
            self._drag_mode = "rect"
            self._zoom_rect_start = (event.x, event.y)
            self._zoom_rect_end = (event.x, event.y)
            self._drag_last_x = None
        self.canvas.focus_set()

    def _on_drag_move(self, event) -> None:
        if self._drag_mode == "rect" and self._zoom_rect_start is not None:
            self._zoom_rect_end = (event.x, event.y)
            self._queue_redraw()
            return
        if not self._plot_bounds:
            return
        plot_left, plot_top, plot_right, plot_bottom = self._plot_bounds
        if self._drag_mode == "xzoom" and self._drag_anchor and self._drag_start_x_range:
            anchor_x, _ = self._drag_anchor
            start_min, start_max = self._drag_start_x_range
            span = max(start_max - start_min, MIN_ZOOM_SPAN_SECONDS)
            anchor_ratio = min(max((anchor_x - plot_left) / max(plot_right - plot_left, 1), 0.0), 1.0)
            anchor_value = start_min + span * anchor_ratio
            delta_x = event.x - anchor_x
            scale = math.exp(-delta_x / 240.0)
            new_span = max(span * scale, MIN_ZOOM_SPAN_SECONDS)
            self._enter_manual_view()
            self._manual_range = (
                anchor_value - new_span * anchor_ratio,
                anchor_value + new_span * (1.0 - anchor_ratio),
            )
            self._frozen_x_range = self._manual_range
            self._manual_y_range = self._drag_start_y_range
            self._frozen_y_range = self._drag_start_y_range
        elif self._drag_mode == "yzoom" and self._drag_anchor and self._drag_start_y_range:
            _, anchor_y = self._drag_anchor
            start_min, start_max = self._drag_start_y_range
            span = max(start_max - start_min, MIN_ZOOM_SPAN_VALUE)
            anchor_ratio = min(max((anchor_y - plot_top) / max(plot_bottom - plot_top, 1), 0.0), 1.0)
            anchor_value = start_max - span * anchor_ratio
            delta_y = event.y - anchor_y
            scale = math.exp(delta_y / 240.0)
            new_span = max(span * scale, MIN_ZOOM_SPAN_VALUE)
            self._enter_manual_view()
            new_max = anchor_value + new_span * anchor_ratio
            new_min = anchor_value - new_span * (1.0 - anchor_ratio)
            self._manual_y_range = (new_min, new_max)
            self._frozen_y_range = self._manual_y_range
        self._queue_redraw()

    def _on_drag_end(self, _event) -> None:
        self._drag_last_x = None
        if self._drag_mode == "rect" and self._zoom_rect_start is not None and self._zoom_rect_end is not None:
            self._apply_rect_zoom()
        self._drag_mode = None
        self._drag_anchor = None
        self._drag_start_x_range = None
        self._drag_start_y_range = None
        self._zoom_rect_start = None
        self._zoom_rect_end = None
        self._queue_redraw()

    def _apply_rect_zoom(self) -> None:
        if not self._plot_bounds or not self._x_range or not self._y_range:
            return
        if not self._zoom_rect_start or not self._zoom_rect_end:
            return
        plot_left, plot_top, plot_right, plot_bottom = self._plot_bounds
        x0, y0 = self._zoom_rect_start
        x1, y1 = self._zoom_rect_end
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        if dx < 8 and dy < 8:
            return

        x0 = min(max(x0, plot_left), plot_right)
        x1 = min(max(x1, plot_left), plot_right)
        y0 = min(max(y0, plot_top), plot_bottom)
        y1 = min(max(y1, plot_top), plot_bottom)

        self._enter_manual_view()

        x_min, x_max = self._x_range
        start_ratio = (min(x0, x1) - plot_left) / max(plot_right - plot_left, 1)
        end_ratio = (max(x0, x1) - plot_left) / max(plot_right - plot_left, 1)
        new_start = x_min + (x_max - x_min) * start_ratio
        new_end = x_min + (x_max - x_min) * end_ratio
        if new_end - new_start >= MIN_ZOOM_SPAN_SECONDS:
            self._manual_range = (new_start, new_end)
            self._frozen_x_range = self._manual_range

        y_min, y_max = self._y_range
        top_ratio = (min(y0, y1) - plot_top) / max(plot_bottom - plot_top, 1)
        bottom_ratio = (max(y0, y1) - plot_top) / max(plot_bottom - plot_top, 1)
        new_y_max = y_max - (y_max - y_min) * top_ratio
        new_y_min = y_max - (y_max - y_min) * bottom_ratio
        if new_y_max - new_y_min >= MIN_ZOOM_SPAN_VALUE:
            self._manual_y_range = (new_y_min, new_y_max)
            self._frozen_y_range = self._manual_y_range

    def _enter_manual_view(self) -> None:
        self._paused_view = True
        self.pause_button_text.set("继续显示")

    def _on_canvas_motion(self, event) -> None:
        if self._zoom_rect_start is not None:
            self._zoom_rect_end = (event.x, event.y)
            self._queue_redraw()
            return
        if not self._plot_bounds or not self._x_range:
            return
        plot_left, _, plot_right, _ = self._plot_bounds
        if event.x < plot_left or event.x > plot_right:
            return
        index = self._find_hover_index(event.x)
        if index is None or index == self._last_hover_index:
            return
        self._last_hover_index = index
        self.redraw()

    def _on_canvas_leave(self, _event) -> None:
        if self._zoom_rect_start is not None:
            return
        self._last_hover_index = None
        self.cursor_var.set("把鼠标移动到图上即可查看该时刻的数据")
        self.redraw()

    def _find_hover_index(self, canvas_x: float) -> int | None:
        reference = self._reference_series()
        if not reference or not self._plot_bounds or not self._x_range:
            return None
        plot_left, _, plot_right, _ = self._plot_bounds
        x_min, x_max = self._x_range
        ratio = (canvas_x - plot_left) / max(plot_right - plot_left, 1)
        target_ts = x_min + (x_max - x_min) * ratio
        timestamps = [timestamp for timestamp, _ in reference]
        index = bisect_left(timestamps, target_ts)
        if index <= 0:
            return 0
        if index >= len(timestamps):
            return len(timestamps) - 1
        before = timestamps[index - 1]
        after = timestamps[index]
        return index - 1 if abs(target_ts - before) <= abs(after - target_ts) else index

    def _reference_series(self) -> list[tuple[float, float | None]] | None:
        for name in self.selected_names:
            visible = self._cached_visible_series.get(name)
            if visible:
                return visible
        return None

    def _draw_hover_overlay(self, index: int) -> None:
        reference = self._reference_series()
        if not reference or not self._plot_bounds or not self._x_range or not self._y_range:
            return
        if index < 0 or index >= len(reference):
            return

        plot_left, plot_top, plot_right, plot_bottom = self._plot_bounds
        x_min, x_max = self._x_range
        y_min, y_max = self._y_range
        timestamp = reference[index][0]
        x = plot_left + (timestamp - x_min) / max(x_max - x_min, 1e-9) * (plot_right - plot_left)
        self.canvas.create_line(x, plot_top, x, plot_bottom, fill="#64748b", dash=(4, 4))

        base_text = datetime.fromtimestamp(timestamp).strftime("%H:%M:%S.%f")[:-3]
        lines = [base_text]
        marker_map = self._marker_map()
        if timestamp in marker_map:
            lines.append(f"标记 = {marker_map[timestamp]}")
        point_labels: list[tuple[str, str, str, float]] = []
        visible_names = [name for name in self.selected_names if name in self.visible_names]
        for idx, name in enumerate(visible_names):
            series = self._cached_visible_series.get(name, [])
            sample = self._nearest_sample(series, timestamp)
            if sample is None:
                continue
            _, value = sample
            if value is None or not math.isfinite(value):
                continue
            color = SERIES_COLORS[idx % len(SERIES_COLORS)]
            y = plot_bottom - (value - y_min) / max(y_max - y_min, 1e-9) * (plot_bottom - plot_top)
            self.canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill=color, outline="")
            point_labels.append((name, self._format_numeric(value), color, y))
            if self._alt_pressed:
                lines.append(f"{name} = {self._format_numeric(value)}")

        self.cursor_var.set(" | ".join(lines))
        if self._alt_pressed:
            self._draw_hover_panel(point_labels, lines, plot_left, plot_top, plot_right, plot_bottom)

    def _draw_hover_panel(
        self,
        point_labels: list[tuple[str, str, str, float]],
        lines: list[str],
        plot_left: float,
        plot_top: float,
        plot_right: float,
        plot_bottom: float,
    ) -> None:
        line_height = 18
        padding = 10
        visible_rows = lines[:]
        max_rows = max(3, int((plot_bottom - plot_top - 20) // line_height) - 1)
        hidden_count = max(0, len(visible_rows) - max_rows)
        if hidden_count:
            visible_rows = visible_rows[:max_rows]
            visible_rows.append(f"... 还有 {hidden_count} 项")

        box_width = 190
        box_height = padding * 2 + len(visible_rows) * line_height
        x = max(plot_left + 12, plot_right - box_width - 12)
        y = plot_top + 12
        self.canvas.create_rectangle(x, y, x + box_width, y + box_height, fill="#ffffff", outline="#94a3b8", width=1)
        for i, line in enumerate(visible_rows):
            fill = "#0f172a"
            if "=" in line and i > 0:
                name = line.split("=", 1)[0].strip()
                for label_name, _value_text, color, _row_y in point_labels:
                    if label_name == name:
                        fill = color
                        break
            self.canvas.create_text(x + padding, y + padding + i * line_height, text=line, anchor="nw", fill=fill, font=("Consolas", 9))

    def _draw_alt_value_labels(
        self,
        x: float,
        point_labels: list[tuple[str, str, str, float]],
        plot_right: float,
        plot_top: float,
        plot_bottom: float,
    ) -> None:
        return

    def _nearest_sample(self, series: list[tuple[float, float | None]], target_ts: float) -> tuple[float, float | None] | None:
        if not series:
            return None
        timestamps = [timestamp for timestamp, _ in series]
        index = bisect_left(timestamps, target_ts)
        if index <= 0:
            return series[0]
        if index >= len(series):
            return series[-1]
        before = series[index - 1]
        after = series[index]
        return before if abs(before[0] - target_ts) <= abs(after[0] - target_ts) else after

    def _draw_tooltip_box(self, x: float, y: float, lines: list[str], plot_right: float) -> None:
        if not lines:
            return
        line_height = 18
        padding = 8
        max_chars = max(len(line) for line in lines)
        box_width = min(360, max(160, max_chars * 7 + padding * 2))
        box_height = len(lines) * line_height + padding * 2
        if x + box_width > plot_right:
            x = max(16, plot_right - box_width - 8)
        self.canvas.create_rectangle(x, y, x + box_width, y + box_height, fill="#ffffff", outline="#94a3b8", width=1)
        for i, line in enumerate(lines):
            self.canvas.create_text(x + padding, y + padding + i * line_height, text=line, anchor="nw", fill="#0f172a", font=("Consolas", 9))

    def _format_numeric(self, value: float) -> str:
        return f"{value:.6f}".rstrip("0").rstrip(".")
