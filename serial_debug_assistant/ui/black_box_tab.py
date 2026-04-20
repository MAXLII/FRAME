from __future__ import annotations

import csv
from datetime import datetime, timezone
import re
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk

from serial_debug_assistant.i18n import I18nManager


class BlackBoxTab(ttk.Frame):
    def __init__(self, master, *, on_query, export_dir: Path, i18n: I18nManager) -> None:
        super().__init__(master, style="Panel.TFrame", padding=12)
        self.i18n = i18n
        self._translatable_widgets: list[tuple[object, str, str]] = []
        self.on_query = on_query
        self.export_dir = export_dir

        self.start_offset_var = tk.StringVar(value="0")
        self.read_length_var = tk.StringVar(value="131072")
        self.status_var = tk.StringVar(value=self.i18n.translate_text("Waiting for a black box query"))
        self.detail_var = tk.StringVar(value=self.i18n.translate_text("Enter a flash start offset and read length, then click Push."))

        self._header_fields: list[str] = []
        self._rows: list[dict[str, int | str]] = []
        self._query_start_offset = 0
        self._query_read_length = 0

        self._build()
        self._configure_default_columns()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        query_frame = ttk.LabelFrame(self, text=self.i18n.translate_text("Black Box Query"), style="Section.TLabelframe", padding=12)
        self._remember_text(query_frame, "Black Box Query")
        query_frame.grid(row=0, column=0, sticky="ew")
        for column in range(7):
            query_frame.columnconfigure(column, weight=1 if column in {1, 3, 6} else 0)

        start_label = ttk.Label(query_frame, text=self.i18n.translate_text("Start Offset"))
        start_label.grid(row=0, column=0, sticky="w")
        self._remember_text(start_label, "Start Offset")
        ttk.Entry(query_frame, textvariable=self.start_offset_var, width=16).grid(row=0, column=1, sticky="ew", padx=(8, 16))
        length_label = ttk.Label(query_frame, text=self.i18n.translate_text("Read Length"))
        length_label.grid(row=0, column=2, sticky="w")
        self._remember_text(length_label, "Read Length")
        ttk.Entry(query_frame, textvariable=self.read_length_var, width=16).grid(row=0, column=3, sticky="ew", padx=(8, 16))
        self.push_button = ttk.Button(query_frame, text=self.i18n.translate_text("Push"), command=self.on_query, style="Accent.TButton", width=12)
        self.push_button.grid(row=0, column=4, sticky="w")
        self._remember_text(self.push_button, "Push")
        self.save_button = ttk.Button(query_frame, text=self.i18n.translate_text("Save CSV"), command=self.save_csv, width=12)
        self.save_button.grid(row=0, column=5, sticky="w", padx=(8, 0))
        self._remember_text(self.save_button, "Save CSV")
        ttk.Label(query_frame, textvariable=self.status_var, style="Header.TLabel").grid(row=0, column=6, sticky="e")
        ttk.Label(query_frame, textvariable=self.detail_var).grid(row=1, column=0, columnspan=7, sticky="w", pady=(10, 0))

        table_frame = ttk.LabelFrame(self, text=self.i18n.translate_text("Black Box Records"), style="Section.TLabelframe", padding=12)
        self._remember_text(table_frame, "Black Box Records")
        table_frame.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(table_frame, show="headings")
        self.tree.grid(row=0, column=0, sticky="nsew")
        v_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        h_scroll.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

        self._set_save_enabled(False)

    def get_query_range(self) -> tuple[int, int]:
        start_offset = int(self.start_offset_var.get().strip() or "0", 0)
        read_length = int(self.read_length_var.get().strip() or "0", 0)
        return start_offset, read_length

    def begin_query(self, *, start_offset: int, read_length: int) -> None:
        self._query_start_offset = start_offset
        self._query_read_length = read_length
        self._header_fields = []
        self._rows.clear()
        self.tree.delete(*self.tree.get_children())
        self._configure_default_columns()
        self._set_save_enabled(False)
        self.set_status(
            self.i18n.translate_text("Black box query sent"),
            self.i18n.format_text("Waiting for data from offset 0x{start:06X}, length 0x{length:X}.", start=start_offset, length=read_length),
        )

    def set_query_ack(self, *, accepted: int, start_offset: int, read_length: int) -> None:
        effective_start = start_offset if start_offset else self._query_start_offset
        effective_length = read_length if read_length else self._query_read_length
        if accepted:
            self.set_status(
                self.i18n.translate_text("Black box query accepted"),
                self.i18n.format_text("Device accepted the query: offset 0x{start:06X}, length 0x{length:X}.", start=effective_start, length=effective_length),
            )
        else:
            self.set_status(
                self.i18n.translate_text("Black box query rejected"),
                self.i18n.format_text("Device rejected the query: offset 0x{start:06X}, length 0x{length:X}.", start=effective_start, length=effective_length),
            )

    def set_header(self, header_text: str) -> None:
        parsed_fields = self._split_fields(header_text)
        if parsed_fields and parsed_fields[0].strip().lower() in {"time", "timestamp"}:
            parsed_fields = parsed_fields[1:]
        self._header_fields = parsed_fields
        self._configure_table_columns()
        self.set_status(self.i18n.translate_text("Receiving black box records"), self.i18n.translate_text("Header received. Rows are being appended to the table."))

    def add_row(self, *, row_text: str, record_offset: int = 0) -> None:
        fields = self._split_fields(row_text)
        raw_time_value = fields[0] if fields else ""
        time_value = self._format_utc_time(raw_time_value)
        value_fields = fields[1:] if fields else []

        extra_count = max(0, len(value_fields) - len(self._header_fields))
        if extra_count > 0:
            self._header_fields.extend(f"Extra {index}" for index in range(len(self._header_fields) + 1, len(self._header_fields) + extra_count + 1))
            self._configure_table_columns()

        row_number = len(self._rows) + 1
        row_values = [str(row_number), time_value]
        for index in range(len(self._header_fields)):
            row_values.append(value_fields[index] if index < len(value_fields) else "")

        self._rows.append(
            {
                "row_number": row_number,
                "record_offset": record_offset,
                "time": time_value,
                "values": list(value_fields),
            }
        )
        self.tree.insert("", "end", values=row_values)
        self._set_save_enabled(True)
        self.set_status(self.i18n.translate_text("Receiving black box records"), self.i18n.format_text("Received {count} row(s) so far.", count=len(self._rows)))

    def finish_query(self, *, start_offset: int, end_offset: int, scanned_bytes: int, row_count: int, has_more: int) -> None:
        effective_start = start_offset if start_offset else self._query_start_offset
        effective_end = end_offset if end_offset else (self._query_start_offset + self._query_read_length)
        effective_rows = row_count if row_count else len(self._rows)
        more_text = self.i18n.translate_text("More data is available after this range." if has_more else "No more data reported after this range.")
        self.set_status(
            self.i18n.translate_text("Black box query finished"),
            self.i18n.format_text(
                "Range 0x{start:06X} -> 0x{end:06X}, scanned {bytes} bytes, rows {rows}. {more}",
                start=effective_start,
                end=effective_end,
                bytes=scanned_bytes,
                rows=effective_rows,
                more=more_text,
            ),
        )

    def save_csv(self) -> None:
        if not self._rows:
            self.set_status(self.i18n.translate_text("Nothing to save"), self.i18n.translate_text("Run a black box query first."))
            return

        self.export_dir.mkdir(parents=True, exist_ok=True)
        default_name = (
            f"black_box_0x{self._query_start_offset:06X}_0x{self._query_read_length:X}.csv"
            if self._query_read_length > 0
            else "black_box.csv"
        )
        path = filedialog.asksaveasfilename(
            title=self.i18n.translate_text("Save Black Box CSV"),
            initialdir=str(self.export_dir),
            initialfile=default_name,
            defaultextension=".csv",
            filetypes=[(self.i18n.translate_text("CSV Files"), "*.csv"), (self.i18n.translate_text("All Files"), "*.*")],
        )
        if not path:
            return

        header = ["No.", "Time", *self._header_fields]
        with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            for row in self._rows:
                values = row["values"]
                csv_row = [row["row_number"], row["time"]]
                for index in range(len(self._header_fields)):
                    csv_row.append(values[index] if index < len(values) else "")
                writer.writerow(csv_row)

        self.set_status(self.i18n.translate_text("CSV saved"), self.i18n.format_text("Saved black box data to {path}", path=path))

    def set_status(self, status: str, detail: str) -> None:
        self.status_var.set(status)
        self.detail_var.set(detail)

    def _configure_default_columns(self) -> None:
        self.tree["columns"] = ("no", "time")
        self.tree.heading("no", text=self.i18n.translate_text("No."))
        self.tree.heading("time", text=self.i18n.translate_text("Time"))
        self.tree.column("no", width=90, minwidth=70, anchor="center", stretch=False)
        self.tree.column("time", width=180, minwidth=140, anchor="center", stretch=False)

    def _configure_table_columns(self) -> None:
        columns = ["no", "time", *[f"value_{index}" for index in range(len(self._header_fields))]]
        self.tree["columns"] = columns
        self.tree.heading("no", text=self.i18n.translate_text("No."))
        self.tree.heading("time", text=self.i18n.translate_text("Time"))
        self.tree.column("no", width=90, minwidth=70, anchor="center", stretch=False)
        self.tree.column("time", width=180, minwidth=140, anchor="center", stretch=False)
        for index, field_name in enumerate(self._header_fields):
            column_id = f"value_{index}"
            self.tree.heading(column_id, text=field_name)
            self.tree.column(column_id, width=150, minwidth=120, anchor="center", stretch=True)

    def _set_save_enabled(self, enabled: bool) -> None:
        self.save_button.configure(state="normal" if enabled else "disabled")

    def refresh_texts(self) -> None:
        for widget, source_text, option in self._translatable_widgets:
            widget.configure(**{option: self.i18n.translate_text(source_text)})
        self.status_var.set(self.i18n.translate_text(self.status_var.get()))
        self.detail_var.set(self.i18n.translate_text(self.detail_var.get()))
        self._configure_table_columns() if self._header_fields else self._configure_default_columns()

    def _remember_text(self, widget: object, source_text: str, option: str = "text") -> None:
        self._translatable_widgets.append((widget, source_text, option))

    def _split_fields(self, raw_text: str) -> list[str]:
        text = raw_text.strip()
        if not text:
            return []
        if "\t" in text:
            return [item.strip() for item in text.split("\t")]
        return [item.strip() for item in re.split(r"\s{2,}", text) if item.strip()]

    def _format_utc_time(self, raw_value: str) -> str:
        text = raw_value.strip()
        if not text:
            return ""
        try:
            unix_time = int(text, 0)
        except ValueError:
            return text

        if unix_time < 0:
            return text

        try:
            utc_time = datetime.fromtimestamp(unix_time, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return text

        return utc_time.strftime("%Y-%m-%d %H:%M:%S UTC")
