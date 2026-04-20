from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import ttk

from serial_debug_assistant.firmware_update import UPDATE_TYPE_FORCE, UPDATE_TYPE_NORMAL
from serial_debug_assistant.i18n import I18nManager
from serial_debug_assistant.models import FirmwareImage


class UpgradeTab(ttk.Frame):
    def __init__(self, master, *, on_browse, on_start_stop, on_read_version, i18n: I18nManager) -> None:
        super().__init__(master, style="Panel.TFrame", padding=12)
        self.i18n = i18n
        self._translatable_widgets: list[tuple[object, str, str]] = []
        self._running = False
        self.on_browse = on_browse
        self.on_start_stop = on_start_stop
        self.on_read_version = on_read_version

        self.file_path_var = tk.StringVar(value=self.i18n.translate_text("No firmware loaded"))
        self.version_var = tk.StringVar(value="-")
        self.device_version_var = tk.StringVar(value="-")
        self.compile_time_var = tk.StringVar(value="-")
        self.file_size_var = tk.StringVar(value="-")
        self.commit_var = tk.StringVar(value="-")
        self.module_var = tk.StringVar(value="-")
        self.footer_crc_var = tk.StringVar(value="-")
        self.download_addr_var = tk.StringVar(value="2")
        self.download_dyn_addr_var = tk.StringVar(value="0")
        self.update_type_var = tk.StringVar(value="Normal")
        self.status_var = tk.StringVar(value=self.i18n.translate_text("Waiting for firmware"))
        self.detail_var = tk.StringVar(value=self.i18n.translate_text("Flow: 0x08 -> 0x09 -> 0x0A -> 0x0B, firmware packet size: 1024 bytes"))
        self.error_var = tk.StringVar(value="-")
        self.progress_text_var = tk.StringVar(value="0 / 0 bytes")
        self.progress_percent_var = tk.StringVar(value="0%")
        self.connection_var = tk.StringVar(value=self.i18n.translate_text("Serial port disconnected"))
        self.forward_status_var = tk.StringVar(value=self.i18n.translate_text("LLC -> PFC forward progress is idle"))
        self.forward_detail_var = tk.StringVar(value=self.i18n.translate_text("Waiting for the main upgrade flow to start"))
        self.forward_text_var = tk.StringVar(value="0 / 0 bytes")
        self.forward_percent_var = tk.StringVar(value="0%")

        self._build()

    def _build(self) -> None:
        self.columnconfigure(0, weight=5)
        self.columnconfigure(1, weight=4)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self, style="Panel.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        left.columnconfigure(1, weight=1)
        left.rowconfigure(3, weight=0)

        right = ttk.Frame(self, style="Panel.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        file_frame = ttk.LabelFrame(left, text=self.i18n.translate_text("Firmware"), style="Section.TLabelframe", padding=12)
        self._remember_text(file_frame, "Firmware")
        file_frame.grid(row=0, column=0, columnspan=2, sticky="ew")
        file_frame.columnconfigure(0, weight=1)
        ttk.Entry(file_frame, textvariable=self.file_path_var, state="readonly").grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.load_button = ttk.Button(file_frame, text=self.i18n.translate_text("Load Firmware"), command=self.on_browse, style="Accent.TButton", width=12)
        self.load_button.grid(row=0, column=1)
        self._remember_text(self.load_button, "Load Firmware")

        control_frame = ttk.LabelFrame(left, text=self.i18n.translate_text("Upgrade Control"), style="Section.TLabelframe", padding=12)
        self._remember_text(control_frame, "Upgrade Control")
        control_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        for index in range(4):
            control_frame.columnconfigure(index, weight=1 if index % 2 == 1 else 0)
        target_label = ttk.Label(control_frame, text=self.i18n.translate_text("Target Address"))
        target_label.grid(row=0, column=0, sticky="w")
        self._remember_text(target_label, "Target Address")
        ttk.Entry(control_frame, textvariable=self.download_addr_var, width=10).grid(row=0, column=1, sticky="ew", padx=(8, 16))
        dynamic_label = ttk.Label(control_frame, text=self.i18n.translate_text("Dynamic Address"))
        dynamic_label.grid(row=0, column=2, sticky="w")
        self._remember_text(dynamic_label, "Dynamic Address")
        ttk.Entry(control_frame, textvariable=self.download_dyn_addr_var, width=10).grid(row=0, column=3, sticky="ew", padx=(8, 0))
        type_label = ttk.Label(control_frame, text=self.i18n.translate_text("Upgrade Type"))
        type_label.grid(row=1, column=0, sticky="w", pady=(10, 0))
        self._remember_text(type_label, "Upgrade Type")
        ttk.Combobox(
            control_frame,
            textvariable=self.update_type_var,
            state="readonly",
            values=("Normal", "Force"),
        ).grid(row=1, column=1, sticky="ew", padx=(8, 16), pady=(10, 0))
        ttk.Label(control_frame, textvariable=self.connection_var, style="Status.TLabel").grid(row=1, column=2, columnspan=2, sticky="e", pady=(10, 0))
        self.read_version_button = ttk.Button(control_frame, text=self.i18n.translate_text("Read Device Version"), command=self.on_read_version)
        self.read_version_button.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0), padx=(0, 8))
        self._remember_text(self.read_version_button, "Read Device Version")
        self.start_button = ttk.Button(control_frame, text=self.i18n.translate_text("Start Upgrade"), command=self.on_start_stop, style="Accent.TButton")
        self.start_button.grid(row=2, column=2, columnspan=2, sticky="ew", pady=(12, 0))

        info_frame = ttk.LabelFrame(left, text=self.i18n.translate_text("Firmware Info"), style="Section.TLabelframe", padding=12)
        self._remember_text(info_frame, "Firmware Info")
        info_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(12, 0))
        info_frame.columnconfigure(1, weight=1)
        rows = [
            ("File Version", self.version_var),
            ("Device Version", self.device_version_var),
            ("Build Time", self.compile_time_var),
            ("File Size", self.file_size_var),
            ("Commit ID", self.commit_var),
            ("Module", self.module_var),
            ("Footer CRC", self.footer_crc_var),
        ]
        for row, (label, variable) in enumerate(rows):
            info_label = ttk.Label(info_frame, text=self.i18n.translate_text(label))
            info_label.grid(row=row, column=0, sticky="w", pady=4)
            self._remember_text(info_label, label)
            ttk.Label(info_frame, textvariable=variable).grid(row=row, column=1, sticky="w", pady=4, padx=(10, 0))

        status_frame = ttk.LabelFrame(left, text=self.i18n.translate_text("Download Status"), style="Section.TLabelframe", padding=12)
        self._remember_text(status_frame, "Download Status")
        status_frame.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(12, 0))
        status_frame.columnconfigure(0, weight=1)
        status_frame.grid_propagate(False)
        status_frame.configure(height=170)
        ttk.Label(status_frame, textvariable=self.status_var, style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(status_frame, textvariable=self.detail_var).grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(status_frame, textvariable=self.error_var).grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.progress = ttk.Progressbar(status_frame, mode="determinate", maximum=100)
        self.progress.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        progress_meta = ttk.Frame(status_frame, style="Panel.TFrame")
        progress_meta.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        progress_meta.columnconfigure(0, weight=1)
        ttk.Label(progress_meta, textvariable=self.progress_text_var).grid(row=0, column=0, sticky="w")
        ttk.Label(progress_meta, textvariable=self.progress_percent_var).grid(row=0, column=1, sticky="e")

        forward_frame = ttk.LabelFrame(left, text=self.i18n.translate_text("LLC -> PFC Forward Progress"), style="Section.TLabelframe", padding=12)
        self._remember_text(forward_frame, "LLC -> PFC Forward Progress")
        forward_frame.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        forward_frame.columnconfigure(0, weight=1)
        forward_frame.grid_propagate(False)
        forward_frame.configure(height=150)
        ttk.Label(forward_frame, textvariable=self.forward_status_var, style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(forward_frame, textvariable=self.forward_detail_var).grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.forward_progress = ttk.Progressbar(forward_frame, mode="determinate", maximum=100)
        self.forward_progress.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        forward_meta = ttk.Frame(forward_frame, style="Panel.TFrame")
        forward_meta.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        forward_meta.columnconfigure(0, weight=1)
        ttk.Label(forward_meta, textvariable=self.forward_text_var).grid(row=0, column=0, sticky="w")
        ttk.Label(forward_meta, textvariable=self.forward_percent_var).grid(row=0, column=1, sticky="e")

        log_frame = ttk.LabelFrame(right, text=self.i18n.translate_text("Upgrade Log"), style="Section.TLabelframe", padding=12)
        self._remember_text(log_frame, "Upgrade Log")
        log_frame.grid(row=0, column=0, sticky="nsew")
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.log_text = tk.Text(
            log_frame,
            height=24,
            wrap="word",
            relief="flat",
            borderwidth=0,
            font=("Consolas", 10),
            bg="#f8fbfe",
            fg="#122033",
            padx=10,
            pady=10,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.log_text.configure(state="disabled")
        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scroll.set)

    def get_target_address(self) -> tuple[int, int]:
        return int(self.download_addr_var.get() or "0"), int(self.download_dyn_addr_var.get() or "0")

    def get_update_type(self) -> int:
        return UPDATE_TYPE_FORCE if self.update_type_var.get() == "Force" else UPDATE_TYPE_NORMAL

    def set_firmware(self, image: FirmwareImage | None, *, summary: dict[str, str] | None = None) -> None:
        if image is None or summary is None:
            self.file_path_var.set(self.i18n.translate_text("No firmware loaded"))
            self.version_var.set("-")
            self.device_version_var.set("-")
            self.compile_time_var.set("-")
            self.file_size_var.set("-")
            self.commit_var.set("-")
            self.module_var.set("-")
            self.footer_crc_var.set("-")
            return
        self.file_path_var.set(str(Path(image.path)))
        self.version_var.set(summary["version"])
        self.compile_time_var.set(summary["compile_time"])
        self.file_size_var.set(summary["file_size"])
        self.commit_var.set(summary["commit"])
        self.module_var.set(summary["module"])
        self.footer_crc_var.set(summary["footer_crc"])

    def set_device_version(self, version_text: str) -> None:
        self.device_version_var.set(version_text or "-")

    def set_running(self, running: bool) -> None:
        self._running = running
        self.start_button.configure(text=self.i18n.translate_text("Stop Upgrade" if running else "Start Upgrade"))

    def set_connection_state(self, connected: bool, port_label: str = "") -> None:
        self.connection_var.set(
            self.i18n.format_text("Connected: {port}", port=port_label)
            if connected and port_label
            else self.i18n.translate_text("Serial port connected" if connected else "Serial port disconnected")
        )

    def set_status(self, status: str, detail: str = "", *, error_code: str = "-") -> None:
        self.status_var.set(self.i18n.translate_text(status))
        self.detail_var.set(self.i18n.translate_text(detail or ""))
        code = error_code if error_code and error_code != "-" else "-"
        self.error_var.set(self.i18n.format_text("Error Code: {code}", code=code))

    def set_progress(self, sent_bytes: int, total_bytes: int) -> None:
        total = max(total_bytes, 0)
        sent = min(max(sent_bytes, 0), total) if total else 0
        percent = (sent / total * 100.0) if total else 0.0
        self.progress["value"] = percent
        self.progress_text_var.set(f"{sent} / {total} bytes")
        self.progress_percent_var.set(f"{percent:.1f}%")

    def reset_forward_progress(self, detail: str = "Waiting for the main upgrade flow to start") -> None:
        self.forward_status_var.set(self.i18n.translate_text("LLC -> PFC forward progress is idle"))
        self.forward_detail_var.set(self.i18n.translate_text(detail))
        self.forward_progress["value"] = 0
        self.forward_text_var.set("0 / 0 bytes")
        self.forward_percent_var.set("0%")

    def set_forward_progress(self, *, status: str, detail: str, forwarded_bytes: int, total_bytes: int, progress_permille: int = 0) -> None:
        total = max(total_bytes, 0)
        forwarded = min(max(forwarded_bytes, 0), total) if total else max(forwarded_bytes, 0)
        if total > 0:
            percent = forwarded / total * 100.0
        else:
            percent = max(min(progress_permille, 1000), 0) / 10.0
        self.forward_status_var.set(self.i18n.translate_text(status))
        self.forward_detail_var.set(self.i18n.translate_text(detail))
        self.forward_progress["value"] = percent
        self.forward_text_var.set(f"{forwarded} / {total} bytes")
        self.forward_percent_var.set(f"{percent:.1f}%")

    def refresh_texts(self) -> None:
        for widget, source_text, option in self._translatable_widgets:
            widget.configure(**{option: self.i18n.translate_text(source_text)})
        self.file_path_var.set(self.i18n.translate_text(self.file_path_var.get()))
        self.status_var.set(self.i18n.translate_text(self.status_var.get()))
        self.detail_var.set(self.i18n.translate_text(self.detail_var.get()))
        self.connection_var.set(self.i18n.translate_text(self.connection_var.get()))
        self.forward_status_var.set(self.i18n.translate_text(self.forward_status_var.get()))
        self.forward_detail_var.set(self.i18n.translate_text(self.forward_detail_var.get()))
        self.error_var.set(self.i18n.translate_text(self.error_var.get()))
        self.set_running(self._running)

    def _remember_text(self, widget: object, source_text: str, option: str = "text") -> None:
        self._translatable_widgets.append((widget, source_text, option))

    def append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
