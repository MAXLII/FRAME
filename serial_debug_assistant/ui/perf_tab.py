from __future__ import annotations

import csv
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk

from serial_debug_assistant.i18n import I18nManager
from serial_debug_assistant.perf_protocol import (
    PERF_FILTER_ALL,
    PERF_FILTER_CODE,
    PERF_FILTER_INTERRUPT,
    PERF_FILTER_TASK,
    PERF_RECORD_CODE,
    PERF_RECORD_INTERRUPT,
    PERF_RECORD_TASK,
    PerfDictAck,
    PerfDictEnd,
    PerfInfo,
    PerfRecord,
    PerfSampleAck,
    PerfSummary,
    describe_perf_end_status,
    describe_perf_filter,
    describe_perf_record_type,
    describe_perf_reject_reason,
)

PERF_PERIODIC_INTERVAL_MS = 1000
PERF_BG = "#08161b"
PERF_PANEL = "#0d1b22"
PERF_PANEL_ALT = "#101f27"
PERF_BORDER = "#263b45"
PERF_TEXT = "#d8e2e7"
PERF_MUTED = "#8fa3ad"
PERF_CYAN = "#2ec7f0"
PERF_PURPLE = "#8b6df6"
PERF_ORANGE = "#ff9f2f"
PERF_GREEN = "#62d26f"
PERF_BLUE_SELECT = "#123552"


