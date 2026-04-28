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
    PerfInfo,
    PerfListAck,
    PerfListEnd,
    PerfRecord,
    PerfSummary,
    describe_perf_end_status,
    describe_perf_filter,
    describe_perf_record_type,
    describe_perf_reject_reason,
)

PERF_PERIODIC_INTERVAL_MS = 1000


class PerfTab(ttk.Frame):
    def __init__(
        self,
        master,
        *,
        on_refresh_all,
        on_refresh_task,
        on_refresh_interrupt,
        on_refresh_code,
        on_refresh_summary,
        on_reset_peak,
        on_toggle_periodic,
        export_dir: Path,
        i18n: I18nManager,
    ) -> None:
        super().__init__(master, style="Panel.TFrame", padding=12)
        self.i18n = i18n
        self.export_dir = export_dir
        self.on_refresh_all = on_refresh_all
        self.on_refresh_task = on_refresh_task
        self.on_refresh_interrupt = on_refresh_interrupt
        self.on_refresh_code = on_refresh_code
        self.on_refresh_summary = on_refresh_summary
        self.on_reset_peak = on_reset_peak
        self.on_toggle_periodic = on_toggle_periodic
        self._translatable_widgets: list[tuple[object, str, str]] = []

        self.target_addr_var = tk.StringVar(value="2")
        self.dynamic_addr_var = tk.StringVar(value="0")
        self.search_var = tk.StringVar()
        self.periodic_interval_var = tk.StringVar(value=str(PERF_PERIODIC_INTERVAL_MS))
        self.status_var = tk.StringVar(value="Ready to pull perf records.")
        self.info_var = tk.StringVar(value="Protocol: -, records: -, unit: - us")
        self.task_load_var = tk.StringVar(value="-")
        self.task_peak_var = tk.StringVar(value="-")
        self.interrupt_load_var = tk.StringVar(value="-")
        self.interrupt_peak_var = tk.StringVar(value="-")
        self.selection_title_var = tk.StringVar(value="No record selected")
        self.selection_detail_var = tk.StringVar(value="Select a task, interrupt, or code record to inspect timing.")

        self._records: dict[tuple[int, int, str], PerfRecord] = {}
        self._visible_keys: list[tuple[int, int, str]] = []
        self._pull_sequence: int | None = None
        self._pull_filter: int = PERF_FILTER_ALL
        self._pull_seen_keys: set[tuple[int, int, str]] = set()
        self._selected_record: PerfRecord | None = None
        self._periodic_running = False
        self._selected_filter = PERF_FILTER_ALL

        self._build()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        toolbar = ttk.LabelFrame(self, text="Perf Target", style="Section.TLabelframe", padding=12)
        toolbar.grid(row=0, column=0, sticky="ew")
        for column in range(10):
            toolbar.columnconfigure(column, weight=1 if column in {1, 3, 5} else 0)

        ttk.Label(toolbar, text="Target Address").grid(row=0, column=0, sticky="w")
        ttk.Entry(toolbar, textvariable=self.target_addr_var, width=8).grid(row=0, column=1, sticky="ew", padx=(8, 14))
        ttk.Label(toolbar, text="Dynamic Address").grid(row=0, column=2, sticky="w")
        ttk.Entry(toolbar, textvariable=self.dynamic_addr_var, width=8).grid(row=0, column=3, sticky="ew", padx=(8, 14))
        ttk.Label(toolbar, text="Search").grid(row=0, column=4, sticky="w")
        search_entry = ttk.Entry(toolbar, textvariable=self.search_var, width=28)
        search_entry.grid(row=0, column=5, sticky="ew", padx=(8, 14))
        self.search_var.trace_add("write", lambda *_args: self._refresh_rows())

        ttk.Button(toolbar, text="All", command=self.on_refresh_all, style="Accent.TButton", width=10).grid(row=0, column=6, sticky="ew")
        ttk.Button(toolbar, text="Task", command=self.on_refresh_task, width=10).grid(row=0, column=7, padx=(8, 0), sticky="ew")
        ttk.Button(toolbar, text="Interrupt", command=self.on_refresh_interrupt, width=12).grid(row=0, column=8, padx=(8, 0), sticky="ew")
        ttk.Button(toolbar, text="Code", command=self.on_refresh_code, width=10).grid(row=0, column=9, padx=(8, 0), sticky="ew")

        actions = ttk.Frame(toolbar, style="Panel.TFrame")
        actions.grid(row=1, column=0, columnspan=10, sticky="ew", pady=(12, 0))
        ttk.Button(actions, text="Summary", command=self.on_refresh_summary, width=12).grid(row=0, column=0)
        ttk.Button(actions, text="Reset Peak", command=self.on_reset_peak, width=12).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(actions, text="Export CSV", command=self.export_csv, width=12).grid(row=0, column=2, padx=(8, 0))
        ttk.Label(actions, text="Interval").grid(row=0, column=3, sticky="w", padx=(14, 6))
        ttk.Entry(actions, textvariable=self.periodic_interval_var, width=8, state="readonly").grid(row=0, column=4, sticky="w")
        ttk.Label(actions, text="ms").grid(row=0, column=5, sticky="w", padx=(4, 0))
        self.periodic_button = ttk.Button(actions, text="Periodic Query", command=self.on_toggle_periodic, width=14)
        self.periodic_button.grid(row=0, column=6, padx=(8, 0))
        ttk.Label(actions, textvariable=self.status_var, style="Header.TLabel").grid(row=0, column=7, sticky="w", padx=(18, 0))
        actions.columnconfigure(7, weight=1)

        summary = ttk.LabelFrame(self, text="CPU Load", style="Section.TLabelframe", padding=12)
        summary.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        for column in range(8):
            summary.columnconfigure(column, weight=1)
        self._add_metric(summary, "Task Current", self.task_load_var, 0, 0)
        self._add_metric(summary, "Task Peak", self.task_peak_var, 0, 2)
        self._add_metric(summary, "Interrupt Current", self.interrupt_load_var, 0, 4)
        self._add_metric(summary, "Interrupt Peak", self.interrupt_peak_var, 0, 6)
        ttk.Label(summary, textvariable=self.info_var).grid(row=1, column=0, columnspan=8, sticky="w", pady=(8, 0))

        content = ttk.Frame(self, style="Panel.TFrame")
        content.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        content.columnconfigure(0, weight=3)
        content.columnconfigure(1, weight=2)
        content.rowconfigure(0, weight=1)

        table_frame = ttk.LabelFrame(content, text="Records", style="Section.TLabelframe", padding=10)
        table_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        columns = ("type", "name", "time", "max", "load", "peak")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
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
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self._on_select_record)

        detail = ttk.LabelFrame(content, text="Selected Record", style="Section.TLabelframe", padding=12)
        detail.grid(row=0, column=1, sticky="nsew")
        detail.columnconfigure(0, weight=1)
        detail.rowconfigure(3, weight=1)
        ttk.Label(detail, textvariable=self.selection_title_var, style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(detail, textvariable=self.selection_detail_var, wraplength=420).grid(row=1, column=0, sticky="ew", pady=(8, 12))
        self.usage_canvas = tk.Canvas(detail, height=150, bg="#fbfdff", highlightthickness=0)
        self.usage_canvas.grid(row=2, column=0, sticky="ew")
        self.usage_canvas.bind("<Configure>", lambda _event: self._draw_selected_record())

    def _add_metric(self, parent: ttk.Frame, label: str, variable: tk.StringVar, row: int, column: int) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w", padx=(0, 8))
        ttk.Label(parent, textvariable=variable, style="Header.TLabel").grid(row=row, column=column + 1, sticky="w")

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
        self.periodic_button.configure(text="Stop Periodic" if running else "Periodic Query")

    def set_status(self, message: str, *, error: bool = False) -> None:
        self.status_var.set(message)

    def set_info(self, info: PerfInfo) -> None:
        self.info_var.set(
            f"Protocol: {info.protocol_version}, records: {info.record_count}, "
            f"unit: {info.unit_us:.3f} us, cnt/tick: {info.cnt_per_sys_tick}, window: {info.cpu_window_ms} ms"
        )
        self.set_status("Perf info updated.")

    def set_summary(self, summary: PerfSummary) -> None:
        self.task_load_var.set(self._format_percent(summary.task_load_percent))
        self.task_peak_var.set(self._format_percent(summary.task_peak_percent))
        self.interrupt_load_var.set(self._format_percent(summary.interrupt_load_percent))
        self.interrupt_peak_var.set(self._format_percent(summary.interrupt_peak_percent))
        self.set_status("Perf summary updated.")

    def start_pull(self, ack: PerfListAck) -> None:
        self._pull_sequence = ack.sequence
        self._pull_filter = ack.type_filter
        self._pull_seen_keys = set()
        self.set_status(
            f"Pulling {describe_perf_filter(ack.type_filter).lower()} records "
            f"({ack.record_count}, seq {ack.sequence})."
        )

    def set_pull_rejected(self, ack: PerfListAck) -> None:
        self._pull_sequence = None
        self._pull_seen_keys = set()
        self.set_status(f"Pull rejected: {describe_perf_reject_reason(ack.reject_reason)}.", error=True)

    def add_record(self, record: PerfRecord) -> None:
        key = self._record_key(record)
        self._pull_seen_keys.add(key)
        self._records[key] = record
        self._upsert_record_row(record)
        self.set_status(f"Received {len(self._records)}/{record.record_count} records.")

    def finish_pull(self, end: PerfListEnd) -> None:
        self._remove_records_missing_from_pull()
        self._pull_sequence = None
        self._pull_seen_keys = set()
        self.set_status(f"Pull finished: {describe_perf_end_status(end.status)}, {end.record_count} records.")

    def set_reset_result(self, success: bool) -> None:
        self.set_status("Peak values reset." if success else "Peak reset failed.", error=not success)

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
            writer.writerow(["type", "name", "time_us", "max_time_us", "load_percent", "peak_percent"])
            for record in sorted(self._records.values(), key=lambda item: (item.record_type, item.index, item.name.lower())):
                writer.writerow(
                    [
                        describe_perf_record_type(record.record_type),
                        record.name,
                        record.time_us,
                        record.max_time_us,
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
            self.tree.insert("", "end", iid=iid, values=self._record_values(record))
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

    def _key_matches_filter(self, key: tuple[int, int, str], type_filter: int) -> bool:
        if type_filter == PERF_FILTER_ALL:
            return True
        return key[0] == type_filter

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

    def _on_select_record(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            self._selected_record = None
            self.selection_title_var.set("No record selected")
            self.selection_detail_var.set("Select a task, interrupt, or code record to inspect timing.")
            self._draw_selected_record()
            return
        raw = selection[0]
        type_text, index_text, name = raw.split(":", 2)
        record = self._records.get((int(type_text), int(index_text), name))
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
        canvas.create_text(x0, 20, text="Occupancy", anchor="w", fill="#36506b", font=("Segoe UI", 10, "bold"))
        canvas.create_rectangle(x0, y, x1, y + height, fill="#e5ecf5", outline="#bfd0e3")
        if record is None:
            return
        if record.record_type == PERF_RECORD_CODE:
            canvas.create_text(x0, y + 50, text="Code records do not carry load percent.", anchor="w", fill="#5b6b7f")
            canvas.create_text(x0, y + 74, text=f"Run {record.time_us:,} us / max {record.max_time_us:,} us", anchor="w", fill="#112033")
            return
        peak_width = self._bar_width(x1 - x0, record.peak_percent)
        load_width = self._bar_width(x1 - x0, record.load_percent)
        canvas.create_rectangle(x0, y, x0 + peak_width, y + height, fill="#93c5fd", outline="")
        canvas.create_rectangle(x0, y + 7, x0 + load_width, y + height - 7, fill="#2563eb", outline="")
        canvas.create_text(x0, y + 48, text="Background = 100%, light = peak, blue = current", anchor="w", fill="#5b6b7f")
        canvas.create_text(
            x0,
            y + 72,
            text=f"Current {self._format_percent(record.load_percent)} / Peak {self._format_percent(record.peak_percent)}",
            anchor="w",
            fill="#112033",
        )

    def _bar_width(self, width: int, percent: float) -> int:
        percent = max(0.0, min(100.0, percent))
        return int(width * percent / 100.0)

    def _record_key(self, record: PerfRecord) -> tuple[int, int, str]:
        return (record.record_type, record.index, record.name)

    def _record_iid(self, key: tuple[int, int, str]) -> str:
        return f"{key[0]}:{key[1]}:{key[2]}"

    def _format_percent(self, value: float) -> str:
        return f"{value:.2f}%"
