from __future__ import annotations

from bisect import bisect_left
import math
import tkinter as tk
from tkinter import ttk

from serial_debug_assistant.i18n import I18nManager
from serial_debug_assistant.models import SfraInfo, SfraListItem, SfraPoint
from serial_debug_assistant.sfra_protocol import describe_sfra_state
from serial_debug_assistant.ui.theme import ACCENT, BORDER_MUTED, DANGER, SURFACE_ALT, TEXT, TEXT_MUTED


class SfraTab(ttk.Frame):
    def __init__(
        self,
        master,
        *,
        on_refresh_loops,
        on_refresh_info,
        on_apply_config,
        on_start,
        on_stop,
        on_reset,
        i18n: I18nManager,
    ) -> None:
        super().__init__(master, style="Panel.TFrame", padding=12)
        self.i18n = i18n
        self.on_refresh_loops = on_refresh_loops
        self.on_refresh_info = on_refresh_info
        self.on_apply_config = on_apply_config
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_reset = on_reset
        self._translatable_widgets: list[tuple[object, str, str]] = []

        self.target_addr_var = tk.StringVar(value="2")
        self.dynamic_addr_var = tk.StringVar(value="0")
        self.sfra_var = tk.StringVar()
        self.start_freq_var = tk.StringVar(value="100")
        self.stop_freq_var = tk.StringVar(value="10000")
        self.amplitude_var = tk.StringVar(value="0.01")
        self.length_var = tk.StringVar(value="-")
        self.state_var = tk.StringVar(value="-")
        self.current_freq_var = tk.StringVar(value="-")
        self.progress_text_var = tk.StringVar(value="0 / 0")
        self.status_var = tk.StringVar(value=self.i18n.translate_text("Waiting for SFRA actions"))
        self.detail_var = tk.StringVar(value=self.i18n.translate_text("Refresh SFRA loops, then read config."))
        self._plot_status_var = tk.StringVar(value=self.i18n.translate_text("Move the mouse over the Bode plot to inspect points."))
        self.progress_var = tk.DoubleVar(value=0.0)

        self._sfra_choices: list[SfraListItem] = []
        self._sfra_name_to_id: dict[str, int] = {}
        self._points_by_index: dict[int, SfraPoint] = {}
        self._point_count = 0
        self._hover_points: list[SfraPoint] = []
        self._mag_bounds: tuple[float, float, float, float] | None = None
        self._phase_bounds: tuple[float, float, float, float] | None = None

        self._build()

    def _remember_text(self, widget: object, text: str, option: str = "text") -> None:
        self._translatable_widgets.append((widget, text, option))

    def _build(self) -> None:
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        side = ttk.Frame(self, style="Panel.TFrame")
        side.grid(row=0, column=0, sticky="nsw", padx=(0, 12))
        side.columnconfigure(0, weight=1)

        select_frame = ttk.LabelFrame(side, text=self.i18n.translate_text("SFRA Loop"), style="Section.TLabelframe", padding=12)
        self._remember_text(select_frame, "SFRA Loop")
        select_frame.grid(row=0, column=0, sticky="ew")
        select_frame.columnconfigure(1, weight=1)

        self._add_label(select_frame, "Target Address", 0, 0)
        ttk.Entry(select_frame, textvariable=self.target_addr_var, width=12).grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=2)
        self._add_label(select_frame, "Dynamic Address", 1, 0)
        ttk.Entry(select_frame, textvariable=self.dynamic_addr_var, width=12).grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=2)
        self._add_label(select_frame, "Loop", 2, 0)
        self.sfra_combo = ttk.Combobox(select_frame, textvariable=self.sfra_var, values=(), state="readonly", width=22)
        self.sfra_combo.grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=2)
        self.sfra_combo.bind("<<ComboboxSelected>>", lambda _event: self.on_refresh_info())

        button_row = ttk.Frame(select_frame, style="Panel.TFrame")
        button_row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.refresh_button = ttk.Button(button_row, text=self.i18n.translate_text("Refresh Loops"), command=self.on_refresh_loops)
        self.refresh_button.grid(row=0, column=0, sticky="ew")
        self._remember_text(self.refresh_button, "Refresh Loops")
        self.info_button = ttk.Button(button_row, text=self.i18n.translate_text("Read Config"), command=self.on_refresh_info)
        self.info_button.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self._remember_text(self.info_button, "Read Config")

        config_frame = ttk.LabelFrame(side, text=self.i18n.translate_text("Sweep Config"), style="Section.TLabelframe", padding=12)
        self._remember_text(config_frame, "Sweep Config")
        config_frame.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        config_frame.columnconfigure(1, weight=1)

        self._add_label(config_frame, "Start Frequency (Hz)", 0, 0)
        ttk.Entry(config_frame, textvariable=self.start_freq_var, width=14).grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=2)
        self._add_label(config_frame, "Stop Frequency (Hz)", 1, 0)
        ttk.Entry(config_frame, textvariable=self.stop_freq_var, width=14).grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=2)
        self._add_label(config_frame, "Injection Amplitude", 2, 0)
        ttk.Entry(config_frame, textvariable=self.amplitude_var, width=14).grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=2)
        self._add_label(config_frame, "Frequency Points", 3, 0)
        ttk.Label(config_frame, textvariable=self.length_var).grid(row=3, column=1, sticky="w", padx=(8, 0), pady=2)
        self.apply_button = ttk.Button(config_frame, text=self.i18n.translate_text("Apply Config"), command=self.on_apply_config, style="Accent.TButton")
        self.apply_button.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self._remember_text(self.apply_button, "Apply Config")

        control_frame = ttk.LabelFrame(side, text=self.i18n.translate_text("Sweep Control"), style="Section.TLabelframe", padding=12)
        self._remember_text(control_frame, "Sweep Control")
        control_frame.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        control_frame.columnconfigure(0, weight=1)
        control_frame.columnconfigure(1, weight=1)
        control_frame.columnconfigure(2, weight=1)
        self.start_button = ttk.Button(control_frame, text=self.i18n.translate_text("Start Sweep"), command=self.on_start, style="Accent.TButton")
        self.start_button.grid(row=0, column=0, sticky="ew")
        self._remember_text(self.start_button, "Start Sweep")
        self.stop_button = ttk.Button(control_frame, text=self.i18n.translate_text("Stop"), command=self.on_stop)
        self.stop_button.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self._remember_text(self.stop_button, "Stop")
        self.reset_button = ttk.Button(control_frame, text=self.i18n.translate_text("Reset"), command=self.on_reset)
        self.reset_button.grid(row=0, column=2, sticky="ew", padx=(8, 0))
        self._remember_text(self.reset_button, "Reset")
        ttk.Progressbar(control_frame, variable=self.progress_var, maximum=100.0).grid(row=1, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        ttk.Label(control_frame, textvariable=self.progress_text_var).grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))

        status_frame = ttk.LabelFrame(side, text=self.i18n.translate_text("Status"), style="Section.TLabelframe", padding=12)
        self._remember_text(status_frame, "Status")
        status_frame.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        status_frame.columnconfigure(1, weight=1)
        self._add_label(status_frame, "State", 0, 0)
        ttk.Label(status_frame, textvariable=self.state_var).grid(row=0, column=1, sticky="w", padx=(8, 0), pady=2)
        self._add_label(status_frame, "Current Frequency", 1, 0)
        ttk.Label(status_frame, textvariable=self.current_freq_var).grid(row=1, column=1, sticky="w", padx=(8, 0), pady=2)
        ttk.Label(status_frame, textvariable=self.status_var, style="Header.TLabel").grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Label(status_frame, textvariable=self.detail_var, wraplength=260).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        plot_frame = ttk.Frame(self, style="Panel.TFrame")
        plot_frame.grid(row=0, column=1, sticky="nsew")
        plot_frame.columnconfigure(0, weight=1)
        plot_frame.rowconfigure(0, weight=1)
        plot_frame.rowconfigure(1, weight=1)
        self.mag_canvas = tk.Canvas(plot_frame, bg=SURFACE_ALT, highlightthickness=1, highlightbackground=BORDER_MUTED)
        self.phase_canvas = tk.Canvas(plot_frame, bg=SURFACE_ALT, highlightthickness=1, highlightbackground=BORDER_MUTED)
        self.mag_canvas.grid(row=0, column=0, sticky="nsew")
        self.phase_canvas.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        ttk.Label(plot_frame, textvariable=self._plot_status_var, style="Status.TLabel").grid(row=2, column=0, sticky="ew", pady=(8, 0))
        for canvas in (self.mag_canvas, self.phase_canvas):
            canvas.bind("<Configure>", lambda _event: self._redraw_plots())
            canvas.bind("<Motion>", self._on_plot_motion)
            canvas.bind("<Leave>", self._on_plot_leave)

        self._redraw_plots()

    def _add_label(self, parent: ttk.Frame, text: str, row: int, column: int) -> None:
        label = ttk.Label(parent, text=self.i18n.translate_text(text))
        label.grid(row=row, column=column, sticky="w", pady=2)
        self._remember_text(label, text)

    def get_target_address(self) -> tuple[int, int]:
        dst = int(self.target_addr_var.get().strip(), 0)
        d_dst = int(self.dynamic_addr_var.get().strip(), 0)
        if not (0 <= dst <= 0xFF and 0 <= d_dst <= 0xFF):
            raise ValueError("Target and dynamic addresses must be in 0..255.")
        return dst, d_dst

    def get_selected_sfra_id(self) -> int:
        selected_name = self.sfra_var.get().strip()
        if not selected_name or selected_name not in self._sfra_name_to_id:
            raise ValueError("Please select an SFRA loop first.")
        return self._sfra_name_to_id[selected_name]

    def get_selected_sfra_name(self) -> str:
        return self.sfra_var.get().strip()

    def get_config_values(self) -> tuple[float, float, float]:
        start_hz = float(self.start_freq_var.get().strip())
        stop_hz = float(self.stop_freq_var.get().strip())
        amplitude = float(self.amplitude_var.get().strip())
        if start_hz <= 0.0 or stop_hz < start_hz or amplitude <= 0.0:
            raise ValueError("Start frequency, stop frequency, and amplitude must be valid positive values.")
        return start_hz, stop_hz, amplitude

    def set_sfra_items(self, items: list[SfraListItem]) -> None:
        self._sfra_choices = list(items)
        self._sfra_name_to_id = {item.name: item.sfra_id for item in items}
        names = [item.name for item in items]
        self.sfra_combo.configure(values=names)
        if names:
            current = self.sfra_var.get().strip()
            self.sfra_var.set(current if current in self._sfra_name_to_id else names[0])
        else:
            self.sfra_var.set("")

    def set_sfra_info(self, info: SfraInfo | None) -> None:
        if info is None:
            self.state_var.set("-")
            self.current_freq_var.set("-")
            self.length_var.set("-")
            return
        self.start_freq_var.set(self._format_float(info.freq_start_hz))
        self.stop_freq_var.set(self._format_float(info.freq_end_hz))
        self.amplitude_var.set(self._format_float(info.inject_amplitude))
        self.length_var.set(str(info.freq_length))
        self.state_var.set(self.i18n.translate_text(describe_sfra_state(info.state)))
        self.current_freq_var.set(f"{info.current_freq_hz:.3f} Hz" if info.current_freq_hz > 0 else "-")
        self._point_count = max(0, int(info.freq_length))
        self._set_progress(info.table_length, self._point_count)

    def begin_sweep(self, point_count: int, sweep_tag: int) -> None:
        self._points_by_index.clear()
        self._point_count = max(0, point_count)
        self._set_progress(0, self._point_count)
        self.current_freq_var.set("-")
        self.state_var.set(self.i18n.translate_text("Running"))
        self.set_status("Sweep running", f"Sweep tag {sweep_tag}")
        self._redraw_plots()

    def add_point(self, point: SfraPoint) -> None:
        self._points_by_index[point.point_index] = point
        self._point_count = max(self._point_count, point.point_count)
        self.current_freq_var.set(f"{point.freq_hz:.3f} Hz")
        self._set_progress(len(self._points_by_index), self._point_count)
        self._redraw_plots()

    def finish_sweep(self) -> None:
        self._set_progress(self._point_count, self._point_count)
        self.state_var.set(self.i18n.translate_text("Done"))
        self.set_status("Sweep complete", self.i18n.format_text("Received {count} point(s).", count=len(self._points_by_index)))

    def set_status(self, title: str, detail: str = "") -> None:
        self.status_var.set(self.i18n.translate_text(title))
        self.detail_var.set(self.i18n.translate_text(detail) if detail else "")

    def refresh_texts(self) -> None:
        for widget, source_text, option in self._translatable_widgets:
            widget.configure(**{option: self.i18n.translate_text(source_text)})

    def _set_progress(self, current: int, total: int) -> None:
        current = max(0, current)
        total = max(0, total)
        percent = 0.0 if total <= 0 else min(100.0, (current / total) * 100.0)
        self.progress_var.set(percent)
        self.progress_text_var.set(f"{current} / {total}")

    def _format_float(self, value: float) -> str:
        if not math.isfinite(value):
            return "0"
        return f"{value:.6g}"

    def _redraw_plots(self) -> None:
        points = [point for _, point in sorted(self._points_by_index.items(), key=lambda item: item[0])]
        self._hover_points = [point for point in points if point.freq_hz > 0 and math.isfinite(point.freq_hz)]
        self._draw_plot(
            self.mag_canvas,
            points,
            title="Magnitude (dB) vs Frequency (Hz)",
            value_getter=lambda point: point.magnitude_db,
            y_label="dB",
            color=DANGER,
            bounds_attr="_mag_bounds",
        )
        self._draw_plot(
            self.phase_canvas,
            points,
            title="Phase (deg) vs Frequency (Hz)",
            value_getter=lambda point: point.phase_deg,
            y_label="deg",
            color=ACCENT,
            bounds_attr="_phase_bounds",
        )

    def _draw_plot(self, canvas: tk.Canvas, points: list[SfraPoint], *, title: str, value_getter, y_label: str, color: str, bounds_attr: str) -> None:
        canvas.delete("all")
        width = max(1, canvas.winfo_width())
        height = max(1, canvas.winfo_height())
        left, top, right, bottom = 58.0, 28.0, width - 18.0, height - 34.0
        setattr(self, bounds_attr, (left, top, right, bottom))
        canvas.create_text(width / 2, 14, text=title, fill=TEXT, font=("Segoe UI", 10, "bold"))
        canvas.create_rectangle(left, top, right, bottom, outline=BORDER_MUTED)
        for i in range(1, 5):
            y = top + (bottom - top) * i / 5.0
            canvas.create_line(left, y, right, y, fill=BORDER_MUTED)
            x = left + (right - left) * i / 5.0
            canvas.create_line(x, top, x, bottom, fill=BORDER_MUTED)

        finite = [(point.freq_hz, value_getter(point)) for point in points if point.freq_hz > 0 and math.isfinite(value_getter(point))]
        if not finite:
            canvas.create_text((left + right) / 2, (top + bottom) / 2, text="No sweep data", fill=TEXT_MUTED)
            return

        freqs = [item[0] for item in finite]
        values = [item[1] for item in finite]
        min_freq = min(freqs)
        max_freq = max(freqs)
        if max_freq <= min_freq:
            max_freq = min_freq * 10.0
        min_log = math.log10(min_freq)
        max_log = math.log10(max_freq)
        min_value = min(values)
        max_value = max(values)
        if max_value <= min_value:
            pad = 1.0
        else:
            pad = (max_value - min_value) * 0.12
        y_min = min_value - pad
        y_max = max_value + pad
        if y_max <= y_min:
            y_max = y_min + 1.0

        for i in range(6):
            value = y_min + (y_max - y_min) * (5 - i) / 5.0
            y = top + (bottom - top) * i / 5.0
            canvas.create_text(left - 8, y, text=f"{value:.1f}", anchor="e", fill=TEXT_MUTED, font=("Segoe UI", 8))
        canvas.create_text(8, (top + bottom) / 2, text=y_label, anchor="w", fill=TEXT_MUTED, font=("Segoe UI", 8))

        coords: list[float] = []
        for freq, value in finite:
            x = left + (math.log10(freq) - min_log) / (max_log - min_log) * (right - left)
            y = bottom - (value - y_min) / (y_max - y_min) * (bottom - top)
            coords.extend([x, y])
        if len(coords) >= 4:
            canvas.create_line(*coords, fill=color, width=2)
        for x, y in zip(coords[0::2], coords[1::2]):
            canvas.create_oval(x - 2.5, y - 2.5, x + 2.5, y + 2.5, fill=color, outline="")

        canvas.create_text(left, bottom + 16, text=f"{min_freq:.3g}", anchor="w", fill=TEXT_MUTED, font=("Segoe UI", 8))
        canvas.create_text(right, bottom + 16, text=f"{max_freq:.3g}", anchor="e", fill=TEXT_MUTED, font=("Segoe UI", 8))

    def _on_plot_motion(self, event: tk.Event) -> None:
        if not self._hover_points:
            return
        bounds = self._mag_bounds if event.widget == self.mag_canvas else self._phase_bounds
        if bounds is None:
            return
        left, _top, right, _bottom = bounds
        if right <= left:
            return
        freqs = [point.freq_hz for point in self._hover_points]
        min_freq = min(freqs)
        max_freq = max(freqs)
        if max_freq <= min_freq:
            target_freq = min_freq
        else:
            ratio = min(1.0, max(0.0, (event.x - left) / (right - left)))
            target_freq = 10 ** (math.log10(min_freq) + ratio * (math.log10(max_freq) - math.log10(min_freq)))
        index = bisect_left(freqs, target_freq)
        candidates = []
        if index < len(self._hover_points):
            candidates.append(self._hover_points[index])
        if index > 0:
            candidates.append(self._hover_points[index - 1])
        if not candidates:
            return
        point = min(candidates, key=lambda item: abs(math.log10(item.freq_hz) - math.log10(target_freq)))
        self._plot_status_var.set(
            f"#{point.point_index}: {point.freq_hz:.3f} Hz, {point.magnitude_db:.3f} dB, {point.phase_deg:.3f} deg"
        )

    def _on_plot_leave(self, _event: tk.Event) -> None:
        self._plot_status_var.set(self.i18n.translate_text("Move the mouse over the Bode plot to inspect points."))