class PerfTab(ttk.Frame):
    def __init__(
        self,
        master,
        *,
        on_refresh_all,
        on_refresh_task,
        on_refresh_interrupt,
        on_refresh_code,
        on_reset_peak,
        on_toggle_periodic,
        on_status,
        export_dir: Path,
        i18n: I18nManager,
    ) -> None:
        super().__init__(master, style="Perf.TFrame", padding=16)
        self.i18n = i18n
        self.export_dir = export_dir
        self.on_refresh_all = on_refresh_all
        self.on_refresh_task = on_refresh_task
        self.on_refresh_interrupt = on_refresh_interrupt
        self.on_refresh_code = on_refresh_code
        self.on_reset_peak = on_reset_peak
        self.on_toggle_periodic = on_toggle_periodic
        self.on_status = on_status
        self._translatable_widgets: list[tuple[object, str, str]] = []

        self.target_addr_var = tk.StringVar(value="2")
        self.dynamic_addr_var = tk.StringVar(value="0")
        self.search_var = tk.StringVar()
        self.periodic_interval_var = tk.StringVar(value=str(PERF_PERIODIC_INTERVAL_MS))
        self.status_var = tk.StringVar(value="任务时间已就绪")
        self.info_var = tk.StringVar(value="Protocol: -, records: -, unit: - us")
        self.task_load_var = tk.StringVar(value="-")
        self.task_peak_var = tk.StringVar(value="-")
        self.interrupt_load_var = tk.StringVar(value="-")
        self.interrupt_peak_var = tk.StringVar(value="-")
        self.selection_title_var = tk.StringVar(value="未选择记录")
        self.selection_detail_var = tk.StringVar(value="选择一条任务、中断或代码片段记录查看详情。")

        self._records: dict[int, PerfRecord] = {}
        self._visible_keys: list[int] = []
        self._pull_sequence: int | None = None
        self._pull_filter: int = PERF_FILTER_ALL
        self._pull_seen_keys: set[int] = set()
        self._selected_record: PerfRecord | None = None
        self._periodic_running = False
        self._selected_filter = PERF_FILTER_ALL

        self._configure_perf_styles()
        self._build()

    def _configure_perf_styles(self) -> None:
        style = ttk.Style(self)
        style.configure("Perf.TFrame", background=PERF_BG)
        style.configure("Perf.Panel.TFrame", background=PERF_PANEL)
        style.configure("Perf.Toolbar.TFrame", background=PERF_PANEL_ALT)
        style.configure("Perf.TLabel", background=PERF_BG, foreground=PERF_TEXT, font=("Segoe UI", 10))
        style.configure("Perf.Muted.TLabel", background=PERF_BG, foreground=PERF_MUTED, font=("Segoe UI", 9))
        style.configure("Perf.Panel.TLabel", background=PERF_PANEL, foreground=PERF_TEXT, font=("Segoe UI", 10))
        style.configure("Perf.PanelMuted.TLabel", background=PERF_PANEL, foreground=PERF_MUTED, font=("Segoe UI", 9))
        style.configure("Perf.Title.TLabel", background=PERF_BG, foreground=PERF_TEXT, font=("Segoe UI Semibold", 18))
        style.configure("Perf.Header.TLabel", background=PERF_BG, foreground=PERF_TEXT, font=("Segoe UI Semibold", 11))
        style.configure("Perf.Value.TLabel", background=PERF_PANEL, foreground=PERF_TEXT, font=("Segoe UI Semibold", 19))
        style.configure("Perf.Cyan.TLabel", background=PERF_BG, foreground=PERF_CYAN, font=("Segoe UI Semibold", 10))
        style.configure("Perf.Status.TLabel", background=PERF_PANEL_ALT, foreground=PERF_CYAN, font=("Segoe UI Semibold", 10))
        style.configure("Perf.TButton", background=PERF_PANEL_ALT, foreground=PERF_TEXT, bordercolor=PERF_BORDER, padding=(12, 7))
        style.map("Perf.TButton", background=[("active", "#162a34"), ("pressed", "#1b3440")])
        style.configure("Perf.Accent.TButton", background="#123a4c", foreground=PERF_TEXT, bordercolor=PERF_CYAN, padding=(12, 7))
        style.map("Perf.Accent.TButton", background=[("active", "#174b62"), ("pressed", "#1d5c78")])
        style.configure("Perf.TEntry", fieldbackground="#0b151b", foreground=PERF_TEXT, insertcolor=PERF_TEXT, bordercolor=PERF_BORDER)
        style.configure("Perf.Treeview", background=PERF_PANEL, fieldbackground=PERF_PANEL, foreground=PERF_TEXT, bordercolor=PERF_BORDER, rowheight=34)
        style.configure("Perf.Treeview.Heading", background="#0a151b", foreground=PERF_MUTED, font=("Segoe UI Semibold", 10), bordercolor=PERF_BORDER)
        style.map(
            "Perf.Treeview",
            background=[("selected", PERF_BLUE_SELECT)],
            foreground=[("selected", PERF_TEXT)],
        )

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        toolbar = ttk.Frame(self, style="Perf.Toolbar.TFrame", padding=(16, 12))
        toolbar.grid(row=0, column=0, sticky="ew")
        for column in range(12):
            toolbar.columnconfigure(column, weight=1 if column == 5 else 0)

        ttk.Label(toolbar, text="FRAME 任务时间查看器", style="Perf.Header.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 18))
        ttk.Label(toolbar, text="Target", style="Perf.PanelMuted.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Entry(toolbar, textvariable=self.target_addr_var, width=6, style="Perf.TEntry").grid(row=0, column=2, sticky="w", padx=(6, 12))
        ttk.Label(toolbar, text="Dyn", style="Perf.PanelMuted.TLabel").grid(row=0, column=3, sticky="w")
        ttk.Entry(toolbar, textvariable=self.dynamic_addr_var, width=6, style="Perf.TEntry").grid(row=0, column=4, sticky="w", padx=(6, 16))
        search_entry = ttk.Entry(toolbar, textvariable=self.search_var, width=42, style="Perf.TEntry")
        search_entry.grid(row=0, column=5, sticky="ew", padx=(0, 16))
        self.search_var.trace_add("write", lambda *_args: self._refresh_rows())

        ttk.Button(toolbar, text="拉取全部", command=self.on_refresh_all, style="Perf.Accent.TButton", width=10).grid(row=0, column=6, sticky="ew")
        ttk.Button(toolbar, text="Task", command=self.on_refresh_task, style="Perf.TButton", width=9).grid(row=0, column=7, padx=(8, 0), sticky="ew")
        ttk.Button(toolbar, text="Interrupt", command=self.on_refresh_interrupt, style="Perf.TButton", width=11).grid(row=0, column=8, padx=(8, 0), sticky="ew")
        ttk.Button(toolbar, text="Code", command=self.on_refresh_code, style="Perf.TButton", width=9).grid(row=0, column=9, padx=(8, 0), sticky="ew")
        self.periodic_button = ttk.Button(toolbar, text="自动刷新 1s", command=self.on_toggle_periodic, style="Perf.TButton", width=12)
        self.periodic_button.grid(row=0, column=10, padx=(8, 0), sticky="ew")
        ttk.Button(toolbar, text="导出 CSV", command=self.export_csv, style="Perf.TButton", width=11).grid(row=0, column=11, padx=(8, 0), sticky="ew")

        title_row = ttk.Frame(self, style="Perf.TFrame")
        title_row.grid(row=1, column=0, sticky="ew", pady=(18, 10))
        title_row.columnconfigure(0, weight=1)
        ttk.Label(title_row, text="任务时间", style="Perf.Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(title_row, text="Reset Peak", command=self.on_reset_peak, style="Perf.TButton", width=11).grid(row=0, column=1, sticky="e", padx=(0, 12))
        ttk.Label(title_row, textvariable=self.info_var, style="Perf.Muted.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

        summary = ttk.Frame(self, style="Perf.TFrame")
        summary.grid(row=2, column=0, sticky="ew")
        for column in range(4):
            summary.columnconfigure(column, weight=1)
        self._add_metric(summary, "任务总占用", self.task_load_var, 0, 0, PERF_CYAN)
        self._add_metric(summary, "任务峰值", self.task_peak_var, 0, 1, PERF_PURPLE)
        self._add_metric(summary, "中断总占用", self.interrupt_load_var, 0, 2, PERF_ORANGE)
        self._add_metric(summary, "中断峰值", self.interrupt_peak_var, 0, 3, "#ffbf3d")

        content = ttk.Frame(self, style="Perf.TFrame")
        content.grid(row=3, column=0, sticky="nsew", pady=(18, 0))
        content.columnconfigure(0, weight=3)
        content.columnconfigure(1, weight=2)
        content.rowconfigure(0, weight=1)

        table_frame = ttk.Frame(content, style="Perf.Panel.TFrame", padding=1)
        table_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(1, weight=1)
        ttk.Label(table_frame, text="Records", style="Perf.Panel.TLabel").grid(row=0, column=0, sticky="w", padx=12, pady=(10, 8))

        columns = ("type", "name", "time", "max", "load", "peak")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse", style="Perf.Treeview")
        headings = {
            "type": "Type",
            "name": "Name",
            "time": "Run Time (us)",
            "max": "Max Time (us)",
            "load": "Load",
            "peak": "Peak",
        }
        widths = {"type": 90, "name": 220, "time": 120, "max": 120, "load": 110, "peak": 110}
        for column in columns:
            self.tree.heading(column, text=headings[column], anchor="center")
            self.tree.column(column, width=widths[column], anchor="center")
        yscroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.grid(row=1, column=0, sticky="nsew", padx=(10, 0), pady=(0, 10))
        yscroll.grid(row=1, column=1, sticky="ns", pady=(0, 10))
        self.tree.bind("<<TreeviewSelect>>", self._on_select_record)
        self.tree.tag_configure("task", foreground=PERF_CYAN)
        self.tree.tag_configure("interrupt", foreground=PERF_ORANGE)
        self.tree.tag_configure("code", foreground=PERF_GREEN)

        detail = ttk.Frame(content, style="Perf.Panel.TFrame", padding=14)
        detail.grid(row=0, column=1, sticky="nsew")
        detail.columnconfigure(0, weight=1)
        detail.rowconfigure(3, weight=1)
        ttk.Label(detail, text="选中项详情", style="Perf.PanelMuted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(detail, textvariable=self.selection_title_var, style="Perf.Cyan.TLabel").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Label(detail, textvariable=self.selection_detail_var, style="Perf.Panel.TLabel", wraplength=420).grid(row=2, column=0, sticky="ew", pady=(8, 12))
        self.usage_canvas = tk.Canvas(detail, height=250, bg=PERF_PANEL, highlightthickness=0)
        self.usage_canvas.grid(row=3, column=0, sticky="ew")
        self.usage_canvas.bind("<Configure>", lambda _event: self._draw_selected_record())

    def _add_metric(self, parent: ttk.Frame, label: str, variable: tk.StringVar, row: int, column: int, accent: str) -> None:
        card = tk.Frame(parent, bg=PERF_PANEL, highlightbackground=PERF_BORDER, highlightthickness=1)
        card.grid(row=row, column=column, sticky="ew", padx=(0 if column == 0 else 12, 0), ipady=12)
        card.columnconfigure(1, weight=1)
        icon = tk.Canvas(card, width=48, height=48, bg=PERF_PANEL, highlightthickness=0)
        icon.grid(row=0, column=0, rowspan=2, padx=(18, 12), pady=8)
        icon.create_oval(8, 8, 40, 40, outline=accent, width=3)
        icon.create_line(24, 15, 24, 26, fill=accent, width=3)
        icon.create_line(24, 26, 33, 26, fill=accent, width=3)
        tk.Label(card, text=label, bg=PERF_PANEL, fg=PERF_MUTED, font=("Segoe UI", 10)).grid(row=0, column=1, sticky="w", pady=(10, 0))
        tk.Label(card, textvariable=variable, bg=PERF_PANEL, fg=PERF_TEXT, font=("Segoe UI Semibold", 20)).grid(row=1, column=1, sticky="w", pady=(0, 8))

    def get_target_address(self) -> tuple[int, int]:
        target = int(self.target_addr_var.get().strip(), 0)
        dynamic = int(self.dynamic_addr_var.get().strip(), 0)
        if not 0 <= target <= 0xFF or not 0 <= dynamic <= 0xFF:
            raise ValueError("Target and dynamic addresses must be between 0 and 255.")
        return target, dynamic

    def get_periodic_interval_ms(self) -> int:
        return PERF_PERIODIC_INTERVAL_MS

    def select_filter(self, type_filter: int) -> None:
        self._selected_filter = type_filter
        self._refresh_rows()

    def selected_filter(self) -> int:
        return self._selected_filter

    def set_periodic_running(self, running: bool) -> None:
        self._periodic_running = running
        self.periodic_button.configure(text="停止刷新" if running else "自动刷新 1s")

    def set_status(self, message: str, *, error: bool = False) -> None:
        self.status_var.set(message)
        self.on_status(message, error)

    def set_info(self, info: PerfInfo) -> None:
        self.info_var.set(
            f"Protocol: {info.protocol_version}, records: {info.record_count}, "
            f"unit: {info.unit_us:.3f} us, cnt/tick: {info.cnt_per_sys_tick}, window: {info.cpu_window_ms} ms"
        )
        self.set_status("任务时间信息已更新。")

    def set_summary(self, summary: PerfSummary) -> None:
        self.task_load_var.set(self._format_percent(summary.task_load_percent))
        self.task_peak_var.set(self._format_percent(summary.task_peak_percent))
        self.interrupt_load_var.set(self._format_percent(summary.interrupt_load_percent))
        self.interrupt_peak_var.set(self._format_percent(summary.interrupt_peak_percent))
        self.set_status("总占用率已更新。")

    def start_pull(self, ack: PerfSampleAck) -> None:
        self._pull_sequence = ack.sequence
        self._pull_filter = ack.type_filter
        self._pull_seen_keys = set()
        self.set_status(f"正在刷新{describe_perf_filter(ack.type_filter)}记录，共 {ack.record_count} 条。")

    def set_pull_rejected(self, ack: PerfDictAck | PerfSampleAck) -> None:
        self._pull_sequence = None
        self._pull_seen_keys = set()
        self.set_status(f"刷新失败：{describe_perf_reject_reason(ack.reject_reason)}。", error=True)

    def add_record(self, record: PerfRecord) -> None:
        key = self._record_key(record)
        self._pull_seen_keys.add(key)
        self._records[key] = record
        self._upsert_record_row(record)
        self.set_status(f"已更新 {len(self._pull_seen_keys)}/{record.record_count} 条记录。")

    def finish_pull(self, end: PerfDictEnd) -> None:
        self._remove_records_missing_from_pull()
        self._pull_sequence = None
        self._pull_seen_keys = set()
        self.set_status(f"刷新完成：{describe_perf_end_status(end.status)}，{end.record_count} 条记录。")

    def set_reset_result(self, success: bool) -> None:
        self.set_status("峰值已重置。" if success else "峰值重置失败。", error=not success)

    def export_csv(self) -> None:
        if not self._records:
            self.set_status("No perf records to export.", error=True)
            return
        self.export_dir.mkdir(parents=True, exist_ok=True)
        path = filedialog.asksaveasfilename(
            initialdir=str(self.export_dir),
            initialfile="perf_records.csv",
            defaultextension=".csv",
            filetypes=(("CSV Files", "*.csv"), ("All Files", "*.*")),
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["record_id", "type", "name", "time_us", "max_time_us", "period_us", "load_percent", "peak_percent"])
            for record in sorted(self._records.values(), key=lambda item: (item.record_type, item.index, item.name.lower())):
                writer.writerow(
                    [
                        record.record_id,
                        describe_perf_record_type(record.record_type),
                        record.name,
                        record.time_us,
                        record.max_time_us,
                        record.period_us if record.record_type == PERF_RECORD_TASK else "",
                        "" if record.record_type == PERF_RECORD_CODE else f"{record.load_percent:.6g}",
                        "" if record.record_type == PERF_RECORD_CODE else f"{record.peak_percent:.6g}",
                    ]
                )
        self.set_status(f"Exported perf records to {path}.")

    def refresh_texts(self) -> None:
        pass

    def _refresh_rows(self) -> None:
        query = self.search_var.get().strip().lower()
        selected_key = self._record_key(self._selected_record) if self._selected_record is not None else None
        for item in self.tree.get_children():
            self.tree.delete(item)
        records = sorted(self._records.values(), key=lambda item: (item.record_type, item.index, item.name.lower()))
        self._visible_keys = []
        for record in records:
            if not self._record_matches_active_filter(record):
                continue
            if query and query not in record.name.lower() and query not in describe_perf_record_type(record.record_type).lower():
                continue
            key = self._record_key(record)
            iid = self._record_iid(key)
            self._visible_keys.append(key)
            self.tree.insert(
                "",
                "end",
                iid=iid,
                values=self._record_values(record),
                tags=(self._record_tag(record),),
            )
            if key == selected_key:
                self.tree.selection_set(iid)
        if selected_key is None and self._visible_keys:
            first_iid = self._record_iid(self._visible_keys[0])
            self.tree.selection_set(first_iid)
        self._on_select_record()

    def _upsert_record_row(self, record: PerfRecord) -> None:
        query = self.search_var.get().strip().lower()
        key = self._record_key(record)
        iid = self._record_iid(key)
        visible = self._record_matches_active_filter(record) and (
            not query or query in record.name.lower() or query in describe_perf_record_type(record.record_type).lower()
        )
        if not visible:
            if self.tree.exists(iid):
                self.tree.delete(iid)
            if key in self._visible_keys:
                self._visible_keys.remove(key)
            return

        if self.tree.exists(iid):
            self.tree.item(iid, values=self._record_values(record))
        else:
            self.tree.insert("", "end", iid=iid, values=self._record_values(record), tags=(self._record_tag(record),))
            self._visible_keys.append(key)

        if self._selected_record is None and not self.tree.selection():
            self.tree.selection_set(iid)
            self._on_select_record()
        elif self._selected_record is not None and self._record_key(self._selected_record) == key:
            self._selected_record = record
            self.tree.selection_set(iid)
            self._on_select_record()

    def _remove_records_missing_from_pull(self) -> None:
        if self._pull_sequence is None:
            return
        stale_keys = [
            key
            for key in self._records
            if self._key_matches_filter(key, self._pull_filter) and key not in self._pull_seen_keys
        ]
        if not stale_keys:
            return
        selected_key = self._record_key(self._selected_record) if self._selected_record is not None else None
        for key in stale_keys:
            self._records.pop(key, None)
            iid = self._record_iid(key)
            if self.tree.exists(iid):
                self.tree.delete(iid)
            if key in self._visible_keys:
                self._visible_keys.remove(key)
        if selected_key in stale_keys:
            self._selected_record = None
            if self._visible_keys:
                self.tree.selection_set(self._record_iid(self._visible_keys[0]))
            else:
                self.tree.selection_remove(self.tree.selection())
            self._on_select_record()

    def _key_matches_filter(self, key: int, type_filter: int) -> bool:
        if type_filter == PERF_FILTER_ALL:
            return True
        record = self._records.get(key)
        return record is not None and record.record_type == type_filter

    def _record_matches_active_filter(self, record: PerfRecord) -> bool:
        return self._key_matches_filter(self._record_key(record), self._selected_filter)

    def _record_values(self, record: PerfRecord) -> tuple[str, str, str, str, str, str]:
        return (
            describe_perf_record_type(record.record_type),
            record.name,
            f"{record.time_us:,}",
            f"{record.max_time_us:,}",
            "-" if record.record_type == PERF_RECORD_CODE else self._format_percent(record.load_percent),
            "-" if record.record_type == PERF_RECORD_CODE else self._format_percent(record.peak_percent),
        )

    def _record_tag(self, record: PerfRecord) -> str:
        if record.record_type == PERF_RECORD_TASK:
            return "task"
        if record.record_type == PERF_RECORD_INTERRUPT:
            return "interrupt"
        if record.record_type == PERF_RECORD_CODE:
            return "code"
        return ""

    def _on_select_record(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            self._selected_record = None
            self.selection_title_var.set("未选择记录")
            self.selection_detail_var.set("选择一条任务、中断或代码片段记录查看详情。")
            self._draw_selected_record()
            return
        raw = selection[0]
        record = self._records.get(int(raw))
        self._selected_record = record
        if record is None:
            return
        if record.record_type == PERF_RECORD_CODE:
            self.selection_title_var.set(f"Code: {record.name}")
            self.selection_detail_var.set(f"Run time {record.time_us:,} us, max time {record.max_time_us:,} us.")
        else:
            self.selection_title_var.set(f"{describe_perf_record_type(record.record_type)}: {record.name}")
            period_text = ""
            if record.record_type == PERF_RECORD_TASK and record.period_us > 0:
                period_text = f", period {record.period_us:,} us"
            self.selection_detail_var.set(
                f"Current load {self._format_percent(record.load_percent)}, peak {self._format_percent(record.peak_percent)}, "
                f"run time {record.time_us:,} us, max time {record.max_time_us:,} us{period_text}."
            )
        self._draw_selected_record()

    def _draw_selected_record(self) -> None:
        canvas = self.usage_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 320)
        x0 = 16
        x1 = width - 16
        y = 52
        height = 28
        record = self._selected_record
        canvas.create_text(x0, 20, text="占用率对比", anchor="w", fill=PERF_TEXT, font=("Segoe UI", 10, "bold"))
        canvas.create_rectangle(x0, y, x1, y + height, fill="#263138", outline=PERF_BORDER)
        if record is None:
            return
        if record.record_type == PERF_RECORD_CODE:
            canvas.create_text(x0, y + 50, text="Code records do not carry load percent.", anchor="w", fill=PERF_MUTED)
            canvas.create_text(x0, y + 74, text=f"Run {record.time_us:,} us / max {record.max_time_us:,} us", anchor="w", fill=PERF_TEXT)
            return
        accent = PERF_CYAN if record.record_type == PERF_RECORD_TASK else PERF_ORANGE
        peak_width = self._bar_width(x1 - x0, record.peak_percent)
        load_width = self._bar_width(x1 - x0, record.load_percent)
        canvas.create_rectangle(x0, y, x0 + peak_width, y + height, fill=PERF_PURPLE, outline="")
        canvas.create_rectangle(x0, y + 7, x0 + load_width, y + height - 7, fill=accent, outline="")
        canvas.create_text(x0, y + 48, text="灰色 = 100% 基准，紫色 = 峰值，亮色 = 当前", anchor="w", fill=PERF_MUTED)
        canvas.create_text(
            x0,
            y + 72,
            text=f"Current {self._format_percent(record.load_percent)} / Peak {self._format_percent(record.peak_percent)}",
            anchor="w",
            fill=PERF_TEXT,
        )

    def _bar_width(self, width: int, percent: float) -> int:
        percent = max(0.0, min(100.0, percent))
        return int(width * percent / 100.0)

    def _record_key(self, record: PerfRecord) -> int:
        return record.record_id

    def _record_iid(self, key: int) -> str:
        return str(key)

    def _format_percent(self, value: float) -> str:
        return f"{value:.2f}%"
