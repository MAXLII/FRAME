from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
import tkinter as tk
from tkinter import ttk

from serial_debug_assistant.ui.theme import ACCENT, BORDER, SURFACE, SURFACE_ALT, TEXT_MUTED


# Views own their coordinates and interaction state; samples stay in the tab.
PLOT_STATE_FIELDS = (
    "_plot_bounds", "_x_range", "_y_range", "_manual_y_range", "_frozen_y_range",
    "_last_hover_index", "_last_hover_canvas_x", "_cached_visible_series",
    "_cached_visible_timestamps", "reference_lines", "_pending_reference_line",
    "_preview_reference_value", "_drag_anchor", "_drag_start_x_range",
    "_drag_start_y_range", "_drag_mode", "_drag_last_x", "_drag_started_live",
    "_zoom_rect_start", "_zoom_rect_end",
)


@dataclass(eq=False)
class PlotWindow:
    number: int
    frame: tk.Frame
    canvas: tk.Canvas
    title: ttk.Label
    legend: tk.Frame
    state: dict
    legend_names: tuple[str, ...] | None = None


class WaveformWindowsMixin:
    def _init_plot_windows(self) -> None:
        self._plot_windows: list[PlotWindow] = []
        self._active_plot: PlotWindow | None = None
        self._current_plot: PlotWindow | None = None
        self._next_plot_number = 1
        self._plot_assignments: dict[str, int] = {}
        self._empty_plot_state = {key: deepcopy(getattr(self, key)) for key in PLOT_STATE_FIELDS}
        self._parameter_drag = None
        self._drop_plot = None
        self._shared_x_range = None
        self._shared_cursor_ratio = 1.0

    def _build_plot_windows(self, parent) -> None:
        self._time_axis_canvas = tk.Canvas(parent, height=34, bg=SURFACE, highlightthickness=0)
        self._time_axis_canvas.grid(row=0, column=0, sticky="ew")
        self._plots_canvas = tk.Canvas(parent, bg=SURFACE, highlightthickness=0)
        self._plots_canvas.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(parent, orient="vertical", command=self._plots_canvas.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self._plots_canvas.configure(yscrollcommand=scroll.set)
        self._plots_grid = tk.Frame(self._plots_canvas, bg=SURFACE)
        self._plots_item = self._plots_canvas.create_window(0, 0, window=self._plots_grid, anchor="nw")
        self._plots_canvas.bind("<Configure>", lambda event: self._layout_plot_windows())
        self._empty_canvas = tk.Canvas(self._plots_grid, bg=SURFACE, highlightthickness=0)
        self.canvas = self._empty_canvas

    def add_plot_window(self) -> PlotWindow:
        frame = tk.Frame(self._plots_grid, bg=SURFACE, highlightthickness=2, highlightbackground=BORDER)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(2, weight=1)
        header = ttk.Frame(frame, style="Panel.TFrame", padding=(6, 3))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        title = ttk.Label(header)
        title.grid(row=0, column=0, sticky="w")
        legend = tk.Frame(frame, bg=SURFACE, height=24)
        legend.grid(row=1, column=0, sticky="ew", padx=6)
        canvas = tk.Canvas(frame, bg=SURFACE, highlightthickness=0)
        canvas.grid(row=2, column=0, sticky="nsew")
        plot = PlotWindow(self._next_plot_number, frame, canvas, title, legend, deepcopy(self._empty_plot_state))
        self._next_plot_number += 1
        ttk.Button(header, text="×", width=3, command=lambda: self.close_plot_window(plot)).grid(row=0, column=1)
        for widget in (header, title):
            widget.bind("<Button-1>", lambda event, p=plot: self._select_plot(p))
        for sequence, handler in (
            ("<Motion>", self._on_canvas_motion), ("<Leave>", self._on_canvas_leave),
            ("<MouseWheel>", self._on_mousewheel), ("<ButtonPress-1>", self._on_drag_start),
            ("<B1-Motion>", self._on_drag_move), ("<ButtonRelease-1>", self._on_drag_end),
        ):
            canvas.bind(sequence, lambda event, p=plot, callback=handler: self._plot_event(p, callback, event))
        canvas.bind("<Enter>", lambda event: self._select_plot(plot))
        canvas.bind("<Configure>", lambda event: self._queue_redraw())
        self._plot_windows.append(plot)
        self._sync_plot_assignments()
        self._select_plot(plot)
        self._layout_plot_windows()
        self._plots_canvas.yview_moveto(1.0)
        self._install_alt_guard_bindtags(frame)
        self._queue_redraw()
        return plot

    def close_plot_window(self, plot: PlotWindow) -> None:
        if plot not in self._plot_windows:
            return
        self._cancel_parameter_drag()
        self._load_plot(None)
        self._plot_windows.remove(plot)
        replacement = self._plot_windows[0] if self._plot_windows else None
        for name, number in list(self._plot_assignments.items()):
            if number == plot.number:
                if replacement is None:
                    del self._plot_assignments[name]
                else:
                    self._plot_assignments[name] = replacement.number
        if self._active_plot is plot:
            self._active_plot = replacement
        plot.frame.destroy()
        self._load_plot(self._active_plot)
        self._layout_plot_windows()
        self._refresh_active_latest_values()
        self._queue_redraw()

    def _load_plot(self, plot: PlotWindow | None) -> None:
        if self._current_plot is plot:
            return
        if self._current_plot is not None:
            self._current_plot.state = {key: getattr(self, key) for key in PLOT_STATE_FIELDS}
        state = plot.state if plot is not None else deepcopy(self._empty_plot_state)
        for key, value in state.items():
            setattr(self, key, value)
        self.canvas = plot.canvas if plot is not None else self._empty_canvas
        self._current_plot = plot

    def _select_plot(self, plot: PlotWindow) -> None:
        if plot not in self._plot_windows or self._parameter_drag is not None:
            return
        changed = self._active_plot is not plot
        self._active_plot = plot
        self._load_plot(plot)
        if changed:
            self._highlight_plot_windows()
            self._refresh_active_latest_values()
            self._queue_redraw()

    def _refresh_active_latest_values(self) -> None:
        if self._latest_refresh_job is not None:
            self.after_cancel(self._latest_refresh_job)
        self._run_latest_refresh()

    def _plot_event(self, plot, callback, event):
        if plot not in self._plot_windows or self._parameter_drag is not None:
            return
        self._select_plot(plot)
        return callback(event)

    def _layout_plot_windows(self) -> None:
        count = len(self._plot_windows)
        width = max(self._plots_canvas.winfo_width(), 1)
        rows = max(1, count)
        height = max(self._plots_canvas.winfo_height(), rows * 200)
        self._plots_canvas.itemconfigure(self._plots_item, width=width, height=height)
        self._plots_canvas.configure(scrollregion=(0, 0, width, height))
        for row in range(max(self._plots_grid.grid_size()[1], rows)):
            self._plots_grid.rowconfigure(row, weight=1 if row < rows else 0, minsize=0, uniform="plot_rows" if row < rows else "")
        self._plots_grid.columnconfigure(0, weight=1)
        self._empty_canvas.grid_forget()
        if not count:
            self._empty_canvas.grid(row=0, column=0, sticky="nsew")
        for index, plot in enumerate(self._plot_windows):
            plot.frame.grid(row=index, column=0, sticky="nsew", padx=3, pady=3)
        self._highlight_plot_windows()
        self._queue_redraw()

    def _highlight_plot_windows(self) -> None:
        for plot in self._plot_windows:
            plot.frame.configure(highlightbackground=ACCENT if plot is self._drop_plot or plot is self._active_plot else BORDER)

    def _sync_plot_assignments(self) -> None:
        current_names = set(self.selected_names)
        self._plot_assignments = {name: number for name, number in self._plot_assignments.items() if name in current_names}
        if self._plot_windows:
            for name in self.selected_names:
                self._plot_assignments.setdefault(name, self._plot_windows[0].number)

    def _visible_plot_names(self) -> list[str]:
        plot = self._current_plot
        return [name for name in self.selected_names if name in self.visible_names and plot is not None
                and self._plot_assignments.get(name) == plot.number]

    def _refresh_plot_legends(self) -> None:
        self.reference_panel.configure(text=self.i18n.translate_text("参考线数值"))
        self.latest_panel.configure(text=self.i18n.translate_text("最新值"))
        for plot in self._plot_windows:
            plot.title.configure(text=self.i18n.format_text("波形窗口 {number}", number=plot.number))
            names = tuple(name for name in self.selected_names if name in self.visible_names
                          and self._plot_assignments.get(name) == plot.number)
            if names == plot.legend_names:
                continue
            plot.legend_names = names
            for child in plot.legend.winfo_children():
                child.destroy()
            for name in names:
                label = tk.Label(plot.legend, text=name, bg=SURFACE_ALT, fg=self._series_color(name), cursor="hand2")
                label.pack(side="left", padx=(0, 6), pady=2)
                self._bind_parameter_drag(label, name)

    def _bind_parameter_drag(self, widget, name: str) -> None:
        widget.bind("<ButtonPress-1>", lambda event: self._start_parameter_drag(event, name))
        widget.bind("<B1-Motion>", self._move_parameter_drag)
        widget.bind("<ButtonRelease-1>", self._finish_parameter_drag)

    def _start_parameter_drag(self, event, name: str) -> None:
        self._parameter_drag = (name, event.x_root, event.y_root, event.widget, False)

    def _plot_at(self, x_root, y_root):
        widget = self.winfo_containing(x_root, y_root)
        while widget is not None:
            for plot in self._plot_windows:
                if widget is plot.frame:
                    return plot
            widget = widget.master
        return None

    def _move_parameter_drag(self, event) -> None:
        if self._parameter_drag is None:
            return
        name, x, y, widget, started = self._parameter_drag
        started = started or abs(event.x_root - x) + abs(event.y_root - y) >= 6
        self._parameter_drag = (name, x, y, widget, started)
        if started:
            widget.configure(cursor="fleur")
            self._drop_plot = self._plot_at(event.x_root, event.y_root)
            self._highlight_plot_windows()

    def _finish_parameter_drag(self, event) -> None:
        drag = self._parameter_drag
        target = self._plot_at(event.x_root, event.y_root) if drag is not None and drag[4] else None
        self._cancel_parameter_drag()
        if target is not None:
            self.move_parameter_to_plot(drag[0], target)

    def _cancel_parameter_drag(self) -> None:
        if self._parameter_drag is not None:
            widget = self._parameter_drag[3]
            if widget.winfo_exists():
                widget.configure(cursor="")
        self._parameter_drag = None
        self._drop_plot = None
        self._highlight_plot_windows()

    def move_parameter_to_plot(self, name: str, plot: PlotWindow) -> None:
        if name not in self.selected_names or plot not in self._plot_windows:
            return
        self._plot_assignments[name] = plot.number
        self.visible_names.add(name)
        self._refresh_row_widget(name)
        self._update_select_all_visible_state()
        self._select_plot(plot)
        self._queue_latest_refresh()
        self._queue_redraw()

    def redraw(self) -> None:
        self._refresh_plot_legends()
        bounds = [self._timestamps_for(name) for name in self.selected_names if name in self.visible_names]
        bounds = [(values[0], values[-1]) for values in bounds if values]
        self._shared_x_range = self._resolve_x_range(min(pair[0] for pair in bounds), max(pair[1] for pair in bounds)) if bounds else None
        self._time_axis_canvas.delete("all")
        if not self._plot_windows:
            self.canvas.delete("all")
            self.canvas.create_text(20, 30, anchor="nw", text=self.i18n.translate_text("点击“新增窗口”开始显示波形"), fill=TEXT_MUTED)
            self._draw_hover_panel([], [], 0, 0, 0, 0)
            return
        try:
            for plot in self._plot_windows:
                self._load_plot(plot)
                self._redraw_plot()
        finally:
            self._load_plot(self._active_plot)
            if self._shared_x_range is not None:
                self.view_var.set(self._build_view_text(*self._shared_x_range))
        self._draw_shared_time_axis()
        self._update_shared_reference_values()

    def _draw_shared_time_axis(self) -> None:
        if self._shared_x_range is None or not self._plot_windows:
            return
        first = self._plot_windows[0].canvas
        offset = first.winfo_rootx() - self._time_axis_canvas.winfo_rootx()
        left, right = offset + 72, offset + max(first.winfo_width(), 100) - 24
        x_min, x_max = self._shared_x_range
        for tick in range(5):
            ratio = tick / 4
            x = left + (right - left) * ratio
            self._time_axis_canvas.create_line(x, 24, x, 32, fill=BORDER)
            self._time_axis_canvas.create_text(x, 12, text=self._format_time_axis_value(x_min + (x_max - x_min) * ratio), fill=TEXT_MUTED)
        x = left + (right - left) * self._shared_cursor_ratio
        self._time_axis_canvas.create_line(x, 0, x, 34, fill=ACCENT, dash=(4, 4))

    def _draw_shared_cursor(self) -> None:
        if self._plot_bounds is None or self._shared_x_range is None:
            return
        left, top, right, bottom = self._plot_bounds
        self._last_hover_canvas_x = left + (right - left) * self._shared_cursor_ratio
        self.canvas.create_line(self._last_hover_canvas_x, top, self._last_hover_canvas_x, bottom,
                                fill=TEXT_MUTED, dash=(4, 4), tags="shared_cursor")

    def _update_shared_reference_values(self) -> None:
        if self._shared_x_range is None:
            self._draw_hover_panel([], [], 0, 0, 0, 0)
            return
        x_min, x_max = self._shared_x_range
        timestamp = x_min + (x_max - x_min) * self._shared_cursor_ratio
        labels = []
        for name in self.selected_names:
            if name not in self.visible_names:
                continue
            sample = self._nearest_sample(self.series_data.get(name, []), timestamp, self._timestamps_for(name))
            value = sample[1] if sample and x_min <= sample[0] <= x_max else None
            text = self._format_numeric(value) if value is not None and math.isfinite(value) else "/"
            labels.append((name, text, self._series_color(name), 0.0))
        self._draw_hover_panel(labels, [self._format_time_axis_value(timestamp, milliseconds=True)], 0, 0, 0, 0)

    def _plot_reference_lines(self):
        vertical = set()
        for plot in self._plot_windows:
            lines = self.reference_lines if plot is self._current_plot else plot.state["reference_lines"]
            vertical.update(value for orientation, value in lines if orientation == "vertical")
        return [(orientation, value) for orientation, value in self.reference_lines if orientation != "vertical"] + [
            ("vertical", value) for value in sorted(vertical)]

    def _clear_plot_reference_lines(self) -> bool:
        self._load_plot(None)
        had_lines = False
        for plot in self._plot_windows:
            had_lines |= bool(plot.state["reference_lines"]) or plot.state["_pending_reference_line"] is not None
            plot.state["reference_lines"] = []
            plot.state["_pending_reference_line"] = None
            plot.state["_preview_reference_value"] = None
        self._load_plot(self._active_plot)
        return had_lines

    def _reset_plot_views(self) -> None:
        self._cancel_parameter_drag()
        self._shared_cursor_ratio = 1.0
        self._shared_x_range = None
        self._load_plot(None)
        for plot in self._plot_windows:
            plot.state = deepcopy(self._empty_plot_state)
        self._load_plot(self._active_plot)

    def _freeze_plot_y_ranges(self) -> None:
        self._load_plot(None)
        for plot in self._plot_windows:
            plot.state["_frozen_y_range"] = plot.state["_y_range"]
        self._load_plot(self._active_plot)

    def _reset_plot_y_ranges(self) -> None:
        self._load_plot(None)
        for plot in self._plot_windows:
            plot.state["_manual_y_range"] = None
            plot.state["_frozen_y_range"] = None
        self._load_plot(self._active_plot)
