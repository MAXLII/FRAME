from __future__ import annotations

from bisect import bisect_left
import csv
import math
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk

from serial_debug_assistant.i18n import I18nManager
from serial_debug_assistant.models import ScopeCapture, ScopeInfo, ScopeListItem
from serial_debug_assistant.scope_protocol import describe_scope_state

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
MIN_ZOOM_SPAN_MS = 1e-3
MIN_ZOOM_SPAN_VALUE = 1e-6
SHIFT_MASK = 0x0001
CTRL_MASK = 0x0004


class ScopeTab(ttk.Frame):
    def __init__(
        self,
        master,
        *,
        on_refresh_scopes,
        on_refresh_info,
        on_refresh_vars,
        on_start,
        on_trigger,
        on_stop,
        on_reset,
        on_pull,
        on_force_pull,
        on_clear_captures,
        export_dir: Path,
        i18n: I18nManager,
    ) -> None:
        super().__init__(master, style="Panel.TFrame", padding=12)
        self.i18n = i18n
        self.export_dir = export_dir
        self._translatable_widgets: list[tuple[object, str, str]] = []
        self.on_refresh_scopes = on_refresh_scopes
        self.on_refresh_info = on_refresh_info
        self.on_refresh_vars = on_refresh_vars
        self.on_start = on_start
        self.on_trigger = on_trigger
        self.on_stop = on_stop
        self.on_reset = on_reset
        self.on_pull = on_pull
        self.on_force_pull = on_force_pull
        self.on_clear_captures = on_clear_captures

        self.target_addr_var = tk.StringVar(value="2")
        self.dynamic_addr_var = tk.StringVar(value="0")
        self.scope_var = tk.StringVar()
        self.status_var = tk.StringVar(value=self.i18n.translate_text("Waiting for scope actions"))
        self.detail_var = tk.StringVar(value=self.i18n.translate_text("Refresh scope objects, then read scope info and variable names."))
        self.state_var = tk.StringVar(value="-")
        self.data_ready_var = tk.StringVar(value="-")
        self.var_count_var = tk.StringVar(value="-")
        self.sample_count_var = tk.StringVar(value="-")
        self.sample_period_var = tk.StringVar(value="-")
        self.trigger_display_var = tk.StringVar(value="-")
        self.capture_tag_var = tk.StringVar(value="-")
        self.pull_status_var = tk.StringVar(value=self.i18n.translate_text("No scope capture has been pulled yet."))
        self.capture_summary_var = tk.StringVar(value=self.i18n.translate_text("Local captures: 0"))
        self.var_scale_input_var = tk.StringVar(value="1")

        self._scope_choices: list[ScopeListItem] = []
        self._scope_name_to_id: dict[str, int] = {}
        self._scope_var_names: list[str] = []
        self._captures: list[ScopeCapture] = []
        self._selected_capture_index: int | None = None
        self._visible_var_states: list[tk.BooleanVar] = []
        self._selected_var_states: list[tk.BooleanVar] = []
        self._var_scale_labels: list[tk.StringVar] = []
        self._var_scale_by_name: dict[str, float] = {}
        self._capture_visible_states: list[tk.BooleanVar] = []
        self._capture_row_frames: list[tk.Frame] = []
        self._last_hover_text = self.i18n.translate_text("Move the mouse over the scope plot to inspect values.")
        self._plot_status_var = tk.StringVar(value=self._last_hover_text)
        self._plot_hover_entries: list[dict[str, object]] = []
        self._plot_bounds: tuple[float, float, float, float] | None = None
        self._x_range: tuple[float, float] | None = None
        self._y_range: tuple[float, float] | None = None
        self._manual_x_range: tuple[float, float] | None = None
        self._manual_y_range: tuple[float, float] | None = None
        self._alt_pressed = False
        self._hover_entry: dict[str, object] | None = None
        self._drag_mode: str | None = None
        self._drag_anchor: tuple[float, float] | None = None
        self._drag_start_x_range: tuple[float, float] | None = None
        self._drag_start_y_range: tuple[float, float] | None = None
        self._zoom_rect_start: tuple[float, float] | None = None
        self._zoom_rect_end: tuple[float, float] | None = None

        self._build()
        self.bind_all("<KeyPress-Alt_L>", self._on_alt_press, add=True)
        self.bind_all("<KeyPress-Alt_R>", self._on_alt_press, add=True)
        self.bind_all("<KeyRelease-Alt_L>", self._on_alt_release, add=True)
        self.bind_all("<KeyRelease-Alt_R>", self._on_alt_release, add=True)

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        select_frame = ttk.LabelFrame(self, text=self.i18n.translate_text("Scope Objects"), style="Section.TLabelframe", padding=12)
        self._remember_text(select_frame, "Scope Objects")
        select_frame.grid(row=0, column=0, sticky="ew")
        for column in range(8):
            select_frame.columnconfigure(column, weight=1 if column in {1, 3, 5} else 0)

        addr_label = ttk.Label(select_frame, text=self.i18n.translate_text("Target Address"))
        addr_label.grid(row=0, column=0, sticky="w")
        self._remember_text(addr_label, "Target Address")
        ttk.Entry(select_frame, textvariable=self.target_addr_var, width=10).grid(row=0, column=1, sticky="ew", padx=(8, 16))

        dyn_label = ttk.Label(select_frame, text=self.i18n.translate_text("Dynamic Address"))
        dyn_label.grid(row=0, column=2, sticky="w")
        self._remember_text(dyn_label, "Dynamic Address")
        ttk.Entry(select_frame, textvariable=self.dynamic_addr_var, width=10).grid(row=0, column=3, sticky="ew", padx=(8, 16))

        scope_label = ttk.Label(select_frame, text=self.i18n.translate_text("Scope Object"))
        scope_label.grid(row=0, column=4, sticky="w")
        self._remember_text(scope_label, "Scope Object")
        self.scope_combo = ttk.Combobox(select_frame, textvariable=self.scope_var, values=(), state="readonly", width=28)
        self.scope_combo.grid(row=0, column=5, sticky="ew", padx=(8, 16))

        self.refresh_scopes_button = ttk.Button(select_frame, text=self.i18n.translate_text("Refresh Scopes"), command=self.on_refresh_scopes, width=16)
        self.refresh_scopes_button.grid(row=0, column=6, sticky="w")
        self._remember_text(self.refresh_scopes_button, "Refresh Scopes")

        self.refresh_info_button = ttk.Button(select_frame, text=self.i18n.translate_text("Refresh Info"), command=self.on_refresh_info, width=14)
        self.refresh_info_button.grid(row=0, column=7, sticky="e")
        self._remember_text(self.refresh_info_button, "Refresh Info")

        control_row = ttk.Frame(select_frame, style="Panel.TFrame")
        control_row.grid(row=1, column=0, columnspan=8, sticky="ew", pady=(12, 0))
        self.read_vars_button = ttk.Button(control_row, text=self.i18n.translate_text("Read Variables"), command=self.on_refresh_vars, width=14)
        self.read_vars_button.grid(row=0, column=0, sticky="w")
        self._remember_text(self.read_vars_button, "Read Variables")
        self.start_button = ttk.Button(control_row, text=self.i18n.translate_text("Start Scope"), command=self.on_start, style="Accent.TButton", width=12)
        self.start_button.grid(row=0, column=1, padx=(12, 0))
        self._remember_text(self.start_button, "Start Scope")
        self.trigger_button = ttk.Button(control_row, text=self.i18n.translate_text("Trigger Scope"), command=self.on_trigger, width=12)
        self.trigger_button.grid(row=0, column=2, padx=(8, 0))
        self._remember_text(self.trigger_button, "Trigger Scope")
        self.stop_button = ttk.Button(control_row, text=self.i18n.translate_text("Stop Scope"), command=self.on_stop, width=12)
        self.stop_button.grid(row=0, column=3, padx=(8, 0))
        self._remember_text(self.stop_button, "Stop Scope")
        self.reset_button = ttk.Button(control_row, text=self.i18n.translate_text("Reset Scope"), command=self.on_reset, width=12)
        self.reset_button.grid(row=0, column=4, padx=(8, 0))
        self._remember_text(self.reset_button, "Reset Scope")
        self.pull_button = ttk.Button(control_row, text=self.i18n.translate_text("Pull Capture"), command=self.on_pull, width=12)
        self.pull_button.grid(row=0, column=5, padx=(16, 0))
        self._remember_text(self.pull_button, "Pull Capture")
        self.force_pull_button = ttk.Button(control_row, text=self.i18n.translate_text("Force Pull"), command=self.on_force_pull, width=12)
        self.force_pull_button.grid(row=0, column=6, padx=(8, 0))
        self._remember_text(self.force_pull_button, "Force Pull")
        self.clear_local_button = ttk.Button(control_row, text=self.i18n.translate_text("Clear Local Captures"), command=self.on_clear_captures, width=16)
        self.clear_local_button.grid(row=0, column=7, padx=(8, 0))
        self._remember_text(self.clear_local_button, "Clear Local Captures")
        ttk.Label(control_row, textvariable=self.status_var, style="Header.TLabel").grid(row=0, column=8, sticky="w", padx=(20, 0))

        detail_frame = ttk.LabelFrame(self, text=self.i18n.translate_text("Scope Info"), style="Section.TLabelframe", padding=12)
        self._remember_text(detail_frame, "Scope Info")
        detail_frame.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        detail_frame.columnconfigure(1, weight=1)
        detail_frame.columnconfigure(3, weight=1)

        rows = [
            ("State", self.state_var, 0, 0),
            ("Data Ready", self.data_ready_var, 0, 2),
            ("Variable Count", self.var_count_var, 1, 0),
            ("Sample Count", self.sample_count_var, 1, 2),
            ("Sample Period (us)", self.sample_period_var, 2, 0),
            ("Trigger Display Index", self.trigger_display_var, 2, 2),
            ("Capture Tag", self.capture_tag_var, 3, 0),
            ("Detail", self.detail_var, 3, 2),
        ]
        for label, variable, row, column in rows:
            row_label = ttk.Label(detail_frame, text=self.i18n.translate_text(label))
            row_label.grid(row=row, column=column, sticky="w", pady=4)
            self._remember_text(row_label, label)
            ttk.Label(detail_frame, textvariable=variable).grid(row=row, column=column + 1, sticky="w", pady=4, padx=(12, 0))

        content_frame = ttk.Frame(self, style="Panel.TFrame")
        content_frame.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        content_frame.columnconfigure(0, weight=0)
        content_frame.columnconfigure(1, weight=1)
        content_frame.rowconfigure(0, weight=1)

        side_frame = ttk.Frame(content_frame, style="Panel.TFrame")
        side_frame.grid(row=0, column=0, sticky="nsw", padx=(0, 8))
        side_frame.rowconfigure(0, weight=1)
        side_frame.rowconfigure(1, weight=1)

        vars_frame = ttk.LabelFrame(side_frame, text=self.i18n.translate_text("Variables"), style="Section.TLabelframe", padding=12)
        self._remember_text(vars_frame, "Variables")
        vars_frame.grid(row=0, column=0, sticky="nsew")
        vars_frame.columnconfigure(0, weight=1)
        vars_frame.rowconfigure(1, weight=1)

        vars_toolbar = ttk.Frame(vars_frame, style="Panel.TFrame")
        vars_toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.show_all_button = ttk.Button(vars_toolbar, text=self.i18n.translate_text("Show All"), command=self.show_all_variables, width=12)
        self.show_all_button.grid(row=0, column=0, sticky="w")
        self._remember_text(self.show_all_button, "Show All")
        self.hide_all_button = ttk.Button(vars_toolbar, text=self.i18n.translate_text("Hide All"), command=self.hide_all_variables, width=12)
        self.hide_all_button.grid(row=0, column=1, padx=(8, 0), sticky="w")
        self._remember_text(self.hide_all_button, "Hide All")
        ttk.Label(vars_toolbar, text="倍率").grid(row=0, column=2, padx=(12, 4), sticky="w")
        ttk.Entry(vars_toolbar, textvariable=self.var_scale_input_var, width=10).grid(row=0, column=3, sticky="w")
        ttk.Button(vars_toolbar, text="应用倍率", command=self.apply_selected_variable_scale, width=10).grid(row=0, column=4, padx=(8, 0), sticky="w")

        self.vars_canvas = tk.Canvas(vars_frame, bg="#ffffff", highlightthickness=1, highlightbackground="#d8e3ef", width=280)
        self.vars_canvas.grid(row=1, column=0, sticky="nsew")
        vars_scroll = ttk.Scrollbar(vars_frame, orient="vertical", command=self.vars_canvas.yview)
        vars_scroll.grid(row=1, column=1, sticky="ns")
        self.vars_canvas.configure(yscrollcommand=vars_scroll.set)
        self.vars_inner = ttk.Frame(self.vars_canvas, style="Panel.TFrame")
        self.vars_window = self.vars_canvas.create_window((0, 0), window=self.vars_inner, anchor="nw")
        self.vars_inner.bind("<Configure>", self._on_vars_inner_configure)
        self.vars_canvas.bind("<Configure>", self._on_vars_canvas_configure)

        ttk.Label(vars_frame, textvariable=self.capture_summary_var, style="Status.TLabel").grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        captures_frame = ttk.LabelFrame(side_frame, text=self.i18n.translate_text("Local Captures"), style="Section.TLabelframe", padding=12)
        self._remember_text(captures_frame, "Local Captures")
        captures_frame.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        captures_frame.columnconfigure(0, weight=1)
        captures_frame.rowconfigure(1, weight=1)

        capture_header = ttk.Frame(captures_frame, style="Panel.TFrame")
        capture_header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        visible_label = ttk.Label(capture_header, text=self.i18n.translate_text("Visible"), width=6)
        visible_label.grid(row=0, column=0, padx=(0, 8), sticky="w")
        self._remember_text(visible_label, "Visible")
        selected_label = ttk.Label(capture_header, text=self.i18n.translate_text("Selected"), width=8)
        selected_label.grid(row=0, column=1, padx=(0, 8), sticky="w")
        self._remember_text(selected_label, "Selected")
        capture_list_label = ttk.Label(capture_header, text=self.i18n.translate_text("Local Captures"))
        capture_list_label.grid(row=0, column=2, sticky="w")
        self._remember_text(capture_list_label, "Local Captures")

        self.capture_canvas = tk.Canvas(captures_frame, bg="#ffffff", highlightthickness=1, highlightbackground="#d8e3ef", width=280)
        self.capture_canvas.grid(row=1, column=0, sticky="nsew")
        capture_scroll = ttk.Scrollbar(captures_frame, orient="vertical", command=self.capture_canvas.yview)
        capture_scroll.grid(row=1, column=1, sticky="ns")
        self.capture_canvas.configure(yscrollcommand=capture_scroll.set)
        self.capture_inner = tk.Frame(self.capture_canvas, bg="#ffffff")
        self.capture_window = self.capture_canvas.create_window((0, 0), window=self.capture_inner, anchor="nw")
        self.capture_inner.bind("<Configure>", self._on_capture_inner_configure)
        self.capture_canvas.bind("<Configure>", self._on_capture_canvas_configure)
        self.capture_canvas.bind("<MouseWheel>", self._on_capture_canvas_mousewheel)

        capture_toolbar = ttk.Frame(captures_frame, style="Panel.TFrame")
        capture_toolbar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.show_all_captures_button = ttk.Button(capture_toolbar, text=self.i18n.translate_text("Show All"), command=self.show_all_captures, width=12)
        self.show_all_captures_button.grid(row=0, column=0, sticky="w")
        self._remember_text(self.show_all_captures_button, "Show All")
        self.hide_all_captures_button = ttk.Button(capture_toolbar, text=self.i18n.translate_text("Hide All"), command=self.hide_all_captures, width=12)
        self.hide_all_captures_button.grid(row=0, column=1, padx=(8, 0), sticky="w")
        self._remember_text(self.hide_all_captures_button, "Hide All")
        self.export_csv_button = ttk.Button(capture_toolbar, text=self.i18n.translate_text("Export CSV"), command=self.export_selected_capture_csv, width=12)
        self.export_csv_button.grid(row=0, column=2, padx=(12, 0), sticky="w")
        self._remember_text(self.export_csv_button, "Export CSV")
        self.remove_capture_button = ttk.Button(capture_toolbar, text=self.i18n.translate_text("Remove Selected"), command=self.remove_selected_capture, width=14)
        self.remove_capture_button.grid(row=0, column=3, padx=(8, 0), sticky="w")
        self._remember_text(self.remove_capture_button, "Remove Selected")

        capture_frame = ttk.LabelFrame(content_frame, text=self.i18n.translate_text("Capture Preview"), style="Section.TLabelframe", padding=12)
        self._remember_text(capture_frame, "Capture Preview")
        capture_frame.grid(row=0, column=1, sticky="nsew")
        capture_frame.columnconfigure(0, weight=1)
        capture_frame.rowconfigure(1, weight=1)
        ttk.Label(
            capture_frame,
            textvariable=self.pull_status_var,
            wraplength=420,
            justify="left",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 10))

        self.plot_canvas = tk.Canvas(capture_frame, bg="#f8fbfe", highlightthickness=1, highlightbackground="#bfd0e3", relief="flat")
        self.plot_canvas.grid(row=1, column=0, sticky="nsew")
        self.plot_canvas.bind("<Configure>", lambda _event: self.redraw_plot())
        self.plot_canvas.bind("<Motion>", self._on_plot_motion)
        self.plot_canvas.bind("<Leave>", self._on_plot_leave)
        self.plot_canvas.bind("<MouseWheel>", self._on_plot_mousewheel)
        self.plot_canvas.bind("<ButtonPress-1>", self._on_plot_drag_start)
        self.plot_canvas.bind("<B1-Motion>", self._on_plot_drag_move)
        self.plot_canvas.bind("<ButtonRelease-1>", self._on_plot_drag_end)

        tip_label = ttk.Label(
            capture_frame,
            text=self.i18n.translate_text("Drag to zoom. Shift+drag zooms X, Ctrl+drag zooms Y. Shift+wheel pans X, Ctrl+wheel pans Y. Hold Alt to inspect the current point."),
            style="Status.TLabel",
            justify="left",
        )
        tip_label.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self._remember_text(
            tip_label,
            "Drag to zoom. Shift+drag zooms X, Ctrl+drag zooms Y. Shift+wheel pans X, Ctrl+wheel pans Y. Hold Alt to inspect the current point.",
        )

        ttk.Label(capture_frame, textvariable=self._plot_status_var, style="Status.TLabel", justify="left").grid(row=3, column=0, sticky="ew", pady=(8, 0))

        self._set_capture_buttons_enabled(False)

    def get_target_address(self) -> tuple[int, int]:
        return int(self.target_addr_var.get() or "0"), int(self.dynamic_addr_var.get() or "0")

    def get_selected_scope_id(self) -> int:
        selected_name = self.scope_var.get().strip()
        if not selected_name or selected_name not in self._scope_name_to_id:
            raise ValueError("Please select a scope object first.")
        return self._scope_name_to_id[selected_name]

    def set_scope_items(self, items: list[ScopeListItem]) -> None:
        self._scope_choices = list(items)
        self._scope_name_to_id = {item.name: item.scope_id for item in items}
        names = [item.name for item in items]
        self.scope_combo.configure(values=names)
        if names:
            current = self.scope_var.get().strip()
            self.scope_var.set(current if current in self._scope_name_to_id else names[0])
        else:
            self.scope_var.set("")

    def set_scope_info(self, info: ScopeInfo | None) -> None:
        if info is None:
            self.state_var.set("-")
            self.data_ready_var.set("-")
            self.var_count_var.set("-")
            self.sample_count_var.set("-")
            self.sample_period_var.set("-")
            self.trigger_display_var.set("-")
            self.capture_tag_var.set("-")
            return

        self.state_var.set(self.i18n.translate_text(describe_scope_state(info.state)))
        self.data_ready_var.set(self.i18n.translate_text("Yes" if info.data_ready else "No"))
        self.var_count_var.set(str(info.var_count))
        self.sample_count_var.set(str(info.sample_count))
        self.sample_period_var.set(str(info.sample_period_us))
        self.trigger_display_var.set(str(info.trigger_display_index))
        self.capture_tag_var.set(str(info.capture_tag))

    def set_scope_var_names(self, var_names: list[str]) -> None:
        for child in self.vars_inner.winfo_children():
            child.destroy()

        self._scope_var_names = list(var_names)
        self._visible_var_states = []
        self._selected_var_states = []
        self._var_scale_labels = []
        if var_names:
            ttk.Label(self.vars_inner, text=self.i18n.translate_text("Visible")).grid(row=0, column=0, sticky="w", padx=(0, 8))
            ttk.Label(self.vars_inner, text=self.i18n.translate_text("Selected")).grid(row=0, column=1, sticky="w", padx=(0, 8))
            ttk.Label(self.vars_inner, text=self.i18n.translate_text("Variables")).grid(row=0, column=2, sticky="w", padx=(0, 8))
            ttk.Label(self.vars_inner, text="倍率").grid(row=0, column=3, sticky="w")
        for index, name in enumerate(var_names):
            visible_var = tk.BooleanVar(value=True)
            selected_var = tk.BooleanVar(value=False)
            scale_var = tk.StringVar(value=self._format_scale_label(self._var_scale_by_name.get(name, 1.0)))
            self._visible_var_states.append(visible_var)
            self._selected_var_states.append(selected_var)
            self._var_scale_labels.append(scale_var)
            visible_checkbox = ttk.Checkbutton(
                self.vars_inner,
                variable=visible_var,
                command=self.redraw_plot,
                style="TCheckbutton",
            )
            visible_checkbox.grid(row=index + 1, column=0, sticky="w", pady=2, padx=(0, 8))
            selected_checkbox = ttk.Checkbutton(
                self.vars_inner,
                variable=selected_var,
                style="TCheckbutton",
            )
            selected_checkbox.grid(row=index + 1, column=1, sticky="w", pady=2, padx=(0, 8))
            ttk.Label(self.vars_inner, text=name).grid(row=index + 1, column=2, sticky="w", pady=2, padx=(0, 8))
            ttk.Label(self.vars_inner, textvariable=scale_var).grid(row=index + 1, column=3, sticky="w", pady=2)

        if not var_names:
            ttk.Label(self.vars_inner, text=self.i18n.translate_text("No scope variables loaded yet.")).grid(row=0, column=0, sticky="w")
        self.redraw_plot()

    def set_status(self, status: str, detail: str = "") -> None:
        self.status_var.set(self.i18n.translate_text(status))
        self.detail_var.set(self.i18n.translate_text(detail))

    def set_pull_status(self, message: str) -> None:
        self.pull_status_var.set(self.i18n.translate_text(message))

    def start_pull(self, scope_name: str, sample_count: int, mode_name: str) -> None:
        self.pull_status_var.set(
            self.i18n.format_text(
                "Pulling {scope_name}: {mode}, samples 0 / {total}",
                scope_name=scope_name,
                mode=mode_name,
                total=sample_count,
            )
        )

    def update_pull_progress(self, current: int, total: int, scope_name: str, mode_name: str) -> None:
        self.pull_status_var.set(
            self.i18n.format_text(
                "Pulling {scope_name}: {mode}, samples {current} / {total}",
                scope_name=scope_name,
                mode=mode_name,
                current=current,
                total=total,
            )
        )

    def finish_pull(self, capture: ScopeCapture) -> None:
        self._captures.append(capture)
        self._capture_visible_states.append(tk.BooleanVar(value=True))
        self._selected_capture_index = len(self._captures) - 1
        self.capture_summary_var.set(self.i18n.format_text("Local captures: {count}", count=len(self._captures)))
        self.pull_status_var.set(
            self.i18n.format_text(
                "Pull finished: {scope_name}, tag {tag}, samples {count}",
                scope_name=capture.scope_name,
                tag=capture.capture_tag,
                count=capture.sample_count,
            )
        )
        self._manual_x_range = None
        self._manual_y_range = None
        self._refresh_capture_list(select_last=True)
        self._set_capture_buttons_enabled(True)
        self.redraw_plot()

    def fail_pull(self, message: str) -> None:
        self.pull_status_var.set(self.i18n.translate_text(message))

    def clear_captures(self) -> None:
        self._captures.clear()
        self._capture_visible_states.clear()
        self._selected_capture_index = None
        self._manual_x_range = None
        self._manual_y_range = None
        self._hover_entry = None
        self._rebuild_capture_rows()
        self.capture_summary_var.set(self.i18n.format_text("Local captures: {count}", count=0))
        self.pull_status_var.set(self.i18n.translate_text("No scope capture has been pulled yet."))
        self._plot_status_var.set(self.i18n.translate_text("Move the mouse over the scope plot to inspect values."))
        self._set_capture_buttons_enabled(False)
        self.redraw_plot()

    def refresh_texts(self) -> None:
        for widget, source_text, option in self._translatable_widgets:
            widget.configure(**{option: self.i18n.translate_text(source_text)})
        self.status_var.set(self.i18n.translate_text(self.status_var.get()))
        self.detail_var.set(self.i18n.translate_text(self.detail_var.get()))
        self.pull_status_var.set(self.i18n.translate_text(self.pull_status_var.get()))
        self.capture_summary_var.set(self.i18n.translate_text(self.capture_summary_var.get()))
        self._plot_status_var.set(self.i18n.translate_text(self._plot_status_var.get()))
        self.data_ready_var.set(self.i18n.translate_text(self.data_ready_var.get()))
        self._refresh_capture_list()
        self.redraw_plot()

    def show_all_variables(self) -> None:
        for variable in self._visible_var_states:
            variable.set(True)
        self.redraw_plot()

    def hide_all_variables(self) -> None:
        for variable in self._visible_var_states:
            variable.set(False)
        self.redraw_plot()

    def apply_selected_variable_scale(self) -> None:
        try:
            scale = float(self.var_scale_input_var.get().strip() or "1")
        except ValueError:
            self.set_pull_status("倍率输入无效。")
            return

        applied_names: list[str] = []
        for index, selected in enumerate(self._selected_var_states):
            if not selected.get():
                continue
            if index >= len(self._scope_var_names):
                continue
            name = self._scope_var_names[index]
            self._var_scale_by_name[name] = scale
            if index < len(self._var_scale_labels):
                self._var_scale_labels[index].set(self._format_scale_label(scale))
            applied_names.append(name)
        if not applied_names:
            self.set_pull_status("请先选中录波变量。")
            return
        self.set_pull_status(f"已将 {len(applied_names)} 个变量的倍率设置为 {scale:g}")
        self.redraw_plot()

    def show_all_captures(self) -> None:
        for variable in self._capture_visible_states:
            variable.set(True)
        self.redraw_plot()

    def hide_all_captures(self) -> None:
        for variable in self._capture_visible_states:
            variable.set(False)
        self.redraw_plot()

    def export_selected_capture_csv(self) -> None:
        capture = self._get_selected_capture()
        if capture is None:
            self.set_pull_status("No local capture selected.")
            return

        self.export_dir.mkdir(parents=True, exist_ok=True)
        default_name = f"scope_{capture.scope_name}_capture_{capture.capture_index}_tag_{capture.capture_tag}.csv"
        path = filedialog.asksaveasfilename(
            title=self.i18n.translate_text("Save Scope CSV"),
            initialdir=str(self.export_dir),
            initialfile=default_name,
            defaultextension=".csv",
            filetypes=[(self.i18n.translate_text("CSV Files"), "*.csv"), (self.i18n.translate_text("All Files"), "*.*")],
        )
        if not path:
            return

        with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["sample_index", "time_ms", "trigger_relative_ms", *capture.var_names])
            for sample_index, sample_values in enumerate(capture.samples):
                time_ms = sample_index * capture.sample_period_us / 1000.0
                trigger_relative_ms = (sample_index - capture.trigger_display_index) * capture.sample_period_us / 1000.0
                writer.writerow([sample_index, f"{time_ms:.6f}", f"{trigger_relative_ms:.6f}", *sample_values])

        self.set_pull_status(self.i18n.format_text("Saved scope capture to {path}", path=path))

    def remove_selected_capture(self) -> None:
        selected_index = self._get_selected_capture_index()
        if selected_index is None:
            self.set_pull_status("No local capture selected.")
            return
        del self._captures[selected_index]
        if selected_index < len(self._capture_visible_states):
            del self._capture_visible_states[selected_index]
        if not self._captures:
            self._selected_capture_index = None
            self._manual_x_range = None
            self._manual_y_range = None
        elif self._selected_capture_index is None:
            self._selected_capture_index = 0
        elif self._selected_capture_index >= len(self._captures):
            self._selected_capture_index = len(self._captures) - 1
        self.capture_summary_var.set(self.i18n.format_text("Local captures: {count}", count=len(self._captures)))
        self._refresh_capture_list(select_last=bool(self._captures))
        self._set_capture_buttons_enabled(bool(self._captures))
        self.set_pull_status("Selected capture removed.")
        self.redraw_plot()

    def _remember_text(self, widget: object, source_text: str, option: str = "text") -> None:
        self._translatable_widgets.append((widget, source_text, option))

    def _refresh_capture_list(self, *, select_last: bool = False) -> None:
        if select_last:
            self._selected_capture_index = len(self._captures) - 1 if self._captures else None
        elif self._selected_capture_index is not None and self._selected_capture_index >= len(self._captures):
            self._selected_capture_index = len(self._captures) - 1 if self._captures else None
        elif self._selected_capture_index is None and self._captures:
            self._selected_capture_index = 0

        self._rebuild_capture_rows()

    def _rebuild_capture_rows(self) -> None:
        for child in self.capture_inner.winfo_children():
            child.destroy()
        self._capture_row_frames = []

        for index, capture in enumerate(self._captures):
            if index >= len(self._capture_visible_states):
                self._capture_visible_states.append(tk.BooleanVar(value=True))
            visible_var = self._capture_visible_states[index]
            row = tk.Frame(
                self.capture_inner,
                bg="#eaf2fb" if index == self._selected_capture_index else "#ffffff",
                highlightthickness=1,
                highlightbackground="#d8e3ef",
                bd=0,
            )
            row.grid(row=index, column=0, sticky="ew", pady=2)
            row.columnconfigure(2, weight=1)
            self._capture_row_frames.append(row)

            check = tk.Checkbutton(
                row,
                variable=visible_var,
                command=self.redraw_plot,
                bg=row.cget("bg"),
                activebackground=row.cget("bg"),
                highlightthickness=0,
                bd=0,
                relief="flat",
            )
            check.grid(row=0, column=0, padx=(6, 8), pady=4)
            select_button = ttk.Button(
                row,
                text=self.i18n.translate_text("Select"),
                command=lambda idx=index: self._select_capture(idx),
                width=8,
            )
            select_button.grid(row=0, column=1, padx=(0, 8), pady=4, sticky="w")

            label_text = self.i18n.format_text(
                "Capture #{index} | tag {tag} | samples {count}",
                index=capture.capture_index,
                tag=capture.capture_tag,
                count=capture.sample_count,
            )
            label = tk.Label(
                row,
                text=label_text,
                anchor="w",
                bg=row.cget("bg"),
                fg="#112033",
            )
            label.grid(row=0, column=2, sticky="ew", padx=(0, 6), pady=4)
            for widget in (row, label):
                widget.bind("<Button-1>", lambda _event, idx=index: self._select_capture(idx))
                widget.bind("<MouseWheel>", self._on_capture_canvas_mousewheel)
            check.bind("<MouseWheel>", self._on_capture_canvas_mousewheel)
            select_button.bind("<MouseWheel>", self._on_capture_canvas_mousewheel)

        empty = not self._captures
        if empty:
            ttk.Label(self.capture_inner, text=self.i18n.translate_text("No local scope captures to display.")).grid(row=0, column=0, sticky="w")

        self.capture_canvas.configure(scrollregion=self.capture_canvas.bbox("all"))

    def _select_capture(self, index: int) -> None:
        if index < 0 or index >= len(self._captures):
            return
        self._selected_capture_index = index
        self._rebuild_capture_rows()
        self.redraw_plot()

    def _set_capture_buttons_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.show_all_captures_button.configure(state=state)
        self.hide_all_captures_button.configure(state=state)
        self.export_csv_button.configure(state=state)
        self.remove_capture_button.configure(state=state)

    def _get_selected_capture_index(self) -> int | None:
        if self._selected_capture_index is None:
            return None
        if self._selected_capture_index < 0 or self._selected_capture_index >= len(self._captures):
            return None
        return self._selected_capture_index

    def _get_selected_capture(self) -> ScopeCapture | None:
        selected_index = self._get_selected_capture_index()
        if selected_index is None or selected_index >= len(self._captures):
            return None
        return self._captures[selected_index]

    def _get_visible_var_indices(self) -> list[int]:
        return [index for index, variable in enumerate(self._visible_var_states) if variable.get()]

    def _get_var_scale(self, capture: ScopeCapture, var_index: int) -> float:
        if var_index >= len(capture.var_names):
            return 1.0
        return self._var_scale_by_name.get(capture.var_names[var_index], 1.0)

    def _scale_value(self, capture: ScopeCapture, var_index: int, value: float) -> float:
        return value * self._get_var_scale(capture, var_index)

    def _format_scale_label(self, scale: float) -> str:
        return f"x {scale:g}"

    def _get_visible_capture_indices(self) -> list[int]:
        visible_indices: list[int] = []
        for index, variable in enumerate(self._capture_visible_states):
            if index < len(self._captures) and variable.get():
                visible_indices.append(index)
        return visible_indices

    def redraw_plot(self) -> None:
        canvas = self.plot_canvas
        canvas.delete("all")
        self._plot_hover_entries = []
        self._plot_bounds = None
        self._x_range = None
        self._y_range = None
        width = max(canvas.winfo_width(), 320)
        height = max(canvas.winfo_height(), 220)
        if not self._captures:
            canvas.create_text(
                width / 2,
                height / 2,
                text=self.i18n.translate_text("No local scope captures to display."),
                fill="#5b6b7f",
                font=("Segoe UI", 11),
            )
            return

        visible_capture_indices = self._get_visible_capture_indices()
        if not visible_capture_indices:
            canvas.create_text(
                width / 2,
                height / 2,
                text=self.i18n.translate_text("No captures are visible. Enable at least one local capture to draw the scope."),
                fill="#5b6b7f",
                font=("Segoe UI", 11),
            )
            return

        visible_var_indices = self._get_visible_var_indices()
        if not visible_var_indices:
            canvas.create_text(
                width / 2,
                height / 2,
                text=self.i18n.translate_text("No variables are visible. Enable at least one variable to draw the scope."),
                fill="#5b6b7f",
                font=("Segoe UI", 11),
            )
            return

        plot_left = 56
        plot_top = 18
        plot_right = width - 18
        plot_bottom = height - 36
        self._plot_bounds = (plot_left, plot_top, plot_right, plot_bottom)
        canvas.create_rectangle(plot_left, plot_top, plot_right, plot_bottom, outline="#cbd5e1", width=1)

        flattened: list[tuple[float, float]] = []
        capture_positions: list[tuple[int, ScopeCapture, float, float, float]] = []
        x_offset = 0.0
        for capture_index in visible_capture_indices:
            capture = self._captures[capture_index]
            capture_duration_ms = max(0.0, (capture.sample_count - 1) * capture.sample_period_us / 1000.0)
            capture_start_x = x_offset
            capture_end_x = x_offset + capture_duration_ms
            capture_trigger_x = x_offset + (capture.trigger_display_index * capture.sample_period_us / 1000.0)
            capture_positions.append((capture_index, capture, capture_start_x, capture_end_x, capture_trigger_x))

            for sample_index, sample_values in enumerate(capture.samples):
                x_value = x_offset + (sample_index * capture.sample_period_us / 1000.0)
                for var_index in visible_var_indices:
                    if var_index >= len(sample_values):
                        continue
                    value = self._scale_value(capture, var_index, sample_values[var_index])
                    if math.isfinite(value):
                        flattened.append((x_value, value))
            x_offset = capture_end_x + max(1.0, capture.sample_period_us * 10 / 1000.0)

        if not flattened:
            canvas.create_text(
                width / 2,
                height / 2,
                text=self.i18n.translate_text("Scope captures contain no finite data."),
                fill="#5b6b7f",
                font=("Segoe UI", 11),
            )
            return

        x_values = [item[0] for item in flattened]
        y_values = [item[1] for item in flattened]
        x_min, x_max = min(x_values), max(x_values)
        y_min, y_max = min(y_values), max(y_values)
        if abs(y_max - y_min) < 1e-9:
            y_min -= 1.0
            y_max += 1.0
        if abs(x_max - x_min) < 1e-9:
            x_max += 1.0
        x_min, x_max = self._resolve_x_range(x_min, x_max)
        y_min, y_max = self._resolve_y_range(y_min, y_max)
        self._x_range = (x_min, x_max)
        self._y_range = (y_min, y_max)

        def map_x(value: float) -> float:
            return plot_left + (value - x_min) / max(x_max - x_min, 1e-9) * (plot_right - plot_left)

        def map_y(value: float) -> float:
            return plot_bottom - (value - y_min) / max(y_max - y_min, 1e-9) * (plot_bottom - plot_top)

        canvas.create_text(plot_left - 10, plot_top, text=f"{y_max:.3f}", anchor="e", fill="#475569", font=("Consolas", 9))
        canvas.create_text(plot_left - 10, plot_bottom, text=f"{y_min:.3f}", anchor="e", fill="#475569", font=("Consolas", 9))
        canvas.create_text(plot_left, plot_bottom + 14, text=f"{x_min:.3f} ms", anchor="w", fill="#475569", font=("Consolas", 9))
        canvas.create_text(plot_right, plot_bottom + 14, text=f"{x_max:.3f} ms", anchor="e", fill="#475569", font=("Consolas", 9))

        legend_entries: list[tuple[str, str]] = []
        for capture_index, capture, capture_start_x, _capture_end_x, capture_trigger_x in capture_positions:
            canvas.create_line(map_x(capture_start_x), plot_top, map_x(capture_start_x), plot_bottom, fill="#cbd5e1", dash=(3, 4))
            canvas.create_line(map_x(capture_trigger_x), plot_top, map_x(capture_trigger_x), plot_bottom, fill="#dc2626", dash=(5, 4))
            canvas.create_text(
                map_x(capture_start_x) + 4,
                plot_top + 4,
                text=f"#{capture.capture_index} {capture.scope_name}",
                anchor="nw",
                fill="#334155",
                font=("Segoe UI", 9, "bold"),
            )

            series_points: dict[int, list[float]] = {}
            for sample_index, sample_values in enumerate(capture.samples):
                x_value = capture_start_x + (sample_index * capture.sample_period_us / 1000.0)
                x_canvas = map_x(x_value)
                self._plot_hover_entries.append(
                    {
                        "capture_index": capture_index,
                        "capture": capture,
                        "sample_index": sample_index,
                        "x_canvas": x_canvas,
                        "x_ms": x_value,
                        "relative_ms": sample_index * capture.sample_period_us / 1000.0,
                        "sample_values": list(sample_values),
                    }
                )
                for var_index in visible_var_indices:
                    if var_index >= len(sample_values):
                        continue
                    value = self._scale_value(capture, var_index, sample_values[var_index])
                    if not math.isfinite(value):
                        continue
                    series_points.setdefault(var_index, []).extend((x_canvas, map_y(value)))

            for var_index, points in series_points.items():
                color = SERIES_COLORS[var_index % len(SERIES_COLORS)]
                if len(points) >= 4:
                    canvas.create_line(*points, fill=color, width=1.5, smooth=False)
                if capture_index == visible_capture_indices[-1]:
                    label = capture.var_names[var_index] if var_index < len(capture.var_names) else f"var{var_index}"
                    scale = self._get_var_scale(capture, var_index)
                    if abs(scale - 1.0) > 1e-12:
                        label = f"{label} x{scale:g}"
                    legend_entries.append((label, color))

        legend_x = plot_right - 180
        legend_y = plot_top + 6
        for idx, (label, color) in enumerate(legend_entries[: min(8, len(visible_var_indices))]):
            y = legend_y + idx * 18
            canvas.create_line(legend_x, y + 7, legend_x + 18, y + 7, fill=color, width=2)
            canvas.create_text(legend_x + 24, y, text=label, anchor="nw", fill="#334155", font=("Segoe UI", 9))

        if self._hover_entry is not None:
            hover_capture_index = int(self._hover_entry.get("capture_index", -1))
            hover_sample_index = int(self._hover_entry.get("sample_index", -1))
            matched_entry = next(
                (
                    item
                    for item in self._plot_hover_entries
                    if int(item.get("capture_index", -1)) == hover_capture_index
                    and int(item.get("sample_index", -1)) == hover_sample_index
                ),
                None,
            )
            self._hover_entry = matched_entry
        if self._zoom_rect_start and self._zoom_rect_end:
            self._draw_zoom_rectangle()
        if self._hover_entry is not None:
            self._draw_hover_overlay(self._hover_entry)

    def _on_plot_motion(self, event) -> None:
        if self._zoom_rect_start is not None:
            self._zoom_rect_end = (event.x, event.y)
            self.redraw_plot()
            return
        if not self._plot_hover_entries:
            self._plot_status_var.set(self.i18n.translate_text("Move the mouse over the scope plot to inspect values."))
            self._hover_entry = None
            return

        nearest = min(self._plot_hover_entries, key=lambda item: abs(float(item["x_canvas"]) - event.x))
        self._hover_entry = nearest
        capture = nearest["capture"]
        sample_index = int(nearest["sample_index"])
        x_ms = float(nearest["relative_ms"])
        values = list(nearest["sample_values"])
        visible_var_indices = self._get_visible_var_indices()
        value_parts: list[str] = []
        for var_index in visible_var_indices[:4]:
            if var_index >= len(values):
                continue
            name = capture.var_names[var_index] if var_index < len(capture.var_names) else f"var{var_index}"
            scaled_value = self._scale_value(capture, var_index, values[var_index])
            value_parts.append(f"{name}={scaled_value:.4f}")
        if len(visible_var_indices) > 4:
            value_parts.append("...")
        detail = ", ".join(value_parts) if value_parts else "-"
        self._plot_status_var.set(
            self.i18n.format_text(
                "Capture #{capture} sample {sample} @ {time_ms:.3f} ms: {detail}",
                capture=capture.capture_index,
                sample=sample_index,
                time_ms=x_ms,
                detail=detail,
            )
        )
        if self._alt_pressed:
            self.redraw_plot()

    def _on_plot_leave(self, _event) -> None:
        if self._zoom_rect_start is not None:
            return
        self._hover_entry = None
        self._plot_status_var.set(self.i18n.translate_text("Move the mouse over the scope plot to inspect values."))
        self.redraw_plot()

    def _on_plot_mousewheel(self, event) -> None:
        if not self._plot_bounds or not self._x_range or not self._y_range:
            return
        plot_left, plot_top, plot_right, plot_bottom = self._plot_bounds
        if not (plot_left <= event.x <= plot_right and plot_top <= event.y <= plot_bottom):
            return

        delta_sign = -1 if event.delta > 0 else 1
        if event.state & SHIFT_MASK:
            x_min, x_max = self._x_range
            span = max(x_max - x_min, MIN_ZOOM_SPAN_MS)
            offset = span * 0.12 * delta_sign
            self._manual_x_range = (x_min + offset, x_max + offset)
        elif event.state & CTRL_MASK:
            y_min, y_max = self._y_range
            span = max(y_max - y_min, MIN_ZOOM_SPAN_VALUE)
            offset = span * 0.12 * delta_sign
            self._manual_y_range = (y_min + offset, y_max + offset)
        else:
            x_min, x_max = self._x_range
            y_min, y_max = self._y_range
            x_ratio = (event.x - plot_left) / max(plot_right - plot_left, 1)
            y_ratio = (event.y - plot_top) / max(plot_bottom - plot_top, 1)
            x_anchor = x_min + (x_max - x_min) * x_ratio
            y_anchor = y_max - (y_max - y_min) * y_ratio
            scale = 0.85 if event.delta > 0 else 1.18
            new_x_span = max((x_max - x_min) * scale, MIN_ZOOM_SPAN_MS)
            new_y_span = max((y_max - y_min) * scale, MIN_ZOOM_SPAN_VALUE)
            self._manual_x_range = (
                x_anchor - new_x_span * x_ratio,
                x_anchor + new_x_span * (1.0 - x_ratio),
            )
            self._manual_y_range = (
                y_anchor - new_y_span * (1.0 - y_ratio),
                y_anchor + new_y_span * y_ratio,
            )
        self.redraw_plot()

    def _on_plot_drag_start(self, event) -> None:
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
        elif event.state & CTRL_MASK:
            self._drag_mode = "yzoom"
        else:
            self._drag_mode = "rect"
            self._zoom_rect_start = (event.x, event.y)
            self._zoom_rect_end = (event.x, event.y)
        self.plot_canvas.focus_set()

    def _on_plot_drag_move(self, event) -> None:
        if self._drag_mode == "rect" and self._zoom_rect_start is not None:
            self._zoom_rect_end = (event.x, event.y)
            self.redraw_plot()
            return
        if not self._plot_bounds:
            return
        plot_left, plot_top, plot_right, plot_bottom = self._plot_bounds
        if self._drag_mode == "xzoom" and self._drag_anchor and self._drag_start_x_range:
            anchor_x, _anchor_y = self._drag_anchor
            start_min, start_max = self._drag_start_x_range
            span = max(start_max - start_min, MIN_ZOOM_SPAN_MS)
            anchor_ratio = min(max((anchor_x - plot_left) / max(plot_right - plot_left, 1), 0.0), 1.0)
            anchor_value = start_min + span * anchor_ratio
            delta_x = event.x - anchor_x
            scale = math.exp(-delta_x / 240.0)
            new_span = max(span * scale, MIN_ZOOM_SPAN_MS)
            self._manual_x_range = (
                anchor_value - new_span * anchor_ratio,
                anchor_value + new_span * (1.0 - anchor_ratio),
            )
        elif self._drag_mode == "yzoom" and self._drag_anchor and self._drag_start_y_range:
            _anchor_x, anchor_y = self._drag_anchor
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
        if self._drag_mode in {"xzoom", "yzoom"}:
            self.redraw_plot()

    def _on_plot_drag_end(self, _event) -> None:
        if self._drag_mode == "rect" and self._zoom_rect_start is not None and self._zoom_rect_end is not None:
            self._apply_rect_zoom()
        self._drag_mode = None
        self._drag_anchor = None
        self._drag_start_x_range = None
        self._drag_start_y_range = None
        self._zoom_rect_start = None
        self._zoom_rect_end = None
        self.redraw_plot()

    def _apply_rect_zoom(self) -> None:
        if not self._plot_bounds or not self._x_range or not self._y_range:
            return
        if not self._zoom_rect_start or not self._zoom_rect_end:
            return

        plot_left, plot_top, plot_right, plot_bottom = self._plot_bounds
        x0, y0 = self._zoom_rect_start
        x1, y1 = self._zoom_rect_end
        if abs(x1 - x0) < 8 and abs(y1 - y0) < 8:
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
        if new_end - new_start >= MIN_ZOOM_SPAN_MS:
            self._manual_x_range = (new_start, new_end)

        y_min, y_max = self._y_range
        top_ratio = (min(y0, y1) - plot_top) / max(plot_bottom - plot_top, 1)
        bottom_ratio = (max(y0, y1) - plot_top) / max(plot_bottom - plot_top, 1)
        new_y_max = y_max - (y_max - y_min) * top_ratio
        new_y_min = y_max - (y_max - y_min) * bottom_ratio
        if new_y_max - new_y_min >= MIN_ZOOM_SPAN_VALUE:
            self._manual_y_range = (new_y_min, new_y_max)

    def _resolve_x_range(self, data_x_min: float, data_x_max: float) -> tuple[float, float]:
        if abs(data_x_max - data_x_min) < 1e-9:
            data_x_max = data_x_min + 1.0
        if self._manual_x_range is None:
            return data_x_min, data_x_max
        start, end = self._manual_x_range
        width = max(end - start, MIN_ZOOM_SPAN_MS)
        if start < data_x_min:
            start = data_x_min
            end = start + width
        if end > data_x_max:
            end = data_x_max
            start = end - width
        if start < data_x_min:
            start = data_x_min
        if end <= start:
            end = start + MIN_ZOOM_SPAN_MS
        return start, end

    def _resolve_y_range(self, data_y_min: float, data_y_max: float) -> tuple[float, float]:
        if abs(data_y_max - data_y_min) < 1e-9:
            data_y_min -= 1.0
            data_y_max += 1.0
        if self._manual_y_range is None:
            return data_y_min, data_y_max
        start, end = self._manual_y_range
        height = max(end - start, MIN_ZOOM_SPAN_VALUE)
        if start < data_y_min:
            start = data_y_min
            end = start + height
        if end > data_y_max:
            end = data_y_max
            start = end - height
        if start < data_y_min:
            start = data_y_min
        if end <= start:
            end = start + MIN_ZOOM_SPAN_VALUE
        return start, end

    def _draw_zoom_rectangle(self) -> None:
        if not self._zoom_rect_start or not self._zoom_rect_end:
            return
        x0, y0 = self._zoom_rect_start
        x1, y1 = self._zoom_rect_end
        self.plot_canvas.create_rectangle(x0, y0, x1, y1, outline="#2563eb", dash=(4, 4), width=1)

    def _draw_hover_overlay(self, entry: dict[str, object]) -> None:
        if not self._plot_bounds or not self._x_range or not self._y_range:
            return

        plot_left, plot_top, plot_right, plot_bottom = self._plot_bounds
        x = float(entry["x_canvas"])
        capture = entry["capture"]
        sample_index = int(entry["sample_index"])
        values = list(entry["sample_values"])
        self.plot_canvas.create_line(x, plot_top, x, plot_bottom, fill="#64748b", dash=(4, 4))

        lines = [
            self.i18n.format_text(
                "Capture #{capture} sample {sample} @ {time_ms:.3f} ms",
                capture=capture.capture_index,
                sample=sample_index,
                time_ms=float(entry["relative_ms"]),
            )
        ]
        point_labels: list[tuple[str, str, str]] = []
        for var_index in self._get_visible_var_indices():
            if var_index >= len(values):
                continue
            value = self._scale_value(capture, var_index, values[var_index])
            if not math.isfinite(value):
                continue
            label = capture.var_names[var_index] if var_index < len(capture.var_names) else f"var{var_index}"
            color = SERIES_COLORS[var_index % len(SERIES_COLORS)]
            y = self._value_to_canvas_y(value, plot_top, plot_bottom, *self._y_range)
            self.plot_canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill=color, outline="")
            if self._alt_pressed:
                lines.append(f"{label} = {value:.6f}".rstrip("0").rstrip("."))
            point_labels.append((label, f"{value:.6f}".rstrip('0').rstrip('.'), color))

        if self._alt_pressed:
            self._draw_hover_panel(lines, point_labels, plot_left, plot_top, plot_right, plot_bottom)

    def _draw_hover_panel(
        self,
        lines: list[str],
        point_labels: list[tuple[str, str, str]],
        plot_left: float,
        plot_top: float,
        plot_right: float,
        plot_bottom: float,
    ) -> None:
        visible_rows = lines[:]
        max_rows = max(4, int((plot_bottom - plot_top - 20) // 18) - 1)
        hidden_count = max(0, len(visible_rows) - max_rows)
        if hidden_count:
            visible_rows = visible_rows[:max_rows]
            visible_rows.append(self.i18n.format_text("还有 {count} 项", count=hidden_count))

        padding = 10
        line_height = 18
        box_width = 240
        box_height = padding * 2 + len(visible_rows) * line_height
        x = max(plot_left + 12, plot_right - box_width - 12)
        y = plot_top + 12
        self.plot_canvas.create_rectangle(x, y, x + box_width, y + box_height, fill="#ffffff", outline="#94a3b8", width=1)
        for row_index, row_text in enumerate(visible_rows):
            fill = "#0f172a"
            if "=" in row_text:
                name = row_text.split("=", 1)[0].strip()
                for label_name, _value_text, color in point_labels:
                    if label_name == name:
                        fill = color
                        break
            self.plot_canvas.create_text(x + padding, y + padding + row_index * line_height, text=row_text, anchor="nw", fill=fill, font=("Consolas", 9))

    def _value_to_canvas_y(self, value: float, plot_top: float, plot_bottom: float, y_min: float, y_max: float) -> float:
        return plot_bottom - (value - y_min) / max(y_max - y_min, 1e-9) * (plot_bottom - plot_top)

    def _on_alt_press(self, _event) -> None:
        if self._alt_pressed:
            return
        self._alt_pressed = True
        if self._hover_entry is not None:
            self.redraw_plot()

    def _on_alt_release(self, _event) -> None:
        if not self._alt_pressed:
            return
        self._alt_pressed = False
        if self._hover_entry is not None:
            self.redraw_plot()

    def _on_vars_inner_configure(self, _event) -> None:
        self.vars_canvas.configure(scrollregion=self.vars_canvas.bbox("all"))

    def _on_vars_canvas_configure(self, event) -> None:
        self.vars_canvas.itemconfigure(self.vars_window, width=event.width)

    def _on_capture_inner_configure(self, _event) -> None:
        self.capture_canvas.configure(scrollregion=self.capture_canvas.bbox("all"))

    def _on_capture_canvas_configure(self, event) -> None:
        self.capture_canvas.itemconfigure(self.capture_window, width=event.width)

    def _on_capture_canvas_mousewheel(self, event) -> str:
        self.capture_canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"
