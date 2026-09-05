from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import datetime
import json
from pathlib import Path
import math
import time
import tkinter as tk
from tkinter import ttk
from typing import TextIO

from serial_debug_assistant.i18n import I18nManager
from serial_debug_assistant.ui.file_dialogs import ask_open_file, ask_save_file
from serial_debug_assistant.ui.parameter_search import matches_parameter_search
from serial_debug_assistant.ui.wave_windows import WaveformWindowsMixin
from serial_debug_assistant.ui.theme import ACCENT, ACCENT_SOFT, BORDER, BORDER_MUTED, CYAN, FONT_MONO, SUCCESS, SURFACE, SURFACE_ALT, TEXT, TEXT_MUTED


REDRAW_MS = 40
LIST_REFRESH_MS = 120
MIN_ZOOM_SPAN_SECONDS = 0.01
MAX_CUSTOM_WINDOW_SECONDS = 86400.0
MIN_ZOOM_SPAN_VALUE = 1e-6
MAX_POINTS_PER_PIXEL = 3
SHIFT_MASK = 0x0001
CTRL_MASK = 0x0004
ALT_MASK = 0x0008 | 0x20000  # Tk Mod1 and Windows Alt event masks.
ALT_GUARD_BINDTAG = "WaveformAltGuard"
WAVE_FILE_EXTENSION = ".sda_wave"
WAVE_FILE_FORMAT = "serial_debug_assistant.waveform"
WAVE_FILE_VERSION = 1
LIVE_WAVE_FILE_EXTENSION = ".sda_wave_live.jsonl"
LIVE_WAVE_FILE_FORMAT = "serial_debug_assistant.waveform.live"
LIVE_SAVE_FLUSH_SECONDS = 1.0
WINDOW_OPTIONS = {
    "最近10秒": 10.0,
    "最近30秒": 30.0,
    "最近1分钟": 60.0,
    "最近10分钟": 600.0,
    "自定义": None,
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


class WaveformTab(WaveformWindowsMixin, ttk.Frame):
    def __init__(
        self,
        master,
        *,
        on_apply_period,
        on_toggle_run,
        on_clear,
        export_dir: Path,
        on_status,
        i18n: I18nManager,
    ) -> None:
        super().__init__(master, style="Panel.TFrame", padding=12)
        self.i18n = i18n
        self._translatable_widgets: list[tuple[object, str, str]] = []
        self.on_apply_period = on_apply_period
        self.on_toggle_run = on_toggle_run
        self.on_clear = on_clear
        self.export_dir = export_dir
        self.on_status = on_status

        self.period_var = tk.StringVar(value="300")
        self.window_var = tk.StringVar(value=self.i18n.translate_text("最近30秒"))
        self.custom_window_var = tk.StringVar(value="30.0")
        self.marker_var = tk.StringVar()
        self.selected_search_var = tk.StringVar()
        self.select_all_visible_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value=self.i18n.translate_text("当前处于停止状态"))
        self.view_var = tk.StringVar(value=self.i18n.translate_text("查看窗口: 最近30秒"))
        self.cursor_var = tk.StringVar(value=self.i18n.translate_text("把鼠标移动到图上即可查看该时刻的数据"))
        self.run_button_text = tk.StringVar(value=self.i18n.translate_text("开始"))
        self.pause_button_text = tk.StringVar(value=self.i18n.translate_text("暂停显示"))

        self.selected_names: list[str] = []
        self.visible_names: set[str] = set()
        self.latest_values: dict[str, str] = {}
        self.series_data: dict[str, list[tuple[float, float | None]]] = {}
        self._series_timestamps: dict[str, list[float]] = {}
        self._series_timestamp_lengths: dict[str, int] = {}
        self.markers: list[tuple[float, str]] = []
        self.reference_lines: list[tuple[str, float]] = []

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
        self._custom_window_seconds = 30.0
        self._selected_window_key = "最近30秒"
        self._updating_window_var = False
        self._unseen_sample_count = 0
        self._alt_pressed = False
        self._last_hover_index: int | None = None
        self._last_hover_canvas_x: float | None = None
        self._drag_last_x: float | None = None
        self._drag_mode: str | None = None
        self._drag_anchor: tuple[float, float] | None = None
        self._drag_start_x_range: tuple[float, float] | None = None
        self._drag_start_y_range: tuple[float, float] | None = None
        self._drag_started_live = False
        self._zoom_rect_start: tuple[float, float] | None = None
        self._zoom_rect_end: tuple[float, float] | None = None
        self._cached_visible_series: dict[str, list[tuple[float, float | None]]] = {}
        self._cached_visible_timestamps: dict[str, list[float]] = {}
        self._pending_reference_line: str | None = None
        self._preview_reference_value: float | tuple[float, float] | None = None
        self._has_unsaved_changes = False
        self._live_save_handle: TextIO | None = None
        self._live_save_path: Path | None = None
        self._live_save_started_at: str | None = None
        self._live_save_last_flush_at = 0.0
        self._live_save_batch_count = 0
        self._time_axis_mode = "system"

        self._init_plot_windows()
        self._build()
        self._install_alt_guard_bindtags(self)
        self.bind_class(ALT_GUARD_BINDTAG, "<KeyPress-Alt_L>", self._on_alt_press, add=True)
        self.bind_class(ALT_GUARD_BINDTAG, "<KeyPress-Alt_R>", self._on_alt_press, add=True)
        self.bind_class(ALT_GUARD_BINDTAG, "<KeyRelease-Alt_L>", self._on_alt_release, add=True)
        self.bind_class(ALT_GUARD_BINDTAG, "<KeyRelease-Alt_R>", self._on_alt_release, add=True)
        self.bind_class(ALT_GUARD_BINDTAG, "<Alt-KeyPress>", self._on_alt_modified_key, add=True)
        self.bind_class(ALT_GUARD_BINDTAG, "<Alt-KeyRelease>", self._on_alt_modified_key, add=True)
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
        self.bind_all("<KeyPress-h>", self._on_horizontal_reference_shortcut, add=True)
        self.bind_all("<KeyPress-H>", self._on_horizontal_reference_shortcut, add=True)
        self.bind_all("<KeyPress-v>", self._on_vertical_reference_shortcut, add=True)
        self.bind_all("<KeyPress-V>", self._on_vertical_reference_shortcut, add=True)
        self.bind_all("<KeyPress-c>", self._on_cross_reference_shortcut, add=True)
        self.bind_all("<KeyPress-C>", self._on_cross_reference_shortcut, add=True)
        self.bind_all("<Escape>", self._on_cancel_reference_shortcut, add=True)
        self.bind_all("<KeyPress-Alt_L>", self._on_alt_press, add=True)
        self.bind_all("<KeyPress-Alt_R>", self._on_alt_press, add=True)
        self.bind_all("<KeyRelease-Alt_L>", self._on_alt_release, add=True)
        self.bind_all("<KeyRelease-Alt_R>", self._on_alt_release, add=True)
        self.bind_all("<Alt-KeyPress>", self._on_alt_modified_key, add=True)
        self.bind_all("<Alt-KeyRelease>", self._on_alt_modified_key, add=True)
        self.bind_all("<KeyRelease>", self._on_key_release_guard, add=True)

    def _install_alt_guard_bindtags(self, widget: tk.Misc) -> None:
        tags = tuple(widget.bindtags())
        if ALT_GUARD_BINDTAG not in tags:
            widget.bindtags((ALT_GUARD_BINDTAG, *tags))
        for child in widget.winfo_children():
            self._install_alt_guard_bindtags(child)

    def _build(self) -> None:
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        top = ttk.Frame(self, style="Panel.TFrame")
        top.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        for column in range(3):
            top.columnconfigure(column, weight=1)

        heading = ttk.Frame(top, style="Panel.TFrame")
        heading.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        heading.columnconfigure(2, weight=1)
        title = ttk.Label(heading, text=self.i18n.translate_text("参数波形"), font=("Microsoft YaHei UI", 16, "bold"))
        title.grid(row=0, column=0, sticky="w")
        self._remember_text(title, "参数波形")
        ttk.Label(heading, textvariable=self.status_var, style="Muted.TLabel").grid(row=0, column=1, padx=20)
        ttk.Label(heading, textvariable=self.view_var, style="Muted.TLabel").grid(row=0, column=2, sticky="e")
        self.add_window_button = ttk.Button(heading, text=self.i18n.translate_text("新增窗口"), command=self.add_plot_window)
        self.add_window_button.grid(row=0, column=3, padx=(12, 0))
        self._remember_text(self.add_window_button, "新增窗口")

        def group(label: str, column: int) -> ttk.LabelFrame:
            frame = ttk.LabelFrame(top, text=self.i18n.translate_text(label), style="Section.TLabelframe", padding=10)
            frame.grid(row=1, column=column, sticky="nsew", padx=(0, 10 if column < 2 else 0))
            self._remember_text(frame, label)
            return frame

        def button(parent, text, command, row, column, **options):
            widget = ttk.Button(parent, text=self.i18n.translate_text(text), command=command, **options)
            widget.grid(row=row, column=column, sticky="ew", padx=3, pady=3)
            self._remember_text(widget, text)
            return widget

        capture = group("采集控制", 0)
        ttk.Button(capture, textvariable=self.run_button_text, command=self.on_toggle_run, style="Accent.TButton").grid(
            row=0, column=0, sticky="ew", padx=3, pady=3)
        self.pause_view_button = ttk.Button(capture, textvariable=self.pause_button_text, command=self.toggle_pause_view)
        self.pause_view_button.grid(row=0, column=1, sticky="ew", padx=3, pady=3)
        self.back_to_live_button = button(capture, "回到实时 L", self.back_to_live, 0, 2)
        period = ttk.Frame(capture, style="Panel.TFrame")
        period.grid(row=1, column=0, columnspan=2, sticky="w", padx=3, pady=3)
        period_label = ttk.Label(period, text=self.i18n.translate_text("上报周期(ms):"))
        period_label.pack(side="left")
        self._remember_text(period_label, "上报周期(ms):")
        ttk.Entry(period, textvariable=self.period_var, width=7).pack(side="left", padx=(6, 0))
        self.apply_period_button = button(capture, "应用周期 R", self.on_apply_period, 1, 2)
        for column in range(3):
            capture.columnconfigure(column, weight=1)

        view = group("时间窗口", 1)
        view.columnconfigure(0, weight=1)
        window_controls = ttk.Frame(view, style="Panel.TFrame")
        window_controls.grid(row=0, column=0, sticky="w", padx=3, pady=3)
        self.window_combo = ttk.Combobox(
            window_controls, textvariable=self.window_var, values=self._window_option_labels(),
            state="readonly", width=12)
        self.window_combo.grid(row=0, column=0, sticky="w")
        self.custom_window_entry = ttk.Entry(window_controls, textvariable=self.custom_window_var, width=7)
        self.custom_window_entry.grid(row=0, column=1, padx=(8, 4))
        self.custom_window_entry.bind("<Return>", self._apply_custom_window)
        self.custom_window_entry.bind("<FocusOut>", self._apply_custom_window)
        self.custom_window_unit_label = ttk.Label(window_controls, text=self.i18n.translate_text("秒"))
        self.custom_window_unit_label.grid(row=0, column=2)
        self._remember_text(self.custom_window_unit_label, "秒")
        self._update_custom_window_controls()
        self.show_all_button = button(view, "显示全部 F", self.show_all, 0, 1)
        hint = ttk.Label(view, text=self.i18n.translate_text("鼠标定位参考线 · 暂停仅冻结显示"), style="Muted.TLabel")
        hint.grid(row=1, column=0, columnspan=2, sticky="w", padx=3, pady=7)
        self._remember_text(hint, "鼠标定位参考线 · 暂停仅冻结显示")

        tools = group("标记与文件", 2)
        tools.columnconfigure(0, weight=1)
        ttk.Entry(tools, textvariable=self.marker_var, width=12).grid(row=0, column=0, sticky="ew", padx=3, pady=3)
        self.marker_button = button(tools, "添加标记 M", self.add_marker, 0, 1)
        style = ttk.Style(self)
        style.configure("Wave.TMenubutton", background=SURFACE_ALT, foreground=TEXT, padding=(10, 6), bordercolor=BORDER, relief="flat")
        style.map("Wave.TMenubutton", background=[("active", ACCENT_SOFT)])
        self.reference_button = ttk.Menubutton(tools, text=self.i18n.translate_text("参考线"), style="Wave.TMenubutton")
        self.reference_button.grid(row=0, column=2, sticky="ew", padx=3, pady=3)
        self._remember_text(self.reference_button, "参考线")
        self.reference_menu = tk.Menu(self.reference_button, tearoff=False)
        self._reference_menu_labels = ("水平参考线 H", "垂直参考线 V", "十字参考线 C", "清除参考线")
        for label, command in zip(self._reference_menu_labels, (
            self.start_horizontal_reference_line, self.start_vertical_reference_line,
            self.start_cross_reference_line, self.clear_reference_lines,
        )):
            self.reference_menu.add_command(label=self.i18n.translate_text(label), command=command)
        self.reference_button.configure(menu=self.reference_menu)
        self.export_button = button(tools, "导出 Ctrl+E", self.export_waveform_file, 1, 0)
        self.import_button = button(tools, "导入 Ctrl+I", self.import_waveform_file, 1, 1)
        self.clear_button = button(tools, "清空", self.on_clear, 1, 2)

        content_paned = tk.PanedWindow(
            self,
            orient="horizontal",
            sashrelief="flat",
            sashwidth=8,
            bd=0,
            relief="flat",
            bg=BORDER_MUTED,
        )
        content_paned.grid(row=1, column=0, sticky="nsew")

        left = ttk.LabelFrame(content_paned, text=self.i18n.translate_text("已选参数"), style="Section.TLabelframe", padding=10)
        self._remember_text(left, "已选参数")
        left.rowconfigure(3, weight=1)
        left.columnconfigure(0, weight=1)

        intro_label = ttk.Label(left, text=self.i18n.translate_text("拖动参数到波形窗口"), style="Muted.TLabel")
        intro_label.grid(
            row=0,
            column=0,
            sticky="w",
            pady=(0, 8),
        )
        self._remember_text(intro_label, "拖动参数到波形窗口")

        search_row = ttk.Frame(left, style="Panel.TFrame")
        search_row.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        search_row.columnconfigure(1, weight=1)
        search_label = ttk.Label(search_row, text=self.i18n.translate_text("搜索:"), style="Header.TLabel")
        search_label.grid(row=0, column=0, sticky="w")
        self._remember_text(search_label, "搜索:")
        ttk.Entry(search_row, textvariable=self.selected_search_var).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        header = ttk.Frame(left, style="Panel.TFrame")
        header.grid(row=2, column=0, sticky="ew", pady=(0, 4))
        self.select_all_check = ttk.Checkbutton(
            header,
            text=self.i18n.translate_text("全选"),
            variable=self.select_all_visible_var,
            command=self._on_select_all_visible_toggle,
        )
        self.select_all_check.grid(row=0, column=0, padx=(2, 8))
        self._remember_text(self.select_all_check, "全选")
        name_label = ttk.Label(header, text=self.i18n.translate_text("参数名"))
        name_label.grid(row=0, column=1, sticky="w")
        self._remember_text(name_label, "参数名")

        self.series_canvas = tk.Canvas(left, bg=SURFACE_ALT, highlightthickness=1, highlightbackground=BORDER, relief="flat")
        self.series_canvas.grid(row=3, column=0, sticky="nsew")
        self.series_list_frame = tk.Frame(self.series_canvas, bg=SURFACE_ALT)
        self.series_window = self.series_canvas.create_window((0, 0), window=self.series_list_frame, anchor="nw")
        self.series_list_frame.bind("<Configure>", self._on_series_frame_configure)
        self.series_canvas.bind("<Configure>", self._on_series_canvas_configure)
        self.series_canvas.bind("<MouseWheel>", self._on_series_canvas_mousewheel)

        left_scroll = ttk.Scrollbar(left, orient="vertical", command=self.series_canvas.yview)
        left_scroll.grid(row=3, column=1, sticky="ns")
        self.series_canvas.configure(yscrollcommand=left_scroll.set)

        center = ttk.Frame(content_paned, style="Panel.TFrame")
        center.rowconfigure(0, weight=1)
        center.columnconfigure(0, weight=1)

        content_paned.add(left, minsize=200, width=250, stretch="never")
        content_paned.add(center, minsize=480, stretch="always")

        right_paned = tk.PanedWindow(
            center,
            orient="horizontal",
            sashrelief="flat",
            sashwidth=8,
            bd=0,
            relief="flat",
            bg=BORDER_MUTED,
        )
        right_paned.grid(row=0, column=0, sticky="nsew")

        plot_frame = ttk.LabelFrame(right_paned, text=self.i18n.translate_text("实时波形"), style="Section.TLabelframe", padding=10)
        self._remember_text(plot_frame, "实时波形")
        plot_frame.rowconfigure(0, weight=0)
        plot_frame.rowconfigure(1, weight=1)
        plot_frame.columnconfigure(0, weight=1)

        self._build_plot_windows(plot_frame)

        values_paned = tk.PanedWindow(right_paned, orient="vertical", sashwidth=8, bd=0, bg=BORDER_MUTED)
        reference_frame = ttk.LabelFrame(values_paned, text=self.i18n.translate_text("参考线数值"), style="Section.TLabelframe", padding=10)
        self.reference_panel = reference_frame
        self._remember_text(reference_frame, "参考线数值")
        reference_frame.columnconfigure(0, weight=1)
        reference_frame.rowconfigure(1, weight=1)
        self.reference_time_var = tk.StringVar(value=self.i18n.translate_text("等待数据"))
        ttk.Label(reference_frame, textvariable=self.reference_time_var, font=(FONT_MONO, 11)).grid(row=0, column=0, sticky="w", pady=(0, 10))
        self.reference_tree = ttk.Treeview(reference_frame, columns=("name", "value"), show="headings", selectmode="none", height=7)
        self.reference_tree.heading("name", text=self.i18n.translate_text("参数名称"))
        self.reference_tree.heading("value", text=self.i18n.translate_text("数据"))
        self.reference_tree.column("name", width=190, minwidth=120)
        self.reference_tree.column("value", width=100, minwidth=90, anchor="e", stretch=False)
        self.reference_tree.grid(row=1, column=0, sticky="nsew")
        reference_scroll = ttk.Scrollbar(reference_frame, orient="vertical", command=self.reference_tree.yview)
        reference_scroll.grid(row=1, column=1, sticky="ns")
        self.reference_tree.configure(yscrollcommand=reference_scroll.set)

        latest_frame = ttk.LabelFrame(values_paned, text=self.i18n.translate_text("最新值"), style="Section.TLabelframe", padding=10)
        self.latest_panel = latest_frame
        self._remember_text(latest_frame, "最新值")
        latest_frame.rowconfigure(0, weight=1)
        latest_frame.columnconfigure(0, weight=1)

        self.latest_canvas = tk.Canvas(
            latest_frame,
            bg=SURFACE_ALT,
            highlightthickness=1,
            highlightbackground=BORDER,
            relief="flat",
            width=240,
        )
        self.latest_canvas.grid(row=0, column=0, sticky="nsew")
        self.latest_list_frame = tk.Frame(self.latest_canvas, bg=SURFACE_ALT)
        self.latest_window = self.latest_canvas.create_window((0, 0), window=self.latest_list_frame, anchor="nw")
        self.latest_list_frame.bind("<Configure>", self._on_latest_frame_configure)
        self.latest_canvas.bind("<Configure>", self._on_latest_canvas_configure)
        self.latest_canvas.bind("<MouseWheel>", self._on_latest_canvas_mousewheel)

        latest_scroll = ttk.Scrollbar(latest_frame, orient="vertical", command=self.latest_canvas.yview)
        latest_scroll.grid(row=0, column=1, sticky="ns")
        self.latest_canvas.configure(yscrollcommand=latest_scroll.set)

        plot_hint = ttk.Label(plot_frame, text=self.i18n.translate_text("拖动框选缩放 · Shift 调整横轴 · Ctrl 调整纵轴"), style="Muted.TLabel", anchor="w")
        self._remember_text(plot_hint, "拖动框选缩放 · Shift 调整横轴 · Ctrl 调整纵轴")
        plot_hint.grid(
            row=2,
            column=0,
            sticky="ew",
            pady=(8, 0),
        )

        right_paned.add(plot_frame, minsize=420, stretch="always")
        values_paned.add(reference_frame, minsize=160, height=280, stretch="always")
        values_paned.add(latest_frame, minsize=140, stretch="always")
        right_paned.add(values_paned, minsize=280, width=330, stretch="never")
        self.add_plot_window()

    def set_period(self, period_ms: int) -> None:
        self.period_var.set(str(period_ms))

    def set_running(self, running: bool) -> None:
        self.status_var.set(self.i18n.translate_text("当前处于运行状态" if running else "当前处于停止状态"))
        self.run_button_text.set(self.i18n.translate_text("停止" if running else "开始"))

    def set_selected_parameters(self, names: list[str]) -> None:
        previous_names = set(self.selected_names)
        was_all_visible = bool(previous_names) and previous_names <= self.visible_names
        self.selected_names = list(names)
        current_names = set(names)
        self.visible_names &= current_names
        if was_all_visible:
            self.visible_names.update(current_names)
        for name in names:
            self.series_data.setdefault(name, [])
            if name not in self._row_widgets:
                row_var = tk.BooleanVar(value=name in self.visible_names)
                row = tk.Frame(self.series_list_frame, bg=SURFACE_ALT, highlightthickness=0, bd=0)
                checkbox = tk.Checkbutton(
                    row,
                    variable=row_var,
                    bg=SURFACE_ALT,
                    activebackground=SURFACE_ALT,
                    highlightthickness=0,
                    bd=0,
                    relief="flat",
                    command=lambda item=name: self._on_row_toggle(item),
                )
                checkbox.grid(row=0, column=0, padx=(4, 8))
                label = tk.Label(row, text=name, anchor="w", justify="left", wraplength=max(120, self.series_canvas.winfo_width() - 48), bg=SURFACE_ALT, fg=TEXT)
                label.grid(row=0, column=1, sticky="w", padx=(0, 6))
                row.columnconfigure(1, weight=1)
                row.pack(fill="x", padx=2, pady=1)
                for widget in (row, checkbox, label):
                    widget.bind("<MouseWheel>", self._on_series_canvas_mousewheel)
                self._row_vars[name] = row_var
                self._row_widgets[name] = (row, checkbox, label)
                self._bind_parameter_drag(row, name)
                self._bind_parameter_drag(label, name)

        for stale_name in list(self.series_data):
            if stale_name not in current_names:
                self.visible_names.discard(stale_name)
        for stale_name in list(self._row_widgets):
            if stale_name not in current_names:
                row, _check, _label = self._row_widgets.pop(stale_name)
                row.destroy()
                self._row_vars.pop(stale_name, None)

        self._sync_plot_assignments()
        self._refresh_series_order()
        self._update_select_all_visible_state()
        self._queue_list_refresh()
        self._queue_latest_refresh()
        self._queue_redraw()

    def _invalidate_series_cache(self, name: str | None = None) -> None:
        if name is None:
            self._series_timestamps.clear()
            self._series_timestamp_lengths.clear()
            return
        self._series_timestamps.pop(name, None)
        self._series_timestamp_lengths.pop(name, None)

    def _timestamps_for(self, name: str) -> list[float]:
        series = self.series_data.get(name, [])
        cached = self._series_timestamps.get(name)
        if cached is not None and self._series_timestamp_lengths.get(name) == len(series):
            return cached
        timestamps = [timestamp for timestamp, _value in series]
        self._series_timestamps[name] = timestamps
        self._series_timestamp_lengths[name] = len(series)
        return timestamps

    def _series_window_indices(self, name: str, x_min: float, x_max: float) -> tuple[int, int]:
        timestamps = self._timestamps_for(name)
        if not timestamps:
            return 0, 0
        return bisect_left(timestamps, x_min), bisect_right(timestamps, x_max)

    def _downsample_series(
        self,
        series: list[tuple[float, float | None]],
        start: int,
        end: int,
        *,
        plot_width: int,
    ) -> list[tuple[float, float | None]]:
        count = max(0, end - start)
        max_points = max(plot_width * MAX_POINTS_PER_PIXEL, 300)
        if count <= max_points:
            return series[start:end]

        bucket_size = max(1, math.ceil(count / max_points))
        sampled: list[tuple[float, float | None]] = []
        index = start
        while index < end:
            bucket_end = min(index + bucket_size, end)
            first: tuple[float, float | None] | None = None
            last: tuple[float, float | None] | None = None
            min_item: tuple[float, float] | None = None
            max_item: tuple[float, float] | None = None
            has_gap = False
            for item_index in range(index, bucket_end):
                item = series[item_index]
                timestamp, value = item
                if first is None:
                    first = item
                last = item
                if value is None or not math.isfinite(value):
                    has_gap = True
                    continue
                if min_item is None or value < min_item[1]:
                    min_item = (timestamp, value)
                if max_item is None or value > max_item[1]:
                    max_item = (timestamp, value)
            if has_gap:
                sampled.append((series[index][0], None))
            candidates: list[tuple[float, float | None]] = []
            for item in (first, min_item, max_item, last):
                if item is not None and item not in candidates:
                    candidates.append(item)
            sampled.extend(sorted(candidates, key=lambda item: item[0]))
            index = bucket_end
        return sampled

    def update_latest_value(self, name: str, value_text: str) -> None:
        self.latest_values[name] = value_text
        self._queue_list_refresh()
        self._queue_latest_refresh()

    def set_time_axis_mode(self, mode: str) -> None:
        if mode not in {"system", "simulation"}:
            raise ValueError(f"unsupported time axis mode: {mode}")
        if self._time_axis_mode != mode:
            self._time_axis_mode = mode
            self._queue_redraw()

    def _format_time_axis_value(self, value: float, *, milliseconds: bool = False) -> str:
        if self._time_axis_mode == "system":
            pattern = "%H:%M:%S.%f" if milliseconds else "%H:%M:%S"
            text = datetime.fromtimestamp(value).strftime(pattern)
            return text[:-3] if milliseconds else text

        sign = "-" if value < 0.0 else ""
        total_milliseconds = int(round(abs(value) * 1000.0))
        seconds, millis = divmod(total_milliseconds, 1000)
        return f"{sign}{seconds}:{millis:03d}"

    def append_batch(self, batch: dict[str, float], batch_time: float | None = None) -> None:
        timestamp = batch_time if batch_time is not None else datetime.now().timestamp()
        for name, value in batch.items():
            self.series_data.setdefault(name, []).append((timestamp, value))
            self._invalidate_series_cache(name)
            self.latest_values[name] = self._format_numeric(value)
        if batch:
            self._has_unsaved_changes = True
            self._append_realtime_batch(batch, timestamp)
            if self._paused_view:
                self._unseen_sample_count += len(batch)
                if self._x_range is not None:
                    self.view_var.set(self._build_view_text(*self._x_range))
        self._queue_list_refresh()
        self._queue_latest_refresh()
        if not self._paused_view or self._x_range is None:
            self._queue_redraw()

    def clear_plot(self) -> None:
        self._reset_plot_views()
        self.stop_realtime_save(reason="clear waveform")
        for data in self.series_data.values():
            data.clear()
        self._invalidate_series_cache()
        self.latest_values.clear()
        self.markers.clear()
        self.reference_lines.clear()
        self._pending_reference_line = None
        self._preview_reference_value = None
        self._last_hover_index = None
        self._last_hover_canvas_x = None
        self._manual_range = None
        self._manual_y_range = None
        self._frozen_x_range = None
        self._frozen_y_range = None
        self._paused_view = False
        self._unseen_sample_count = 0
        self._alt_pressed = False
        self._drag_last_x = None
        self._drag_mode = None
        self._drag_anchor = None
        self._drag_start_x_range = None
        self._drag_start_y_range = None
        self._drag_started_live = False
        self._zoom_rect_start = None
        self._zoom_rect_end = None
        self._has_unsaved_changes = False
        self.pause_button_text.set(self.i18n.translate_text("暂停显示"))
        self.cursor_var.set(self.i18n.translate_text("把鼠标移动到图上即可查看该时刻的数据"))
        self._queue_list_refresh()
        self._queue_latest_refresh()
        self._queue_redraw()

    def _checkbox_text(self, name: str) -> str:
        return "☑" if name in self.visible_names else "☐"

    def refresh_texts(self) -> None:
        for widget, source_text, option in self._translatable_widgets:
            widget.configure(**{option: self.i18n.translate_text(source_text)})
        for index, label in enumerate(self._reference_menu_labels):
            self.reference_menu.entryconfigure(index, label=self.i18n.translate_text(label))
        self.reference_tree.heading("name", text=self.i18n.translate_text("参数名称"))
        self.reference_tree.heading("value", text=self.i18n.translate_text("数据"))
        self.window_combo.configure(values=self._window_option_labels())
        self._set_window_key(self._window_option_key(self.window_var.get()))
        self.status_var.set(self.i18n.translate_text(self.status_var.get()))
        self.view_var.set(self.i18n.translate_text(self.view_var.get()))
        self.cursor_var.set(self.i18n.translate_text(self.cursor_var.get()))
        self.run_button_text.set(self.i18n.translate_text(self.run_button_text.get()))
        self.pause_button_text.set(self.i18n.translate_text(self.pause_button_text.get()))
        self._queue_latest_refresh()
        self._queue_redraw()

    def _window_option_labels(self) -> tuple[str, ...]:
        return tuple(self.i18n.translate_text(label) for label in WINDOW_OPTIONS.keys())

    def _window_option_key(self, label: str) -> str:
        for key in WINDOW_OPTIONS:
            if label == key or label == self.i18n.translate_text(key):
                return key
        return "最近30秒"

    def _set_window_key(self, key: str) -> None:
        if key not in WINDOW_OPTIONS:
            key = "最近30秒"
        self._selected_window_key = key
        self._updating_window_var = True
        try:
            self.window_var.set(self.i18n.translate_text(key))
        finally:
            self._updating_window_var = False
        self._update_custom_window_controls()

    def _update_custom_window_controls(self) -> None:
        if not hasattr(self, "custom_window_entry"):
            return
        if self._window_option_key(self.window_var.get()) == "自定义":
            self.custom_window_entry.state(["!disabled"])
        else:
            self.custom_window_entry.state(["disabled"])

    def _set_custom_window_span(self, seconds: float, *, switch_option: bool = True) -> None:
        self._custom_window_seconds = min(max(float(seconds), MIN_ZOOM_SPAN_SECONDS), MAX_CUSTOM_WINDOW_SECONDS)
        self.custom_window_var.set(f"{self._custom_window_seconds:.3f}".rstrip("0").rstrip("."))
        if switch_option:
            self._set_window_key("自定义")

    def _apply_custom_window(self, _event=None) -> str | None:
        try:
            seconds = float(self.custom_window_var.get().strip().replace(",", "."))
        except ValueError:
            seconds = 0.0
        if not MIN_ZOOM_SPAN_SECONDS <= seconds <= MAX_CUSTOM_WINDOW_SECONDS:
            self.custom_window_var.set(f"{self._custom_window_seconds:g}")
            self.on_status(
                self.i18n.format_text(
                    "自定义窗口必须在 {minimum} 到 {maximum} 秒之间",
                    minimum=f"{MIN_ZOOM_SPAN_SECONDS:g}",
                    maximum=f"{MAX_CUSTOM_WINDOW_SECONDS:g}",
                ),
                True,
            )
            return "break"
        self._set_custom_window_span(seconds)
        self._activate_live_view()
        self.on_status(self.i18n.format_text("自定义查看窗口已设置为 {seconds} 秒", seconds=f"{seconds:g}"), False)
        self._queue_redraw()
        return "break" if _event is not None else None

    def _activate_live_view(self) -> None:
        self._paused_view = False
        self._manual_range = None
        self._frozen_x_range = None
        self._unseen_sample_count = 0
        self.pause_button_text.set(self.i18n.translate_text("暂停显示"))

    def _enter_history_view(
        self,
        x_range: tuple[float, float] | None = None,
        y_range: tuple[float, float] | None = None,
        *,
        use_custom_window: bool = True,
    ) -> None:
        self._paused_view = True
        self._unseen_sample_count = 0
        if x_range is not None:
            self._manual_range = x_range
            self._frozen_x_range = x_range
            if use_custom_window:
                self._set_custom_window_span(max(x_range[1] - x_range[0], MIN_ZOOM_SPAN_SECONDS))
        if y_range is not None:
            self._manual_y_range = y_range
            self._frozen_y_range = y_range
        self.pause_button_text.set(self.i18n.translate_text("继续显示"))

    def _remember_text(self, widget: object, source_text: str, option: str = "text") -> None:
        self._translatable_widgets.append((widget, source_text, option))

    def toggle_pause_view(self) -> None:
        if self._paused_view:
            if self._window_option_key(self.window_var.get()) == "全部" and self._x_range is not None:
                self._set_custom_window_span(max(self._x_range[1] - self._x_range[0], MIN_ZOOM_SPAN_SECONDS))
            self._activate_live_view()
        else:
            self._enter_history_view(self._x_range, self._y_range, use_custom_window=False)
            self._freeze_plot_y_ranges()
        self._queue_redraw()

    def back_to_live(self) -> None:
        if self._x_range is not None:
            self._set_custom_window_span(max(self._x_range[1] - self._x_range[0], MIN_ZOOM_SPAN_SECONDS))
        self._activate_live_view()
        self._queue_redraw()

    def show_all(self) -> None:
        self._reset_plot_y_ranges()
        self._paused_view = True
        self._unseen_sample_count = 0
        self._manual_range = None
        self._manual_y_range = None
        self._frozen_x_range = None
        self._frozen_y_range = None
        self._set_window_key("全部")
        self.pause_button_text.set(self.i18n.translate_text("继续显示"))
        self.on_status(self.i18n.translate_text("已切换为显示全部波形"), False)
        self._queue_redraw()

    def add_marker(self) -> None:
        timestamp = self._latest_timestamp()
        if timestamp is None:
            self.on_status("当前还没有波形数据可添加标记", True)
            return
        label = self.marker_var.get().strip() or f"标记{len(self.markers) + 1}"
        self.markers.append((timestamp, label))
        self._has_unsaved_changes = True
        self.marker_var.set("")
        self.on_status(f"已添加标记: {label}", False)
        self._queue_redraw()

    def start_horizontal_reference_line(self) -> None:
        self._pending_reference_line = "horizontal"
        self._preview_reference_value = self._y_range[0] if self._y_range else None
        self.on_status("移动鼠标选择水平参考线位置，在波形中单击固定", False)
        self._queue_redraw()

    def start_vertical_reference_line(self) -> None:
        self._pending_reference_line = "vertical"
        self._preview_reference_value = self._x_range[0] if self._x_range else None
        self.on_status("移动鼠标选择垂直参考线位置，在波形中单击固定", False)
        self._queue_redraw()

    def start_cross_reference_line(self) -> None:
        self._pending_reference_line = "cross"
        if self._x_range and self._y_range:
            self._preview_reference_value = (self._x_range[0], self._y_range[0])
        else:
            self._preview_reference_value = None
        self.on_status("移动鼠标同时预览水平和垂直参考线，在波形中单击固定", False)
        self._queue_redraw()

    def clear_reference_lines(self) -> None:
        had_lines = self._clear_plot_reference_lines()
        if had_lines and any(self.series_data.values()):
            self._has_unsaved_changes = True
        if had_lines:
            self.on_status("已清除所有参考线", False)
        else:
            self.on_status("当前没有可清除的参考线", False)
        self._queue_redraw()

    def cancel_pending_reference_line(self) -> bool:
        if self._pending_reference_line is None and self._preview_reference_value is None:
            return False
        self._pending_reference_line = None
        self._preview_reference_value = None
        self.on_status("已取消预放置参考线", False)
        self._queue_redraw()
        return True

    def has_waveform_data(self) -> bool:
        return any(self.series_data.values())

    def has_unsaved_waveform_changes(self) -> bool:
        return self._has_unsaved_changes

    def _default_export_path(self) -> Path:
        self.export_dir.mkdir(parents=True, exist_ok=True)
        return self.export_dir / f"waveform_{datetime.now():%Y%m%d_%H%M%S}{WAVE_FILE_EXTENSION}"

    def _default_live_save_path(self) -> Path:
        self.export_dir.mkdir(parents=True, exist_ok=True)
        return self.export_dir / f"waveform_live_{datetime.now():%Y%m%d_%H%M%S}{LIVE_WAVE_FILE_EXTENSION}"

    def start_realtime_save(self) -> Path:
        if self._live_save_handle is not None and self._live_save_path is not None:
            return self._live_save_path
        self._live_save_path = self._default_live_save_path()
        self._live_save_started_at = datetime.now().isoformat(timespec="seconds")
        self._live_save_batch_count = 0
        self._live_save_last_flush_at = time.monotonic()
        try:
            self._live_save_handle = self._live_save_path.open("a", encoding="utf-8")
        except OSError as exc:
            failed_path = self._live_save_path
            self._live_save_path = None
            self._live_save_started_at = None
            self.on_status(f"实时保存波形文件创建失败: {exc}", True)
            return failed_path
        header = {
            "format": LIVE_WAVE_FILE_FORMAT,
            "version": WAVE_FILE_VERSION,
            "type": "header",
            "started_at": self._live_save_started_at,
            "period_ms": self.period_var.get(),
            "selected_names": self.selected_names,
            "visible_names": sorted(self.visible_names),
        }
        self._write_live_save_line(header)
        self._live_save_handle.flush()
        self.on_status(f"实时保存波形文件: {self._live_save_path}", False)
        return self._live_save_path

    def stop_realtime_save(self, *, reason: str) -> Path | None:
        if self._live_save_handle is None:
            path = self._live_save_path
            self._live_save_path = None
            self._live_save_started_at = None
            return path
        path = self._live_save_path
        try:
            footer = {
                "type": "end",
                "reason": reason,
                "ended_at": datetime.now().isoformat(timespec="seconds"),
                "batch_count": self._live_save_batch_count,
            }
            self._write_live_save_line(footer)
            self._live_save_handle.flush()
        except OSError as exc:
            self.on_status(f"实时保存波形文件关闭失败: {exc}", True)
        finally:
            self._live_save_handle.close()
            self._live_save_handle = None
            self._live_save_path = None
            self._live_save_started_at = None
        return path

    def _write_live_save_line(self, payload: dict[str, object]) -> None:
        if self._live_save_handle is None:
            return
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        self._live_save_handle.write(line + "\n")

    def _append_realtime_batch(self, batch: dict[str, float], timestamp: float) -> None:
        try:
            self.start_realtime_save()
            if self._live_save_handle is None:
                return
            self._write_live_save_line({"type": "batch", "timestamp": timestamp, "values": batch})
            self._live_save_batch_count += 1
            now = time.monotonic()
            if now - self._live_save_last_flush_at >= LIVE_SAVE_FLUSH_SECONDS and self._live_save_handle is not None:
                self._live_save_handle.flush()
                self._live_save_last_flush_at = now
        except OSError as exc:
            self.on_status(f"实时保存波形文件失败: {exc}", True)
            self.stop_realtime_save(reason="write error")

    def _build_export_payload(self) -> dict[str, object]:
        return {
            "format": WAVE_FILE_FORMAT,
            "version": WAVE_FILE_VERSION,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "period_ms": self.period_var.get(),
            "selected_names": self.selected_names,
            "visible_names": sorted(self.visible_names),
            "markers": [{"timestamp": timestamp, "label": label} for timestamp, label in self.markers],
            "reference_lines": [
                {"orientation": orientation, "value": value}
                for orientation, value in self._plot_reference_lines()
            ],
            "series_data": {
                name: [
                    {"timestamp": timestamp, "value": value}
                    for timestamp, value in samples
                ]
                for name, samples in sorted(self.series_data.items(), key=lambda item: item[0].lower())
                if samples
            },
        }

    def save_waveform_file(self, file_path: Path) -> Path:
        payload = self._build_export_payload()
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._has_unsaved_changes = False
        return file_path

    def auto_save_waveform_file(self, *, reason: str) -> Path | None:
        if not self.has_waveform_data():
            self.stop_realtime_save(reason=reason)
            return None
        if not self._has_unsaved_changes:
            self.stop_realtime_save(reason=reason)
            return None
        file_path = self.save_waveform_file(self._default_export_path())
        self.stop_realtime_save(reason=reason)
        self.on_status(f"Waveform file auto-saved ({reason}): {file_path}", False)
        return file_path

    def export_waveform_file(self) -> None:
        if not self.has_waveform_data():
            self.on_status("当前没有可导出的波形数据", True)
            return
        default_path = self._default_export_path()
        path = ask_save_file(
            key="wave_export",
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
        self.save_waveform_file(file_path)
        self.on_status(f"已导出波形文件: {file_path}", False)

    def _read_waveform_payload(self, file_path: Path) -> dict[str, object]:
        text = file_path.read_text(encoding="utf-8")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return self._read_live_waveform_payload(text)

    def _read_live_waveform_payload(self, text: str) -> dict[str, object]:
        selected_names: list[str] = []
        visible_names: list[str] = []
        period_ms = self.period_var.get()
        series_data: dict[str, list[dict[str, float | None]]] = {}
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            item_type = item.get("type")
            if item_type == "header":
                if item.get("format") != LIVE_WAVE_FILE_FORMAT:
                    raise ValueError("live waveform format mismatch")
                selected_names = [str(name) for name in item.get("selected_names", [])]
                visible_names = [str(name) for name in item.get("visible_names", [])]
                period_ms = str(item.get("period_ms", period_ms))
                continue
            if item_type != "batch":
                continue
            try:
                timestamp = float(item["timestamp"])
            except (KeyError, TypeError, ValueError):
                continue
            values = item.get("values", {})
            if not isinstance(values, dict):
                continue
            for name, raw_value in values.items():
                series_name = str(name)
                try:
                    value = float(raw_value)
                except (TypeError, ValueError):
                    value = None
                series_data.setdefault(series_name, []).append({"timestamp": timestamp, "value": value})
        if not series_data:
            raise ValueError("live waveform file contains no samples")
        if not selected_names:
            selected_names = list(series_data.keys())
        if not visible_names:
            visible_names = selected_names
        return {
            "format": WAVE_FILE_FORMAT,
            "version": WAVE_FILE_VERSION,
            "period_ms": period_ms,
            "selected_names": selected_names,
            "visible_names": visible_names,
            "markers": [],
            "reference_lines": [],
            "series_data": series_data,
        }

    def import_waveform_file(self) -> None:
        self.export_dir.mkdir(parents=True, exist_ok=True)
        path = ask_open_file(
            key="wave_import",
            title="导入波形文件",
            initialdir=str(self.export_dir),
            filetypes=[
                ("波形数据文件", f"*{WAVE_FILE_EXTENSION}"),
                ("实时波形文件", f"*{LIVE_WAVE_FILE_EXTENSION}"),
                ("所有文件", "*.*"),
            ],
        )
        if not path:
            self.on_status("已取消导入波形文件", False)
            return

        file_path = Path(path)
        self.stop_realtime_save(reason="import waveform")
        try:
            payload = self._read_waveform_payload(file_path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
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

        self._reset_plot_views()
        self.selected_names = []
        self.visible_names = {str(name) for name in payload.get("visible_names", []) if str(name) in selected_names}
        self.series_data = {}
        self._invalidate_series_cache()
        self.latest_values.clear()
        self.markers = []
        self.reference_lines = []
        self._pending_reference_line = None
        self._preview_reference_value = None
        self._last_hover_index = None
        self._last_hover_canvas_x = None
        self._manual_range = None
        self._manual_y_range = None
        self._frozen_x_range = None
        self._frozen_y_range = None
        self._paused_view = False
        self._unseen_sample_count = 0
        self._drag_started_live = False
        self.pause_button_text.set("暂停显示")
        self.cursor_var.set("把鼠标移动到图上即可查看该时刻的数据")

        for marker in payload.get("markers", []):
            try:
                timestamp = float(marker["timestamp"])
                label = str(marker["label"])
            except (KeyError, TypeError, ValueError):
                continue
            self.markers.append((timestamp, label))

        for line in payload.get("reference_lines", []):
            try:
                orientation = str(line["orientation"])
                value = float(line["value"])
            except (KeyError, TypeError, ValueError):
                continue
            if orientation in {"horizontal", "vertical"}:
                self.reference_lines.append((orientation, value))

        period_ms = str(payload.get("period_ms", self.period_var.get()))
        if period_ms.isdigit():
            self.period_var.set(period_ms)

        self.set_selected_parameters(selected_names)
        for name, samples in imported_series.items():
            self.series_data[name] = samples
            self._invalidate_series_cache(name)
            for _timestamp, value in reversed(samples):
                if value is not None and math.isfinite(value):
                    self.latest_values[name] = self._format_numeric(value)
                    break

        self._queue_list_refresh()
        self._queue_latest_refresh()
        self._queue_redraw()
        self._has_unsaved_changes = False
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
        return matches_parameter_search(name, self.selected_search_var.get())

    def _queue_list_refresh(self) -> None:
        if self._list_refresh_job is not None:
            return
        self._list_refresh_job = self.after(LIST_REFRESH_MS, self._run_list_refresh)

    def _run_list_refresh(self) -> None:
        self._list_refresh_job = None
        self._refresh_series_order()
        for name in self.selected_names:
            self._refresh_row_widget(name)
        self._update_select_all_visible_state()

    def _on_selected_search_changed(self, *_args) -> None:
        self._queue_list_refresh()

    def _update_select_all_visible_state(self) -> None:
        selected = set(self.selected_names)
        all_visible = bool(selected) and selected <= self.visible_names
        self.select_all_visible_var.set(all_visible)

    def _on_select_all_visible_toggle(self) -> None:
        selected = set(self.selected_names)
        if not selected:
            self.select_all_visible_var.set(False)
            return
        if self.select_all_visible_var.get():
            self.visible_names.update(selected)
            message = "已切换为显示全部波形"
        else:
            self.visible_names.difference_update(selected)
            message = "已隐藏全部波形"
        for name in self.selected_names:
            self._refresh_row_widget(name)
        self._update_select_all_visible_state()
        self._last_hover_index = None
        self.cursor_var.set(self.i18n.translate_text("把鼠标移动到图上即可查看该时刻的数据"))
        self._queue_latest_refresh()
        self._queue_redraw()
        self.on_status(self.i18n.translate_text(message), False)

    def _queue_latest_refresh(self) -> None:
        if self._latest_refresh_job is not None:
            return
        self._latest_refresh_job = self.after(LIST_REFRESH_MS, self._run_latest_refresh)

    def _run_latest_refresh(self) -> None:
        self._latest_refresh_job = None
        visible_names = [name for name in self.selected_names if name in self.visible_names and name in self._plot_assignments]
        if not visible_names:
            for stale_name, widgets in list(self._latest_widgets.items()):
                widgets[0].destroy()
                del self._latest_widgets[stale_name]
            if self._latest_empty_label is None:
                self._latest_empty_label = tk.Label(
                    self.latest_list_frame,
                    text=self.i18n.translate_text("当前没有勾选显示的参数。"),
                    anchor="w",
                    justify="left",
                    bg=SURFACE_ALT,
                    fg=TEXT_MUTED,
                )
                self._latest_empty_label.pack(fill="x", padx=8, pady=8)
            return
        if self._latest_empty_label is not None:
            self._latest_empty_label.destroy()
            self._latest_empty_label = None

        for idx, name in enumerate(visible_names):
            color = self._series_color(name)
            value_text = self.latest_values.get(name, "-")
            widgets = self._latest_widgets.get(name)
            if widgets is None:
                row = tk.Frame(self.latest_list_frame, bg=SURFACE_ALT, highlightthickness=0, bd=0)
                swatch = tk.Canvas(row, width=12, height=12, bg=SURFACE_ALT, highlightthickness=0, bd=0)
                swatch.grid(row=0, column=0, padx=(0, 6), sticky="n")
                name_label = tk.Label(
                    row,
                    text=name,
                    anchor="w",
                    justify="left",
                    bg=SURFACE_ALT,
                    fg=TEXT,
                    wraplength=270,
                )
                name_label.grid(row=0, column=1, sticky="w")
                value_label = tk.Label(
                    row,
                    text=value_text,
                    anchor="e",
                    justify="right",
                    bg=SURFACE_ALT,
                    fg=TEXT,
                    font=(FONT_MONO, 10),
                )
                value_label.grid(row=1, column=1, sticky="w", pady=(1, 0))
                row.columnconfigure(1, weight=1)
                for widget in (row, swatch, name_label, value_label):
                    widget.bind("<MouseWheel>", self._on_latest_canvas_mousewheel)
                self._latest_widgets[name] = (row, swatch, name_label, value_label)
                widgets = self._latest_widgets[name]
            row, swatch, name_label, value_label = widgets
            row.pack_forget()
            row.pack(fill="x", padx=10, pady=4)
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
        bg = ACCENT_SOFT if visible else SURFACE_ALT
        fg = TEXT if visible else TEXT_MUTED
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
        self._update_select_all_visible_state()
        self._last_hover_index = None
        self.cursor_var.set(self.i18n.translate_text("把鼠标移动到图上即可查看该时刻的数据"))
        self._queue_latest_refresh()
        self._queue_redraw()
        action = self.i18n.translate_text("显示" if name in self.visible_names else "隐藏")
        self.on_status(f"{action}{self.i18n.translate_text('波形')}: {name}", False)

    def _on_series_frame_configure(self, _event) -> None:
        self.series_canvas.configure(scrollregion=self.series_canvas.bbox("all"))

    def _on_series_canvas_configure(self, event) -> None:
        self.series_canvas.itemconfigure(self.series_window, width=event.width)
        for _row, _checkbox, label in self._row_widgets.values():
            label.configure(wraplength=max(120, event.width - 48))

    def _on_series_canvas_mousewheel(self, event) -> None:
        self.series_canvas.yview_scroll(int(-event.delta / 120), "units")

    def _on_latest_frame_configure(self, _event) -> None:
        self.latest_canvas.configure(scrollregion=self.latest_canvas.bbox("all"))

    def _on_latest_canvas_configure(self, event) -> None:
        self.latest_canvas.itemconfigure(self.latest_window, width=event.width)
        for _row, _swatch, label, _value in self._latest_widgets.values():
            label.configure(wraplength=max(120, event.width - 44))

    def _on_latest_canvas_mousewheel(self, event) -> None:
        self.latest_canvas.yview_scroll(int(-event.delta / 120), "units")

    def _queue_redraw(self) -> None:
        if self._redraw_job is not None:
            return
        self._redraw_job = self.after(REDRAW_MS, self._run_redraw)

    def _run_redraw(self) -> None:
        self._redraw_job = None
        self.redraw()

    def _redraw_plot(self) -> None:
        self.canvas.delete("all")
        self._plot_bounds = None
        self._x_range = None
        self._y_range = None
        self._cached_visible_series = {}
        self._cached_visible_timestamps = {}

        width = max(self.canvas.winfo_width(), 100)
        height = max(self.canvas.winfo_height(), 100)
        pad_left = 72
        pad_right = 24
        pad_top = 20
        pad_bottom = 14
        plot_left = pad_left
        plot_top = pad_top
        plot_right = width - pad_right
        plot_bottom = height - pad_bottom
        self.canvas.create_rectangle(plot_left, plot_top, plot_right, plot_bottom, outline=BORDER_MUTED)
        self._plot_bounds = (plot_left, plot_top, plot_right, plot_bottom)
        self._x_range = self._shared_x_range
        self._draw_shared_cursor()

        if not self.selected_names:
            self._draw_hover_panel([], [], plot_left, plot_top, plot_right, plot_bottom)
            self.canvas.create_text(width / 2, height / 2, text=self.i18n.translate_text("还没有选择任何波形参数，请先在参数页勾选。"), fill=TEXT_MUTED, font=("Segoe UI", 12))
            self.view_var.set(self.i18n.translate_text("查看窗口: 无数据"))
            return

        visible_names = self._visible_plot_names()
        if not visible_names:
            self.canvas.create_text(width / 2, height / 2, text=self.i18n.translate_text("拖动参数到此窗口"), fill=TEXT_MUTED, font=("Segoe UI", 12))
            self._draw_hover_panel([], [], plot_left, plot_top, plot_right, plot_bottom)
            self.view_var.set(self.i18n.translate_text("查看窗口: 已全部隐藏"))
            return

        if self._shared_x_range is None:
            self._draw_hover_panel([], [], plot_left, plot_top, plot_right, plot_bottom)
            self.canvas.create_text(width / 2, height / 2, text=self.i18n.translate_text("已选择参数，但暂时还没有收到波形数据。"), fill=TEXT_MUTED, font=("Segoe UI", 12))
            self.view_var.set(self.i18n.translate_text("查看窗口: 等待数据"))
            return

        x_min, x_max = self._shared_x_range

        plot_width = max(int(plot_right - plot_left), 1)
        per_series_windows: dict[str, tuple[int, int, list[tuple[float, float | None]]]] = {}
        visible_samples: list[tuple[float, float]] = []
        for name in visible_names:
            series = self.series_data.get(name, [])
            start, end = self._series_window_indices(name, x_min, x_max)
            if start >= end:
                continue
            sampled = self._downsample_series(series, start, end, plot_width=plot_width)
            per_series_windows[name] = (start, end, sampled)
            visible_samples.extend(
                (timestamp, value)
                for timestamp, value in sampled
                if value is not None and math.isfinite(value)
            )
        if not visible_samples:
            self.canvas.create_text(width / 2, height / 2, text=self.i18n.translate_text("当前时间范围内无数据"), fill=TEXT_MUTED, font=("Segoe UI", 12))
            self._draw_hover_panel([], [], plot_left, plot_top, plot_right, plot_bottom)
            self.view_var.set("View window: waiting for data")
            return

        y_min, y_max = self._resolve_y_range(visible_samples)
        self._plot_bounds = (plot_left, plot_top, plot_right, plot_bottom)
        self._x_range = (x_min, x_max)
        self._y_range = (y_min, y_max)
        self.view_var.set(self._build_view_text(x_min, x_max))

        for index in range(5):
            ratio = index / 4
            y = plot_top + (plot_bottom - plot_top) * ratio
            self.canvas.create_line(plot_left, y, plot_right, y, fill=BORDER_MUTED, dash=(3, 3))
            value = y_max - (y_max - y_min) * ratio
            self.canvas.create_text(plot_left - 8, y, text=self._format_numeric(value), anchor="e", fill=TEXT_MUTED)

        for tick in range(5):
            ratio = tick / 4
            x = plot_left + (plot_right - plot_left) * ratio
            self.canvas.create_line(x, plot_top, x, plot_bottom, fill=BORDER_MUTED, dash=(3, 3))

        if y_min <= 0.0 <= y_max:
            zero_y = plot_bottom - (0.0 - y_min) / max(y_max - y_min, 1e-9) * (plot_bottom - plot_top)
            self.canvas.create_line(plot_left, zero_y, plot_right, zero_y, fill="#94a3b8", width=1)
            self.canvas.create_text(plot_left - 8, zero_y, text="0", anchor="e", fill=TEXT, font=("Segoe UI", 9, "bold"))

        self._draw_markers(plot_left, plot_top, plot_bottom, x_min, x_max)
        self._draw_reference_lines(plot_left, plot_top, plot_right, plot_bottom, x_min, x_max, y_min, y_max)

        latest_points: list[tuple[str, str, float]] = []
        for idx, name in enumerate(visible_names):
            color = self._series_color(name)
            series = self.series_data.get(name, [])
            start, end, draw_series = per_series_windows.get(name, (0, 0, []))
            if end - start <= max(plot_width * MAX_POINTS_PER_PIXEL, 300):
                hover_series = series[start:end]
            else:
                hover_series = draw_series
            self._cached_visible_series[name] = hover_series
            self._cached_visible_timestamps[name] = [timestamp for timestamp, _value in hover_series]
            if len(draw_series) < 2:
                continue

            points: list[float] = []
            latest_xy: tuple[float, float] | None = None
            active_segment = False
            for timestamp, value in draw_series:
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

        if self._zoom_rect_start and self._zoom_rect_end:
            self._draw_zoom_rectangle()
        # Recompute against the current window even when the pointer is stationary.
        self._last_hover_canvas_x = plot_left + (plot_right - plot_left) * self._shared_cursor_ratio
        self._last_hover_index = self._find_hover_index(self._last_hover_canvas_x)
        if self._last_hover_index is not None:
            self._draw_hover_overlay(self._last_hover_index)

    def _resolve_x_range(self, data_x_min: float, data_x_max: float) -> tuple[float, float]:
        if abs(data_x_max - data_x_min) < 1e-6:
            return data_x_min - 0.5, data_x_max + 0.5
        source_range = self._frozen_x_range if self._paused_view else None
        if source_range is None and self._paused_view:
            source_range = self._manual_range
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
        window_key = self._window_option_key(self.window_var.get())
        duration = self._custom_window_seconds if window_key == "自定义" else WINDOW_OPTIONS.get(window_key, 30.0)
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
        mode = self.i18n.translate_text("历史查看" if self._paused_view else "实时跟随")
        if self._paused_view and self._unseen_sample_count:
            return self.i18n.format_text(
                "查看窗口: {mode} {seconds:.1f}s，已接收 {count} 个新数据点",
                mode=mode,
                seconds=max(x_max - x_min, 0.0),
                count=self._unseen_sample_count,
            )
        return self.i18n.format_text("查看窗口: {mode} {seconds:.1f}s", mode=mode, seconds=max(x_max - x_min, 0.0))

    def _draw_view_hint(self, plot_left: float, plot_top: float) -> None:
        self.canvas.create_text(
            plot_left + 6,
            plot_top - 8,
            text=self.i18n.translate_text("拖动框选区域缩放，Shift+拖动缩放横轴，Ctrl+拖动缩放纵轴，Shift+滚轮横向移动，Ctrl+滚轮纵向移动。"),
            anchor="nw",
            fill=TEXT_MUTED,
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
        self.canvas.create_rectangle(box_x0, box_y0, box_x0 + box_width, box_y0 + box_height, fill=SURFACE, outline=BORDER_MUTED)
        self.canvas.create_text(box_x0 + padding, box_y0 + padding - 1, text=self.i18n.translate_text("图例"), anchor="nw", fill=TEXT_MUTED, font=("Segoe UI", 9, "bold"))
        base_y = box_y0 + padding + 16
        for idx, (name, color) in enumerate(visible_items):
            y = base_y + idx * line_height
            self.canvas.create_line(box_x0 + padding, y + 6, box_x0 + padding + 14, y + 6, fill=color, width=3)
            self.canvas.create_text(box_x0 + padding + 20, y + 6, text=name, anchor="w", fill=TEXT, font=("Segoe UI", 9))
        if hidden_count:
            more_y = base_y + len(visible_items) * line_height
            self.canvas.create_text(box_x0 + padding, more_y + 6, text=self.i18n.format_text("还有 {count} 条", count=hidden_count), anchor="w", fill=TEXT_MUTED, font=("Segoe UI", 9))

    def _draw_markers(self, plot_left: float, plot_top: float, plot_bottom: float, x_min: float, x_max: float) -> None:
        plot_right = self._plot_bounds[2] if self._plot_bounds else plot_left
        for timestamp, label in self.markers:
            if timestamp < x_min or timestamp > x_max:
                continue
            x = plot_left + (timestamp - x_min) / max(x_max - x_min, 1e-9) * (plot_right - plot_left)
            self.canvas.create_line(x, plot_top, x, plot_bottom, fill="#f59e0b", dash=(2, 4), width=2)
            self.canvas.create_text(x + 4, plot_top + 6, text=label, anchor="nw", fill="#b45309", font=("Segoe UI", 9, "bold"))

    def _draw_reference_lines(
        self,
        plot_left: float,
        plot_top: float,
        plot_right: float,
        plot_bottom: float,
        x_min: float,
        x_max: float,
        y_min: float,
        y_max: float,
    ) -> None:
        lines = self._plot_reference_lines()
        fixed_count = len(lines)
        preview_lines: list[tuple[str, float]] = []
        if self._pending_reference_line and self._preview_reference_value is not None:
            if self._pending_reference_line == "cross":
                if isinstance(self._preview_reference_value, tuple):
                    preview_x, preview_y = self._preview_reference_value
                    preview_lines.append(("vertical", preview_x))
                    preview_lines.append(("horizontal", preview_y))
            elif isinstance(self._preview_reference_value, (int, float)):
                preview_lines.append((self._pending_reference_line, float(self._preview_reference_value)))
        lines.extend(preview_lines)

        for index, (orientation, value) in enumerate(lines):
            is_preview = index >= fixed_count
            if orientation == "vertical":
                if value < x_min or value > x_max:
                    continue
                x = self._timestamp_to_canvas_x(value, plot_left, plot_right, x_min, x_max)
                self.canvas.create_line(
                    x,
                    plot_top,
                    x,
                    plot_bottom,
                    fill=CYAN if is_preview else SUCCESS,
                    dash=(6, 4),
                    width=2,
                )
                label = f"参考 {self._format_time_axis_value(value, milliseconds=True)}"
                if is_preview:
                    label = f"预览 {self._format_time_axis_value(value, milliseconds=True)}"
                self.canvas.create_text(x + 4, plot_top + 18, text=label, anchor="nw", fill=SUCCESS, font=("Consolas", 9))
            elif orientation == "horizontal":
                if value < y_min or value > y_max:
                    continue
                y = self._value_to_canvas_y(value, plot_top, plot_bottom, y_min, y_max)
                self.canvas.create_line(
                    plot_left,
                    y,
                    plot_right,
                    y,
                    fill="#38bdf8" if is_preview else "#0369a1",
                    dash=(6, 4),
                    width=2,
                )
                label = f"参考 {self._format_numeric(value)}"
                if is_preview:
                    label = f"预览 {self._format_numeric(value)}"
                self.canvas.create_text(plot_left + 6, y - 8, text=label, anchor="sw", fill="#0369a1", font=("Consolas", 9))

    def _draw_zoom_rectangle(self) -> None:
        if not self._zoom_rect_start or not self._zoom_rect_end:
            return
        x0, y0 = self._zoom_rect_start
        x1, y1 = self._zoom_rect_end
        self.canvas.create_rectangle(x0, y0, x1, y1, outline=ACCENT, dash=(4, 2), width=2)

    def _on_window_changed(self, *_args) -> None:
        if self._updating_window_var:
            return
        window_key = self._window_option_key(self.window_var.get())
        self._update_custom_window_controls()
        if window_key == self._selected_window_key:
            return
        self._selected_window_key = window_key
        if window_key == "全部":
            self._paused_view = True
            self._unseen_sample_count = 0
            self._manual_range = None
            self._frozen_x_range = None
            self.pause_button_text.set(self.i18n.translate_text("继续显示"))
        else:
            if window_key == "自定义" and self._x_range is not None:
                self._set_custom_window_span(max(self._x_range[1] - self._x_range[0], MIN_ZOOM_SPAN_SECONDS), switch_option=False)
            self._activate_live_view()
        self._queue_redraw()

    def _shortcut_uses_alt(self, event) -> bool:
        return bool(getattr(event, "state", 0) & ALT_MASK)

    def _on_show_all_shortcut(self, _event) -> None:
        if self._shortcut_uses_alt(_event):
            return
        self.show_all()

    def _on_apply_period_shortcut(self, _event) -> str:
        if self._shortcut_uses_alt(_event):
            return "break"
        self.on_apply_period()
        return "break"

    def _on_toggle_run_shortcut(self, _event) -> str:
        if self._shortcut_uses_alt(_event):
            return "break"
        self.on_toggle_run()
        return "break"

    def _on_pause_shortcut(self, _event) -> str:
        if self._shortcut_uses_alt(_event):
            return "break"
        self.toggle_pause_view()
        return "break"

    def _on_back_to_live_shortcut(self, _event) -> str:
        if self._shortcut_uses_alt(_event):
            return "break"
        self.back_to_live()
        return "break"

    def _on_clear_shortcut(self, _event) -> str:
        if self._shortcut_uses_alt(_event):
            return "break"
        self.on_clear()
        return "break"

    def _on_export_shortcut(self, _event) -> str:
        if self._shortcut_uses_alt(_event):
            return "break"
        self.export_waveform_file()
        return "break"

    def _on_import_shortcut(self, _event) -> str:
        if self._shortcut_uses_alt(_event):
            return "break"
        self.import_waveform_file()
        return "break"

    def _on_marker_shortcut(self, _event) -> str:
        if self._shortcut_uses_alt(_event):
            return "break"
        self.add_marker()
        return "break"

    def _on_horizontal_reference_shortcut(self, _event) -> str:
        if self._shortcut_uses_alt(_event):
            return "break"
        self.start_horizontal_reference_line()
        return "break"

    def _on_vertical_reference_shortcut(self, _event) -> str:
        if self._shortcut_uses_alt(_event):
            return "break"
        self.start_vertical_reference_line()
        return "break"

    def _on_cross_reference_shortcut(self, _event) -> str:
        if self._shortcut_uses_alt(_event):
            return "break"
        self.start_cross_reference_line()
        return "break"

    def _on_cancel_reference_shortcut(self, _event) -> str | None:
        if self._parameter_drag is not None:
            self._cancel_parameter_drag()
            return "break"
        if self._shortcut_uses_alt(_event):
            return "break"
        if self.cancel_pending_reference_line():
            return "break"
        return None

    def _on_alt_press(self, _event) -> str:
        if self._alt_pressed:
            return "break"
        self._alt_pressed = True
        self._refresh_hover_from_pointer(force=True)
        return "break"

    def _on_alt_release(self, _event) -> str:
        if not self._alt_pressed:
            return "break"
        self._alt_pressed = False
        if self._last_hover_index is not None:
            self._queue_redraw()
        return "break"

    def _on_alt_modified_key(self, event) -> str | None:
        if self._shortcut_uses_alt(event):
            return "break"
        return None

    def _on_key_release_guard(self, event) -> str | None:
        if getattr(event, "keysym", "") in {"Alt_L", "Alt_R"}:
            return self._on_alt_release(event)
        if self._shortcut_uses_alt(event):
            return "break"
        return None

    def _on_mousewheel(self, event) -> None:
        if not self._plot_bounds or not self._x_range or not self._y_range:
            return
        plot_left, plot_top, plot_right, plot_bottom = self._plot_bounds
        if not (plot_left <= event.x <= plot_right and plot_top <= event.y <= plot_bottom):
            return
        delta_sign = -1 if event.delta > 0 else 1
        if event.state & SHIFT_MASK:
            x_min, x_max = self._x_range
            span = max(x_max - x_min, MIN_ZOOM_SPAN_SECONDS)
            offset = span * 0.12 * delta_sign
            shifted_range = (x_min + offset, x_max + offset)
            self._enter_history_view(shifted_range, self._y_range)
            self._queue_redraw()
        elif event.state & CTRL_MASK:
            y_min, y_max = self._y_range
            span = max(y_max - y_min, MIN_ZOOM_SPAN_VALUE)
            offset = span * 0.12 * delta_sign
            self._manual_y_range = (y_min + offset, y_max + offset)
            if self._paused_view:
                self._frozen_y_range = self._manual_y_range
            self._queue_redraw()

    def _on_drag_start(self, event) -> None:
        if not self._plot_bounds or not self._x_range or not self._y_range:
            return
        plot_left, plot_top, plot_right, plot_bottom = self._plot_bounds
        if not (plot_left <= event.x <= plot_right and plot_top <= event.y <= plot_bottom):
            return
        if self._pending_reference_line is not None:
            self._place_reference_line(event.x, event.y)
            return
        self._drag_anchor = (event.x, event.y)
        self._drag_start_x_range = self._x_range
        self._drag_start_y_range = self._y_range
        self._drag_started_live = not self._paused_view
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
            preview_range = (
                anchor_value - new_span * anchor_ratio,
                anchor_value + new_span * (1.0 - anchor_ratio),
            )
            self._enter_history_view(preview_range, self._drag_start_y_range, use_custom_window=False)
        elif self._drag_mode == "yzoom" and self._drag_anchor and self._drag_start_y_range:
            _, anchor_y = self._drag_anchor
            start_min, start_max = self._drag_start_y_range
            span = max(start_max - start_min, MIN_ZOOM_SPAN_VALUE)
            anchor_ratio = min(max((anchor_y - plot_top) / max(plot_bottom - plot_top, 1), 0.0), 1.0)
            anchor_value = start_max - span * anchor_ratio
            delta_y = event.y - anchor_y
            scale = math.exp(delta_y / 240.0)
            new_span = max(span * scale, MIN_ZOOM_SPAN_VALUE)
            new_max = anchor_value + new_span * anchor_ratio
            new_min = anchor_value - new_span * (1.0 - anchor_ratio)
            self._manual_y_range = (new_min, new_max)
            if self._paused_view:
                self._frozen_y_range = self._manual_y_range
        self._queue_redraw()

    def _on_drag_end(self, _event) -> None:
        self._drag_last_x = None
        drag_mode = self._drag_mode
        if drag_mode == "rect" and self._zoom_rect_start is not None and self._zoom_rect_end is not None:
            self._apply_rect_zoom()
        elif drag_mode == "xzoom" and self._drag_started_live and self._manual_range is not None:
            span = max(self._manual_range[1] - self._manual_range[0], MIN_ZOOM_SPAN_SECONDS)
            self._set_custom_window_span(span)
            self._activate_live_view()
        self._drag_mode = None
        self._drag_anchor = None
        self._drag_start_x_range = None
        self._drag_start_y_range = None
        self._drag_started_live = False
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

        x_min, x_max = self._x_range
        start_ratio = (min(x0, x1) - plot_left) / max(plot_right - plot_left, 1)
        end_ratio = (max(x0, x1) - plot_left) / max(plot_right - plot_left, 1)
        new_start = x_min + (x_max - x_min) * start_ratio
        new_end = x_min + (x_max - x_min) * end_ratio
        new_x_range = self._x_range
        if new_end - new_start >= MIN_ZOOM_SPAN_SECONDS:
            new_x_range = (new_start, new_end)

        y_min, y_max = self._y_range
        top_ratio = (min(y0, y1) - plot_top) / max(plot_bottom - plot_top, 1)
        bottom_ratio = (max(y0, y1) - plot_top) / max(plot_bottom - plot_top, 1)
        new_y_max = y_max - (y_max - y_min) * top_ratio
        new_y_min = y_max - (y_max - y_min) * bottom_ratio
        new_y_range = self._y_range
        if new_y_max - new_y_min >= MIN_ZOOM_SPAN_VALUE:
            new_y_range = (new_y_min, new_y_max)

        follows_latest = self._drag_started_live and max(x0, x1) >= plot_right - 12
        self._manual_y_range = new_y_range
        if follows_latest:
            self._set_custom_window_span(max(new_x_range[1] - new_x_range[0], MIN_ZOOM_SPAN_SECONDS))
            self._activate_live_view()
        else:
            self._enter_history_view(new_x_range, new_y_range)

    def _on_canvas_motion(self, event) -> None:
        # Recover missed key events when focus changes or the pointer re-enters.
        alt_pressed = self._shortcut_uses_alt(event)
        alt_changed = alt_pressed != self._alt_pressed
        self._alt_pressed = alt_pressed
        if self._pending_reference_line is not None:
            self._update_reference_preview(event.x, event.y)
            return
        if self._zoom_rect_start is not None:
            self._zoom_rect_end = (event.x, event.y)
            self._queue_redraw()
            return
        self._update_hover_from_canvas_position(event.x, event.y, force=alt_pressed or alt_changed)

    def _on_canvas_leave(self, _event) -> None:
        if self._pending_reference_line is not None:
            self._preview_reference_value = None
            self._queue_redraw()
            return
        if self._zoom_rect_start is not None:
            return
        # Keep the reference and its values visible when the pointer leaves.

    def _refresh_hover_from_pointer(self, *, force: bool = False) -> None:
        if not self._plot_bounds:
            if self._last_hover_index is not None:
                self._queue_redraw()
            return
        canvas_x = self.canvas.winfo_pointerx() - self.canvas.winfo_rootx()
        canvas_y = self.canvas.winfo_pointery() - self.canvas.winfo_rooty()
        self._update_hover_from_canvas_position(canvas_x, canvas_y, force=force)

    def _update_hover_from_canvas_position(self, canvas_x: float, canvas_y: float, *, force: bool = False) -> None:
        if not self._plot_bounds or not self._x_range:
            return
        plot_left, plot_top, plot_right, plot_bottom = self._plot_bounds
        inside_plot = plot_left <= canvas_x <= plot_right and plot_top <= canvas_y <= plot_bottom
        if not inside_plot:
            return
        hover_x = min(max(float(canvas_x), plot_left), plot_right)
        ratio = (hover_x - plot_left) / max(plot_right - plot_left, 1)
        ratio_changed = ratio != self.__dict__.get("_shared_cursor_ratio", 1.0)
        self._shared_cursor_ratio = ratio
        index = self._find_hover_index(hover_x)
        changed = ratio_changed or index != self._last_hover_index or hover_x != self._last_hover_canvas_x
        self._last_hover_index = index
        self._last_hover_canvas_x = hover_x
        if changed or force:
            self._queue_redraw()

    def _find_hover_index(self, canvas_x: float) -> int | None:
        reference_name, reference = self._reference_series_with_name()
        if not reference or not self._plot_bounds or not self._x_range:
            return None
        plot_left, _, plot_right, _ = self._plot_bounds
        x_min, x_max = self._x_range
        ratio = (canvas_x - plot_left) / max(plot_right - plot_left, 1)
        target_ts = x_min + (x_max - x_min) * ratio
        timestamps = self._cached_visible_timestamps.get(reference_name, [])
        index = bisect_left(timestamps, target_ts)
        if index <= 0:
            return 0
        if index >= len(timestamps):
            return len(timestamps) - 1
        before = timestamps[index - 1]
        after = timestamps[index]
        return index - 1 if abs(target_ts - before) <= abs(after - target_ts) else index

    def _reference_series_with_name(self) -> tuple[str, list[tuple[float, float | None]] | None]:
        for name in self.selected_names:
            visible = self._cached_visible_series.get(name)
            if visible:
                return name, visible
        return "", None

    def _reference_series(self) -> list[tuple[float, float | None]] | None:
        _name, series = self._reference_series_with_name()
        return series

    def _update_reference_preview(self, canvas_x: float, canvas_y: float) -> None:
        if not self._pending_reference_line or not self._plot_bounds or not self._x_range or not self._y_range:
            return
        plot_left, plot_top, plot_right, plot_bottom = self._plot_bounds
        if not (plot_left <= canvas_x <= plot_right and plot_top <= canvas_y <= plot_bottom):
            if self._preview_reference_value is not None:
                self._preview_reference_value = None
                self._queue_redraw()
            return

        x_min, x_max = self._x_range
        y_min, y_max = self._y_range
        if self._pending_reference_line == "vertical":
            preview_value = x_min + (x_max - x_min) * ((canvas_x - plot_left) / max(plot_right - plot_left, 1))
        elif self._pending_reference_line == "cross":
            preview_x = x_min + (x_max - x_min) * ((canvas_x - plot_left) / max(plot_right - plot_left, 1))
            preview_y = y_max - (y_max - y_min) * ((canvas_y - plot_top) / max(plot_bottom - plot_top, 1))
            preview_value = (preview_x, preview_y)
        else:
            preview_value = y_max - (y_max - y_min) * ((canvas_y - plot_top) / max(plot_bottom - plot_top, 1))

        if self._reference_preview_changed(preview_value):
            self._preview_reference_value = preview_value
            self._queue_redraw()

    def _place_reference_line(self, canvas_x: float, canvas_y: float) -> None:
        if not self._pending_reference_line or not self._plot_bounds or not self._x_range or not self._y_range:
            return
        self._update_reference_preview(canvas_x, canvas_y)
        if self._preview_reference_value is None:
            return
        orientation = self._pending_reference_line
        value = self._preview_reference_value
        if orientation == "cross":
            if not isinstance(value, tuple):
                return
            x_value, y_value = value
            self.reference_lines.append(("vertical", x_value))
            self.reference_lines.append(("horizontal", y_value))
        else:
            if isinstance(value, tuple):
                return
            self.reference_lines.append((orientation, value))
        self._has_unsaved_changes = True
        self._pending_reference_line = None
        self._preview_reference_value = None
        if orientation == "vertical":
            label = self._format_time_axis_value(value, milliseconds=True)
            self.on_status(f"已固定垂直参考线: {label}", False)
        elif orientation == "cross":
            x_value, y_value = value
            x_label = self._format_time_axis_value(x_value, milliseconds=True)
            self.on_status(f"已固定十字参考线: {x_label}, {self._format_numeric(y_value)}", False)
        else:
            self.on_status(f"已固定水平参考线: {self._format_numeric(value)}", False)
        self._queue_redraw()

    def _reference_preview_changed(self, preview_value: float | tuple[float, float]) -> bool:
        current = self._preview_reference_value
        if current is None:
            return True
        if isinstance(current, tuple) and isinstance(preview_value, tuple):
            return any(abs(a - b) > 1e-9 for a, b in zip(current, preview_value))
        if not isinstance(current, tuple) and not isinstance(preview_value, tuple):
            return abs(current - preview_value) > 1e-9
        return True

    def _timestamp_to_canvas_x(self, timestamp: float, plot_left: float, plot_right: float, x_min: float, x_max: float) -> float:
        return plot_left + (timestamp - x_min) / max(x_max - x_min, 1e-9) * (plot_right - plot_left)

    def _value_to_canvas_y(self, value: float, plot_top: float, plot_bottom: float, y_min: float, y_max: float) -> float:
        return plot_bottom - (value - y_min) / max(y_max - y_min, 1e-9) * (plot_bottom - plot_top)

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
        cursor_x = x
        if self._last_hover_canvas_x is not None:
            cursor_x = min(max(self._last_hover_canvas_x, plot_left), plot_right)
            timestamp = x_min + (cursor_x - plot_left) / max(plot_right - plot_left, 1) * (x_max - x_min)

        base_text = self._format_time_axis_value(timestamp, milliseconds=True)
        lines = [base_text]
        marker_map = self._marker_map()
        if timestamp in marker_map:
            lines.append(f"标记 = {marker_map[timestamp]}")
        point_labels: list[tuple[str, str, str, float]] = []
        visible_names = self._visible_plot_names()
        for idx, name in enumerate(visible_names):
            series = self.series_data.get(name, [])
            sample = self._nearest_sample(series, timestamp, self._timestamps_for(name))
            if sample is None or not x_min <= sample[0] <= x_max:
                continue
            _, value = sample
            if value is None or not math.isfinite(value):
                continue
            color = self._series_color(name)
            y = plot_bottom - (value - y_min) / max(y_max - y_min, 1e-9) * (plot_bottom - plot_top)
            self.canvas.create_oval(cursor_x - 3, y - 3, cursor_x + 3, y + 3, fill=color, outline="")
            point_labels.append((name, self._format_numeric(value), color, y))
            lines.append(f"{name} = {self._format_numeric(value)}")

        self.cursor_var.set(" | ".join(lines))

    def _draw_hover_panel(
        self,
        point_labels: list[tuple[str, str, str, float]],
        lines: list[str],
        plot_left: float,
        plot_top: float,
        plot_right: float,
        plot_bottom: float,
    ) -> None:
        if self._current_plot is not self._active_plot:
            return
        self.reference_time_var.set(lines[0] if lines else self.i18n.translate_text("等待数据"))
        current_names = {name for name, _value, _color, _y in point_labels}
        for name in self.reference_tree.get_children():
            if name not in current_names:
                self.reference_tree.delete(name)
        for index, (name, value, _color, _y) in enumerate(point_labels):
            if self.reference_tree.exists(name):
                self.reference_tree.item(name, values=(name, value))
                self.reference_tree.move(name, "", index)
            else:
                self.reference_tree.insert("", "end", iid=name, values=(name, value))

    def _draw_alt_value_labels(
        self,
        x: float,
        point_labels: list[tuple[str, str, str, float]],
        plot_right: float,
        plot_top: float,
        plot_bottom: float,
    ) -> None:
        return

    def _nearest_sample(
        self,
        series: list[tuple[float, float | None]],
        target_ts: float,
        timestamps: list[float] | None = None,
    ) -> tuple[float, float | None] | None:
        if not series:
            return None
        if timestamps is None:
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
        self.canvas.create_rectangle(x, y, x + box_width, y + box_height, fill=SURFACE, outline=BORDER, width=1)
        for i, line in enumerate(lines):
            self.canvas.create_text(x + padding, y + padding + i * line_height, text=line, anchor="nw", fill=TEXT, font=(FONT_MONO, 9))

    def _format_numeric(self, value: float) -> str:
        return f"{value:.6f}".rstrip("0").rstrip(".")

