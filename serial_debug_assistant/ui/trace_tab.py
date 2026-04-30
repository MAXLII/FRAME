from __future__ import annotations

from dataclasses import dataclass
import tkinter as tk
from tkinter import ttk

from serial_debug_assistant.i18n import I18nManager

TRACE_BG = "#08161b"
TRACE_PANEL = "#0d1b22"
TRACE_PANEL_ALT = "#101f27"
TRACE_BORDER = "#263b45"
TRACE_TEXT = "#d8e2e7"
TRACE_MUTED = "#8fa3ad"
TRACE_CYAN = "#2ec7f0"
TRACE_PURPLE = "#8b6df6"
TRACE_ORANGE = "#ff9f2f"
TRACE_GREEN = "#62d26f"
TRACE_BLUE_SELECT = "#123552"


@dataclass(frozen=True)
class TraceRecord:
    index: int
    time_tick: int
    line: int
    time_unit_us: int

    @property
    def time_us(self) -> int:
        return self.time_tick * self.time_unit_us

    @property
    def time_ms(self) -> float:
        return self.time_us / 1000.0


class TraceTab(ttk.Frame):
    def __init__(
        self,
        master,
        *,
        on_toggle_trace,
        on_status,
        i18n: I18nManager,
    ) -> None:
        super().__init__(master, style="Trace.TFrame", padding=16)
        self.i18n = i18n
        self.on_toggle_trace = on_toggle_trace
        self.on_status = on_status

        self.target_addr_var = tk.StringVar(value="3")
        self.dynamic_addr_var = tk.StringVar(value="0")
        self.search_line_var = tk.StringVar()
        self.status_var = tk.StringVar(value="等待开始")
        self.record_count_var = tk.StringVar(value="0")
        self.last_time_var = tk.StringVar(value="-")
        self.last_line_var = tk.StringVar(value="-")
        self.rate_var = tk.StringVar(value="0/s")
        self.time_unit_var = tk.StringVar(value="100 us")

        self._records: list[TraceRecord] = []
        self._running = False
        self._time_unit_us = 100

        self._configure_trace_styles()
        self._build()

    def _configure_trace_styles(self) -> None:
        style = ttk.Style(self)
        style.configure("Trace.TFrame", background=TRACE_BG)
        style.configure("Trace.Panel.TFrame", background=TRACE_PANEL)
        style.configure("Trace.Toolbar.TFrame", background=TRACE_PANEL_ALT)
        style.configure("Trace.TLabel", background=TRACE_BG, foreground=TRACE_TEXT, font=("Segoe UI", 10))
        style.configure("Trace.Muted.TLabel", background=TRACE_BG, foreground=TRACE_MUTED, font=("Segoe UI", 9))
        style.configure("Trace.Panel.TLabel", background=TRACE_PANEL, foreground=TRACE_TEXT, font=("Segoe UI", 10))
        style.configure("Trace.PanelMuted.TLabel", background=TRACE_PANEL, foreground=TRACE_MUTED, font=("Segoe UI", 9))
        style.configure("Trace.Title.TLabel", background=TRACE_BG, foreground=TRACE_TEXT, font=("Segoe UI Semibold", 18))
        style.configure("Trace.Header.TLabel", background=TRACE_BG, foreground=TRACE_TEXT, font=("Segoe UI Semibold", 11))
        style.configure("Trace.PanelTitle.TLabel", background=TRACE_PANEL, foreground=TRACE_TEXT, font=("Segoe UI Semibold", 18))
        style.configure("Trace.PanelHeader.TLabel", background=TRACE_PANEL, foreground=TRACE_TEXT, font=("Segoe UI Semibold", 11))
        style.configure("Trace.Value.TLabel", background=TRACE_PANEL, foreground=TRACE_TEXT, font=("Segoe UI Semibold", 19))
        style.configure("Trace.Cyan.TLabel", background=TRACE_BG, foreground=TRACE_CYAN, font=("Segoe UI Semibold", 10))
        style.configure("Trace.Status.TLabel", background=TRACE_PANEL_ALT, foreground=TRACE_CYAN, font=("Segoe UI Semibold", 10))
        style.configure("Trace.TButton", background=TRACE_PANEL_ALT, foreground=TRACE_TEXT, bordercolor=TRACE_BORDER, padding=(12, 7))
        style.map("Trace.TButton", background=[("active", "#162a34"), ("pressed", "#1b3440")])
        style.configure("Trace.Accent.TButton", background="#123a4c", foreground=TRACE_TEXT, bordercolor=TRACE_CYAN, padding=(12, 7))
        style.map("Trace.Accent.TButton", background=[("active", "#174b62"), ("pressed", "#1d5c78")])
        style.configure("Trace.Stop.TButton", background="#2a1720", foreground=TRACE_TEXT, bordercolor="#ff5d73", padding=(12, 7))
        style.map("Trace.Stop.TButton", background=[("active", "#3a1e2a"), ("pressed", "#4b2635")])
        style.configure("Trace.TEntry", fieldbackground="#0b151b", foreground=TRACE_TEXT, insertcolor=TRACE_TEXT, bordercolor=TRACE_BORDER)
        style.configure("Trace.Treeview", background=TRACE_PANEL, fieldbackground=TRACE_PANEL, foreground=TRACE_TEXT, bordercolor=TRACE_BORDER, rowheight=34)
        style.configure("Trace.Treeview.Heading", background="#0a151b", foreground=TRACE_MUTED, font=("Segoe UI Semibold", 10), bordercolor=TRACE_BORDER)
        style.map(
            "Trace.Treeview",
            background=[("selected", TRACE_BLUE_SELECT)],
            foreground=[("selected", TRACE_TEXT)],
        )

    def _build(self) -> None:
        self.columnconfigure(0, weight=0, minsize=320)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        side = ttk.Frame(self, style="Trace.Panel.TFrame", padding=16)
        side.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        side.columnconfigure(0, weight=1)

        ttk.Label(side, text="FRAME 代码执行跟踪", style="Trace.PanelHeader.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(side, text="代码执行跟踪", style="Trace.PanelTitle.TLabel").grid(row=1, column=0, sticky="w", pady=(18, 4))
        ttk.Label(
            side,
            text="下位机运行后主动上报 time:uint32 和 line:uint16",
            style="Trace.PanelMuted.TLabel",
            wraplength=260,
        ).grid(row=2, column=0, sticky="ew", pady=(0, 18))

        control = ttk.Frame(side, style="Trace.Panel.TFrame")
        control.grid(row=3, column=0, sticky="ew")
        control.columnconfigure(1, weight=1)
        ttk.Label(control, text="Target", style="Trace.PanelMuted.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        ttk.Entry(control, textvariable=self.target_addr_var, width=10, style="Trace.TEntry").grid(row=0, column=1, sticky="ew", pady=(0, 8))
        ttk.Label(control, text="Dyn", style="Trace.PanelMuted.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 8))
        ttk.Entry(control, textvariable=self.dynamic_addr_var, width=10, style="Trace.TEntry").grid(row=1, column=1, sticky="ew", pady=(0, 8))
        self.toggle_button = ttk.Button(control, text="开始上报", command=self.on_toggle_trace, style="Trace.Accent.TButton")
        self.toggle_button.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 16))
        ttk.Label(control, text="行号搜索", style="Trace.PanelMuted.TLabel").grid(row=3, column=0, sticky="w", pady=(0, 8))
        ttk.Entry(control, textvariable=self.search_line_var, style="Trace.TEntry").grid(row=3, column=1, sticky="ew", pady=(0, 8))
        self.search_line_var.trace_add("write", lambda *_args: self._refresh_highlights())
        ttk.Label(control, text="状态", style="Trace.PanelMuted.TLabel").grid(row=4, column=0, sticky="w")
        ttk.Label(control, textvariable=self.status_var, style="Trace.Status.TLabel").grid(row=4, column=1, sticky="ew")

        stats = ttk.Frame(side, style="Trace.Panel.TFrame")
        stats.grid(row=4, column=0, sticky="ew", pady=(22, 0))
        stats.columnconfigure(0, weight=1)
        self._add_metric(stats, "事件总数", self.record_count_var, 0, 0, TRACE_CYAN)
        self._add_metric(stats, "最后时间", self.last_time_var, 1, 0, TRACE_PURPLE)
        self._add_metric(stats, "最后行号", self.last_line_var, 2, 0, TRACE_ORANGE)
        self._add_metric(stats, "接收速率", self.rate_var, 3, 0, TRACE_GREEN)
        self._add_metric(stats, "时间单位", self.time_unit_var, 4, 0, TRACE_CYAN)

        table_frame = ttk.Frame(self, style="Trace.Panel.TFrame", padding=1)
        table_frame.grid(row=0, column=1, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(1, weight=1)
        ttk.Label(table_frame, text="Trace Records", style="Trace.Panel.TLabel").grid(row=0, column=0, sticky="w", padx=12, pady=(10, 8))

        columns = ("index", "time_ms", "line")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse", style="Trace.Treeview")
        headings = {
            "index": "#",
            "time_ms": "Time (ms)",
            "line": "Line",
        }
        widths = {"index": 90, "time_ms": 180, "line": 140}
        for column in columns:
            self.tree.heading(column, text=headings[column], anchor="center")
            self.tree.column(column, width=widths[column], anchor="center")
        yscroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.grid(row=1, column=0, sticky="nsew", padx=(10, 0), pady=(0, 10))
        yscroll.grid(row=1, column=1, sticky="ns", pady=(0, 10))
        self.tree.tag_configure("line_match", background="#3a3315", foreground=TRACE_TEXT)

    def _add_metric(self, parent: ttk.Frame, label: str, variable: tk.StringVar, row: int, column: int, accent: str) -> None:
        card = tk.Frame(parent, bg=TRACE_PANEL, highlightbackground=TRACE_BORDER, highlightthickness=1)
        card.grid(row=row, column=column, sticky="ew", pady=(0, 10), ipady=8)
        card.columnconfigure(1, weight=1)
        icon = tk.Canvas(card, width=42, height=42, bg=TRACE_PANEL, highlightthickness=0)
        icon.grid(row=0, column=0, rowspan=2, padx=(14, 10), pady=8)
        icon.create_oval(8, 8, 34, 34, outline=accent, width=3)
        icon.create_line(21, 14, 21, 24, fill=accent, width=3)
        icon.create_line(21, 24, 29, 24, fill=accent, width=3)
        tk.Label(card, text=label, bg=TRACE_PANEL, fg=TRACE_MUTED, font=("Segoe UI", 10)).grid(row=0, column=1, sticky="w", pady=(8, 0))
        tk.Label(card, textvariable=variable, bg=TRACE_PANEL, fg=TRACE_TEXT, font=("Segoe UI Semibold", 18)).grid(row=1, column=1, sticky="w", pady=(0, 8))

    def get_target_address(self) -> tuple[int, int]:
        target = int(self.target_addr_var.get().strip(), 0)
        dynamic = int(self.dynamic_addr_var.get().strip(), 0)
        if not 0 <= target <= 0xFF or not 0 <= dynamic <= 0xFF:
            raise ValueError("Target and dynamic addresses must be between 0 and 255.")
        return target, dynamic

    def set_running(self, running: bool) -> None:
        self._running = running
        self.status_var.set("上报中" if running else "已停止")
        self.toggle_button.configure(
            text="停止上报" if running else "开始上报",
            style="Trace.Stop.TButton" if running else "Trace.Accent.TButton",
        )

    def set_time_unit_us(self, time_unit_us: int) -> None:
        if time_unit_us <= 0:
            return
        self._time_unit_us = time_unit_us
        self.time_unit_var.set(f"{time_unit_us:,} us")

    def set_status(self, message: str, *, error: bool = False) -> None:
        self.status_var.set(message)
        self.on_status(message, error)

    def add_record(self, time_tick: int, line: int) -> None:
        record = TraceRecord(index=len(self._records) + 1, time_tick=time_tick, line=line, time_unit_us=self._time_unit_us)
        self._records.append(record)
        self.record_count_var.set(f"{len(self._records):,}")
        self.last_time_var.set(f"{record.time_ms:,.1f} ms")
        self.last_line_var.set(str(record.line))
        self.tree.insert("", "end", iid=str(record.index), values=self._record_values(record), tags=self._record_tags(record))
        self.tree.see(str(record.index))

    def _refresh_highlights(self) -> None:
        for record in self._records:
            iid = str(record.index)
            if self.tree.exists(iid):
                self.tree.item(iid, tags=self._record_tags(record))

    def _record_tags(self, record: TraceRecord) -> tuple[str, ...]:
        query = self.search_line_var.get().strip()
        if not query:
            return ()
        try:
            line = int(query, 0)
        except ValueError:
            return ()
        return ("line_match",) if record.line == line else ()

    def clear_records(self) -> None:
        self._records.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.record_count_var.set("0")
        self.last_time_var.set("-")
        self.last_line_var.set("-")
        self.rate_var.set("0/s")

    def refresh_texts(self) -> None:
        pass

    def _record_values(self, record: TraceRecord) -> tuple[str, str, str]:
        return (
            str(record.index),
            f"{record.time_ms:,.1f}",
            str(record.line),
        )
