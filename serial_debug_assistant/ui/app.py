from __future__ import annotations

import queue
import struct
from pathlib import Path
import time
import tkinter as tk
from tkinter import filedialog, ttk

import serial
from serial_debug_assistant.app_paths import ensure_runtime_dirs, get_app_paths, migrate_legacy_data
from serial_debug_assistant.black_box_protocol import (
    CMD_SET_BLACK_BOX,
    CMD_WORD_BLACK_BOX_COMPLETE,
    CMD_WORD_BLACK_BOX_HEADER,
    CMD_WORD_BLACK_BOX_RANGE_QUERY,
    CMD_WORD_BLACK_BOX_ROW,
    build_black_box_range_query_payload,
    parse_black_box_complete_payload,
    parse_black_box_header_payload,
    parse_black_box_range_query_ack,
    parse_black_box_row_payload,
)
from serial_debug_assistant.factory_mode import (
    CMD_SET_FACTORY_CALI_READ,
    CMD_SET_FACTORY_CALI_SAVE,
    CMD_SET_FACTORY_CALI_WRITE,
    CMD_SET_FACTORY_TIME_QUERY,
    CMD_SET_FACTORY_TIME_WRITE,
    CMD_WORD_FACTORY_CALI_READ,
    CMD_WORD_FACTORY_CALI_SAVE,
    CMD_WORD_FACTORY_CALI_WRITE,
    CMD_WORD_FACTORY_TIME_QUERY,
    CMD_WORD_FACTORY_TIME_WRITE,
    build_factory_cali_read_payload,
    build_factory_cali_save_payload,
    build_factory_cali_write_payload,
    parse_factory_cali_payload,
    build_factory_time_query_payload,
    build_factory_time_write_payload,
    format_factory_time_string,
    format_timezone_label,
    parse_factory_time_payload,
    parse_timezone_input,
)

from serial_debug_assistant.constants import (
    APP_GEOMETRY,
    APP_MIN_HEIGHT,
    APP_MIN_WIDTH,
    APP_TITLE,
    BAUD_RATES,
    BYTE_SIZES,
    DEFAULT_AUTO_SEND_SECONDS,
    DEFAULT_BAUD_RATE,
    DEFAULT_BREAK_MS,
    DEFAULT_DATA_BITS,
    DEFAULT_PARITY,
    DEFAULT_STOP_BITS,
    PARITY_OPTIONS,
    POLL_INTERVAL_MS,
    STOP_BITS_OPTIONS,
)
from serial_debug_assistant.debug_logger import DebugLogger
from serial_debug_assistant.firmware_update import (
    CMD_SET_UPDATE,
    CMD_WORD_FIRMWARE_VERSION_QUERY,
    CMD_WORD_LLC_PFC_UPGRADE_PROGRESS_QUERY,
    CMD_WORD_UPDATE_END,
    CMD_WORD_UPDATE_FW,
    CMD_WORD_UPDATE_INFO,
    CMD_WORD_UPDATE_READY,
    build_firmware_version_query_payload,
    build_llc_pfc_upgrade_progress_query_payload,
    build_update_end_payload,
    build_update_info_payload,
    build_update_packet_payload,
    build_update_ready_payload,
    describe_llc_pfc_upgrade_error,
    describe_reject_reason,
    format_unix_time,
    format_version,
    load_firmware_image,
    module_name,
    parse_firmware_version_ack,
    parse_llc_pfc_upgrade_progress_ack,
)
from serial_debug_assistant.i18n import I18nManager
from serial_debug_assistant.models import FirmwareImage, FirmwareUpdateSession, ParameterEntry, ProtocolFrame
from serial_debug_assistant.protocol import (
    FrameParser,
    build_frame,
    format_value,
    u32_to_value,
    value_to_u32,
)
from serial_debug_assistant.services.serial_service import SerialService
from serial_debug_assistant.ui.black_box_tab import BlackBoxTab
from serial_debug_assistant.ui.factory_mode_tab import FactoryModeTab
from serial_debug_assistant.ui.home_tab import HomeTab
from serial_debug_assistant.ui.monitor_tab import SerialMonitorTab
from serial_debug_assistant.ui.parameter_tab import ParameterReadWriteTab
from serial_debug_assistant.ui.upgrade_tab import UpgradeTab
from serial_debug_assistant.ui.wave_tab import WaveformTab

FAULT_MESSAGES = {
    0: "MPPT输入过压",
    1: "MPPT输入硬件过流",
    2: "MPPT输入软件过流",
    3: "AC输出短路",
    4: "AC输出过流",
    5: "AC输出有功功率过载",
    6: "AC输出视在功率过载",
    7: "PFC充电市电软启动失败",
    8: "PFC充电PFC软启动失败",
    9: "LLC放电软启动失败",
    10: "采样错误",
    11: "电池单体欠压",
    12: "母线过压",
    13: "母线欠压",
    14: "PFC故障",
    15: "电池过流",
    16: "电池硬件过流",
    17: "电池单体过压",
    18: "BMS温度异常",
    19: "电池充电过流",
    20: "电池放电过流",
    21: "电网异常",
    22: "PCS温度异常",
    23: "参数配置错误",
}

WARNING_MESSAGES = {
    0: "市电过压",
    1: "市电欠压",
    2: "市电过频",
    3: "市电欠频",
}

MAX_RX_CHUNKS_PER_POLL = 200
MAX_RX_BYTES_PER_POLL = 262_144
SAVE_FLUSH_INTERVAL_SECONDS = 0.4
HOME_REFRESH_INTERVAL_MS = 120


class SerialDebugAssistant(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.i18n = I18nManager("zh")
        self._translatable_widgets: list[tuple[object, str, str]] = []
        self.title(APP_TITLE)
        self.geometry(APP_GEOMETRY)
        self.minsize(APP_MIN_WIDTH, APP_MIN_HEIGHT)
        self.configure(bg="#edf3f8")

        self.paths = get_app_paths()
        ensure_runtime_dirs(self.paths)
        migration_notes = migrate_legacy_data(self.paths)
        self.logger = DebugLogger(self.paths.app_log_file)
        self.serial_service = SerialService()
        self.port_display_map: dict[str, str] = {}
        self.frame_parser = FrameParser()
        self.total_rx_bytes = 0
        self.total_tx_bytes = 0
        self.auto_send_job: str | None = None
        self.save_handle = None
        self.save_path: Path | None = None
        self.last_save_flush_at = 0.0
        self.expected_param_count = 0
        self.parameters: dict[str, ParameterEntry] = {}
        self.wave_running = False
        self.wave_report_period_ms = 300
        self.pending_rx_hex_bytes = bytearray()
        self.pending_wave_batch: dict[str, float] = {}
        self.wave_batch_open = False
        self.wave_batch_counter = 0
        self.wave_debug_batches_remaining = 0
        self.wave_debug_frame_budget = 0
        self.last_wave_table_sync = 0.0
        self.parameter_list_request_job: str | None = None
        self.ignore_wave_frames_until = 0.0
        self.loaded_firmware: FirmwareImage | None = None
        self.update_session: FirmwareUpdateSession | None = None
        self.update_tick_job: str | None = None
        self.home_refresh_job: str | None = None
        self.pending_home_info: dict[str, float | int] | None = None
        self.pending_home_fault_log: str | None = None
        self.pending_home_warning_log: str | None = None
        self.factory_time_snapshot: dict[str, int] | None = None
        self.factory_cali_snapshot: dict[str, float | int] | None = None

        self.port_var = tk.StringVar()
        self.baud_var = tk.StringVar(value=DEFAULT_BAUD_RATE)
        self.data_bits_var = tk.StringVar(value=DEFAULT_DATA_BITS)
        self.parity_var = tk.StringVar(value=DEFAULT_PARITY)
        self.stop_bits_var = tk.StringVar(value=DEFAULT_STOP_BITS)
        self.status_var = tk.StringVar(value=self.i18n.translate_text("Ready"))
        self.rx_count_var = tk.StringVar(value=self.i18n.format_text("Receive: {count} bytes", count=0))
        self.tx_count_var = tk.StringVar(value=self.i18n.format_text("Send: {count} bytes", count=0))
        self.break_ms_var = tk.StringVar(value=DEFAULT_BREAK_MS)
        self.auto_send_seconds_var = tk.StringVar(value=DEFAULT_AUTO_SEND_SECONDS)
        self.send_hex_var = tk.BooleanVar(value=False)
        self.recv_hex_var = tk.BooleanVar(value=False)
        self.timestamp_var = tk.BooleanVar(value=False)
        self.save_to_file_var = tk.BooleanVar(value=False)
        self.auto_break_var = tk.BooleanVar(value=False)
        self.auto_send_var = tk.BooleanVar(value=False)
        self.line_mode_var = tk.BooleanVar(value=True)
        self.display_send_string_var = tk.BooleanVar(value=True)
        self.parameter_status_var = tk.StringVar(value=self.i18n.format_text("参数提示: {message}", message=self.i18n.translate_text("参数页就绪")))
        self.language_var = tk.StringVar(value=self.i18n.get_label_for_language(self.i18n.language))

        self._configure_styles()
        self._build_ui()
        self.logger.log("APP", f"startup log_file={self.logger.log_path}")
        for note in migration_notes:
            self.logger.log("APP", note)
        self.refresh_ports()
        self.after(POLL_INTERVAL_MS, self.process_incoming_data)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        app_bg = "#edf3f8"
        panel_bg = "#fbfdff"
        sidebar_bg = "#e3ebf4"
        border = "#bfd0e3"
        accent = "#1f6feb"
        accent_active = "#1557b5"
        muted_text = "#5b6b7f"
        text = "#112033"

        self.configure(bg=app_bg)

        style.configure("App.TFrame", background=app_bg)
        style.configure("Panel.TFrame", background=panel_bg, relief="flat")
        style.configure("Sidebar.TFrame", background=sidebar_bg, relief="flat")
        style.configure("Section.TLabelframe", background=panel_bg, borderwidth=1, relief="solid", bordercolor=border)
        style.configure("Sidebar.Section.TLabelframe", background=sidebar_bg, borderwidth=1, relief="solid", bordercolor=border)
        style.configure(
            "Section.TLabelframe.Label",
            background=panel_bg,
            foreground="#36506b",
            font=("Segoe UI Semibold", 10),
        )
        style.configure(
            "Sidebar.Section.TLabelframe.Label",
            background=sidebar_bg,
            foreground="#36506b",
            font=("Segoe UI Semibold", 10),
        )
        style.configure("TLabel", background=panel_bg, foreground=text, font=("Segoe UI", 10))
        style.configure("Status.TLabel", background=app_bg, foreground=muted_text, font=("Segoe UI", 10))
        style.configure("ErrorStatus.TLabel", background=app_bg, foreground="#c23b3b", font=("Segoe UI", 10))
        style.configure(
            "Header.TLabel",
            background=app_bg,
            foreground=text,
            font=("Segoe UI Semibold", 11),
        )
        style.configure(
            "SidebarHeader.TLabel",
            background=sidebar_bg,
            foreground=text,
            font=("Segoe UI Semibold", 11),
        )
        style.configure("Sidebar.TLabel", background=sidebar_bg, foreground=text, font=("Segoe UI", 10))
        style.configure(
            "TButton",
            font=("Segoe UI", 10),
            padding=(10, 6),
            background="#f6f9fc",
            foreground=text,
            borderwidth=1,
            relief="solid",
            bordercolor=border,
        )
        style.map(
            "TButton",
            background=[("active", "#e8f0f8"), ("pressed", "#dde8f5")],
            bordercolor=[("focus", accent)],
        )
        style.configure(
            "Accent.TButton",
            foreground="#ffffff",
            background=accent,
            borderwidth=0,
            font=("Segoe UI Semibold", 10),
            padding=(12, 8),
        )
        style.map("Accent.TButton", background=[("active", accent_active), ("disabled", "#8fb8f2")])
        style.configure("TCheckbutton", background=panel_bg, foreground=text, font=("Segoe UI", 10))
        style.configure("Sidebar.TCheckbutton", background=sidebar_bg, foreground=text, font=("Segoe UI", 10))
        style.configure("TRadiobutton", background=panel_bg, foreground=text, font=("Segoe UI", 10))
        style.configure(
            "TEntry",
            fieldbackground="#ffffff",
            foreground=text,
            bordercolor=border,
            lightcolor=border,
            darkcolor=border,
            insertcolor=accent,
            padding=5,
        )
        style.configure(
            "TCombobox",
            padding=5,
            fieldbackground="#f4f8fc",
            foreground=text,
            bordercolor=border,
            lightcolor=border,
            darkcolor=border,
            arrowsize=14,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", "#f4f8fc"), ("focus", "#f4f8fc")],
            selectbackground=[("readonly", "#dce9f7")],
            selectforeground=[("readonly", text)],
        )
        style.configure("Horizontal.TProgressbar", background=accent, troughcolor="#dce6f1", bordercolor="#dce6f1", lightcolor=accent, darkcolor=accent)
        style.configure("Treeview", background="#ffffff", fieldbackground="#ffffff", foreground=text, bordercolor=border, rowheight=28)
        style.configure("Treeview.Heading", background="#edf4fb", foreground="#36506b", relief="flat", font=("Segoe UI Semibold", 10))
        style.map("Treeview.Heading", background=[("active", "#dfeaf6")])
        style.configure("TNotebook", background=panel_bg, borderwidth=0, tabmargins=(0, 0, 0, 0))
        style.configure(
            "TNotebook.Tab",
            background="#e7eef6",
            foreground="#4a5d73",
            padding=(14, 7),
            font=("Segoe UI Semibold", 10),
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", panel_bg), ("active", "#dbe6f2")],
            foreground=[("selected", text), ("active", text)],
            padding=[("selected", (16, 11, 16, 9)), ("!selected", (14, 6, 14, 6))],
        )

    def _build_ui(self) -> None:
        root = ttk.Frame(self, style="App.TFrame", padding=16)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=0)
        root.rowconfigure(1, weight=1)
        root.rowconfigure(2, weight=0)

        serial_bar = ttk.Frame(root, style="Sidebar.TFrame", padding=(16, 14))
        serial_bar.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        self._build_serial_bar(serial_bar)

        content = ttk.Frame(root, style="Panel.TFrame", padding=2)
        content.grid(row=1, column=0, sticky="nsew")
        content.rowconfigure(0, weight=1)
        content.columnconfigure(0, weight=1)

        self.notebook = ttk.Notebook(content)
        self.notebook.grid(row=0, column=0, sticky="nsew")

        monitor_page = ttk.Frame(self.notebook, style="App.TFrame", padding=0)
        monitor_page.columnconfigure(0, weight=0, minsize=300)
        monitor_page.columnconfigure(1, weight=1)
        monitor_page.rowconfigure(0, weight=1)

        monitor_settings = ttk.Frame(monitor_page, style="Sidebar.TFrame", padding=16)
        monitor_settings.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        self._build_monitor_settings(monitor_settings)

        self.home_tab = HomeTab(self.notebook, i18n=self.i18n)
        self.home_tab.bind_inv_cfg_actions(
            on_enable=self.request_enable_ac_output,
            on_disable=self.request_disable_ac_output,
            on_send=self.send_home_inv_cfg,
            on_read=self.request_home_inv_cfg,
        )

        self.monitor_tab = SerialMonitorTab(
            monitor_page,
            on_send=self.send_payload,
            on_send_preset=self.send_preset_payload,
            on_reset_count=self.reset_counters,
            config_path=self.paths.quick_send_config,
            on_layout_change=self._log_monitor_layout,
            receive_hex_var=self.recv_hex_var,
            send_hex_var=self.send_hex_var,
            i18n=self.i18n,
        )
        self.monitor_tab.grid(row=0, column=1, sticky="nsew")

        self.parameter_tab = ParameterReadWriteTab(
            self.notebook,
            on_read_list=self.request_parameter_list,
            on_read_param=self.request_single_parameter,
            on_write_param=self.write_single_parameter,
            on_toggle_wave=self.toggle_auto_report,
            i18n=self.i18n,
        )
        self.parameter_tab.message_var.trace_add("write", self._on_parameter_message_changed)
        self.wave_tab = WaveformTab(
            self.notebook,
            on_apply_period=self.apply_wave_period,
            on_toggle_run=self.toggle_wave_run,
            on_clear=self.clear_wave_data,
            export_dir=self.paths.exports_dir,
            on_status=lambda message, is_error=False: self.set_status(message, error=is_error),
            i18n=self.i18n,
        )
        self.upgrade_tab = UpgradeTab(
            self.notebook,
            on_browse=self.load_upgrade_firmware,
            on_start_stop=self.toggle_upgrade,
            on_read_version=self.request_upgrade_device_version,
            i18n=self.i18n,
        )
        self.black_box_tab = BlackBoxTab(
            self.notebook,
            on_query=self.request_black_box_range_query,
            export_dir=self.paths.exports_dir,
            i18n=self.i18n,
        )
        self.factory_mode_tab = FactoryModeTab(
            self.notebook,
            on_read_time=self.request_factory_time_read,
            on_set_current_time=self.send_factory_current_pc_time,
            on_read_cali=self.request_factory_cali_read,
            on_write_cali=self.send_factory_cali_write,
            on_save_cali=self.send_factory_cali_save,
            i18n=self.i18n,
        )

        self.notebook.add(self.home_tab, text=self.i18n.translate_text("主页"))
        self.notebook.add(monitor_page, text=self.i18n.translate_text("串口调试"))
        self.notebook.add(self.parameter_tab, text=self.i18n.translate_text("参数读写"))
        self.notebook.add(self.wave_tab, text=self.i18n.translate_text("参数波形"))
        self.notebook.add(self.upgrade_tab, text=self.i18n.translate_text("固件升级"))
        self.notebook.add(self.black_box_tab, text=self.i18n.translate_text("Black Box"))
        self.notebook.add(self.factory_mode_tab, text=self.i18n.translate_text("Factory Mode"))
        self.notebook.select(self.home_tab)

        footer = ttk.Frame(root, style="App.TFrame")
        footer.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        footer.columnconfigure(0, weight=1)
        footer.columnconfigure(1, weight=1)
        footer.columnconfigure(2, weight=1)
        footer.columnconfigure(3, weight=1)
        ttk.Label(footer, textvariable=self.tx_count_var, style="Status.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(footer, textvariable=self.rx_count_var, style="Status.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(footer, textvariable=self.parameter_status_var, style="Status.TLabel").grid(row=0, column=2, sticky="w")
        self.status_label = ttk.Label(footer, textvariable=self.status_var, style="Status.TLabel")
        self.status_label.grid(row=0, column=3, sticky="e")

    def _build_serial_bar(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(2, weight=1)
        parent.columnconfigure(12, weight=1)
        parent.columnconfigure(13, weight=0)
        serial_label = ttk.Label(parent, text=self.i18n.translate_text("Serial Port"), style="SidebarHeader.TLabel")
        serial_label.grid(row=0, column=0, sticky="w", padx=(0, 16))
        self._remember_text(serial_label, "Serial Port")

        controls = [
            ("Port Name", self._build_port_selector),
            ("Baud Rate", self._build_baud_selector),
            ("Data Bits", self._build_data_bits_selector),
            ("Parity", self._build_parity_selector),
            ("Stop Bits", self._build_stop_bits_selector),
        ]
        col = 1
        for label, builder in controls:
            label_widget = ttk.Label(parent, text=f"{self.i18n.translate_text(label)} :", style="Sidebar.TLabel")
            label_widget.grid(row=0, column=col, sticky="w", padx=(0, 6))
            self._translatable_widgets.append((label_widget, f"{label} :", "text"))
            builder(parent, 0, col + 1)
            col += 2

        self.open_button = ttk.Button(parent, text=self.i18n.translate_text("Open"), command=self.toggle_connection, style="Accent.TButton")
        self.open_button.grid(row=0, column=11, sticky="w", padx=(12, 0))
        self._remember_text(self.open_button, "Open")
        language_label = ttk.Label(parent, text=self.i18n.translate_text("Language"), style="Sidebar.TLabel")
        language_label.grid(row=0, column=12, sticky="e", padx=(12, 6))
        self._remember_text(language_label, "Language")
        self.language_combo = ttk.Combobox(parent, textvariable=self.language_var, state="readonly", values=self.i18n.get_language_labels(), width=12)
        self.language_combo.grid(row=0, column=13, sticky="e")
        self.language_combo.bind("<<ComboboxSelected>>", self._on_language_changed)

    def _build_monitor_settings(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        debug_label = ttk.Label(parent, text=self.i18n.translate_text("Debug Settings"), style="SidebarHeader.TLabel")
        debug_label.grid(row=0, column=0, sticky="w", pady=(0, 12))
        self._remember_text(debug_label, "Debug Settings")

        row = 1
        receive_frame = ttk.LabelFrame(parent, text=self.i18n.translate_text("Receive Settings"), style="Sidebar.Section.TLabelframe", padding=12)
        self._remember_text(receive_frame, "Receive Settings")
        receive_frame.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        receive_frame.columnconfigure(0, weight=1)
        receive_frame.columnconfigure(1, weight=1)
        row += 1

        self.save_file_check = ttk.Checkbutton(receive_frame, text=self.i18n.translate_text("Save receiving to file"), variable=self.save_to_file_var, command=self.on_toggle_save_to_file, style="Sidebar.TCheckbutton")
        self.save_file_check.grid(row=0, column=0, columnspan=2, sticky="w", pady=2)
        self._remember_text(self.save_file_check, "Save receiving to file")
        self.hex_display_check = ttk.Checkbutton(receive_frame, text=self.i18n.translate_text("HEX display"), variable=self.recv_hex_var, style="Sidebar.TCheckbutton")
        self.hex_display_check.grid(row=1, column=0, columnspan=2, sticky="w", pady=2)
        self._remember_text(self.hex_display_check, "HEX display")
        self.auto_break_check = ttk.Checkbutton(receive_frame, text=self.i18n.translate_text("Auto break frame"), variable=self.auto_break_var, style="Sidebar.TCheckbutton")
        self.auto_break_check.grid(row=2, column=0, sticky="w", pady=2)
        self._remember_text(self.auto_break_check, "Auto break frame")
        ttk.Entry(receive_frame, textvariable=self.break_ms_var, width=8).grid(row=2, column=1, sticky="e", pady=2)
        self.timestamp_check = ttk.Checkbutton(receive_frame, text=self.i18n.translate_text("Add timestamp"), variable=self.timestamp_var, style="Sidebar.TCheckbutton")
        self.timestamp_check.grid(row=3, column=0, columnspan=2, sticky="w", pady=2)
        self._remember_text(self.timestamp_check, "Add timestamp")
        self.clear_data_button = ttk.Button(receive_frame, text=self.i18n.translate_text("Clear data"), command=self.clear_receive_area)
        self.clear_data_button.grid(row=4, column=0, sticky="ew", pady=(8, 0), padx=(0, 6))
        self._remember_text(self.clear_data_button, "Clear data")
        self.save_data_button = ttk.Button(receive_frame, text=self.i18n.translate_text("Save data"), command=self.save_receive_snapshot)
        self.save_data_button.grid(row=4, column=1, sticky="ew", pady=(8, 0))
        self._remember_text(self.save_data_button, "Save data")

        send_frame = ttk.LabelFrame(parent, text=self.i18n.translate_text("Send Settings"), style="Sidebar.Section.TLabelframe", padding=12)
        self._remember_text(send_frame, "Send Settings")
        send_frame.grid(row=row, column=0, columnspan=3, sticky="ew")
        send_frame.columnconfigure(0, weight=1)
        send_frame.columnconfigure(1, weight=1)
        self.hex_send_check = ttk.Checkbutton(send_frame, text=self.i18n.translate_text("HEX send"), variable=self.send_hex_var, style="Sidebar.TCheckbutton")
        self.hex_send_check.grid(row=0, column=0, columnspan=2, sticky="w", pady=2)
        self._remember_text(self.hex_send_check, "HEX send")
        self.timing_send_check = ttk.Checkbutton(send_frame, text=self.i18n.translate_text("Timing send"), variable=self.auto_send_var, command=self.on_toggle_auto_send, style="Sidebar.TCheckbutton")
        self.timing_send_check.grid(row=1, column=0, sticky="w", pady=2)
        self._remember_text(self.timing_send_check, "Timing send")
        ttk.Entry(send_frame, textvariable=self.auto_send_seconds_var, width=8).grid(row=1, column=1, sticky="e", pady=2)
        self.line_mode_check = ttk.Checkbutton(send_frame, text=self.i18n.translate_text("Send line ending (CRLF)"), variable=self.line_mode_var, style="Sidebar.TCheckbutton")
        self.line_mode_check.grid(row=2, column=0, columnspan=2, sticky="w", pady=2)
        self._remember_text(self.line_mode_check, "Send line ending (CRLF)")
        self.display_send_check = ttk.Checkbutton(send_frame, text=self.i18n.translate_text("Display send string"), variable=self.display_send_string_var, style="Sidebar.TCheckbutton")
        self.display_send_check.grid(row=3, column=0, columnspan=2, sticky="w", pady=2)
        self._remember_text(self.display_send_check, "Display send string")
        self.refresh_ports_button = ttk.Button(send_frame, text=self.i18n.translate_text("Refresh Ports"), command=self.refresh_ports)
        self.refresh_ports_button.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self._remember_text(self.refresh_ports_button, "Refresh Ports")

    def _build_port_selector(self, parent: ttk.Frame, row: int, column: int) -> None:
        holder = ttk.Frame(parent, style="Sidebar.TFrame")
        holder.grid(row=row, column=column, sticky="ew", padx=(0, 12))
        holder.columnconfigure(0, weight=1)
        self.port_combo = ttk.Combobox(holder, textvariable=self.port_var, state="readonly", width=18)
        self.port_combo.grid(row=0, column=0, sticky="ew")
        self.port_refresh_button = ttk.Button(holder, text=self.i18n.translate_text("刷新"), command=self.refresh_ports, width=5)
        self.port_refresh_button.grid(row=0, column=1, padx=(6, 0))
        self._remember_text(self.port_refresh_button, "刷新")

    def _build_baud_selector(self, parent: ttk.Frame, row: int, column: int) -> None:
        ttk.Combobox(parent, textvariable=self.baud_var, values=BAUD_RATES, width=10).grid(row=row, column=column, sticky="w", padx=(0, 12))

    def _build_data_bits_selector(self, parent: ttk.Frame, row: int, column: int) -> None:
        ttk.Combobox(parent, textvariable=self.data_bits_var, values=tuple(BYTE_SIZES.keys()), state="readonly", width=7).grid(row=row, column=column, sticky="w", padx=(0, 12))

    def _build_parity_selector(self, parent: ttk.Frame, row: int, column: int) -> None:
        ttk.Combobox(parent, textvariable=self.parity_var, values=tuple(PARITY_OPTIONS.keys()), state="readonly", width=9).grid(row=row, column=column, sticky="w", padx=(0, 12))

    def _build_stop_bits_selector(self, parent: ttk.Frame, row: int, column: int) -> None:
        ttk.Combobox(parent, textvariable=self.stop_bits_var, values=tuple(STOP_BITS_OPTIONS.keys()), state="readonly", width=7).grid(row=row, column=column, sticky="w", padx=(0, 12))

    def _on_language_changed(self, _event=None) -> None:
        self.i18n.set_language(self.i18n.get_language_from_label(self.language_var.get()))
        self.language_var.set(self.i18n.get_label_for_language(self.i18n.language))
        self._apply_language()

    def _apply_language(self) -> None:
        for widget, source_text, option in self._translatable_widgets:
            if source_text.endswith(" :"):
                base_text = source_text[:-2]
                widget.configure(**{option: f"{self.i18n.translate_text(base_text)} :"})
            else:
                widget.configure(**{option: self.i18n.translate_text(source_text)})
        self.language_combo.configure(values=self.i18n.get_language_labels())
        self._set_open_button_text("Close" if self.serial_service.is_open() else "Open")
        self.notebook.tab(0, text=self.i18n.translate_text("主页"))
        self.notebook.tab(1, text=self.i18n.translate_text("串口调试"))
        self.notebook.tab(2, text=self.i18n.translate_text("参数读写"))
        self.notebook.tab(3, text=self.i18n.translate_text("参数波形"))
        self.notebook.tab(4, text=self.i18n.translate_text("固件升级"))
        self.notebook.tab(5, text=self.i18n.translate_text("Black Box"))
        self.notebook.tab(6, text=self.i18n.translate_text("Factory Mode"))
        self.home_tab.refresh_texts()
        self.monitor_tab.refresh_texts()
        self.parameter_tab.refresh_texts()
        self.wave_tab.refresh_texts()
        self.upgrade_tab.refresh_texts()
        self.black_box_tab.refresh_texts()
        self.factory_mode_tab.refresh_texts()
        self._update_counter_labels()
        self._on_parameter_message_changed()
        self.set_status(self.status_var.get(), error=self.status_label.cget("style") == "ErrorStatus.TLabel")

    def _update_counter_labels(self) -> None:
        self.rx_count_var.set(self.i18n.format_text("Receive: {count} bytes", count=self.total_rx_bytes))
        self.tx_count_var.set(self.i18n.format_text("Send: {count} bytes", count=self.total_tx_bytes))

    def _remember_text(self, widget: object, source_text: str, option: str = "text") -> None:
        self._translatable_widgets.append((widget, source_text, option))

    def _log_monitor_layout(self, layout: dict[str, int | str]) -> None:
        self.logger.log(
            "LAYOUT",
            "monitor_split "
            f"source={layout['source']} total_height={layout['total_height']} "
            f"sash_y={layout['sash_y']} top_height={layout['top_height']} "
            f"bottom_height={layout['bottom_height']} "
            f"send_tabs_height={layout.get('send_tabs_height', 0)} "
            f"manual_tab_height={layout.get('manual_tab_height', 0)} "
            f"preset_tab_height={layout.get('preset_tab_height', 0)} "
            f"receive_reqheight={layout.get('receive_reqheight', 0)} "
            f"send_reqheight={layout.get('send_reqheight', 0)} "
            f"send_tabs_reqheight={layout.get('send_tabs_reqheight', 0)} "
            f"manual_reqheight={layout.get('manual_reqheight', 0)} "
            f"preset_reqheight={layout.get('preset_reqheight', 0)}",
        )

    def refresh_ports(self) -> None:
        ports = self.serial_service.list_ports_with_details()
        display_values = [item["display"] for item in ports]
        self.port_display_map = {item["display"]: item["device"] for item in ports}
        current_device = self.port_display_map.get(self.port_var.get(), self.port_var.get())
        self.port_combo["values"] = display_values
        if display_values:
            selected_display = next(
                (item["display"] for item in ports if item["device"] == current_device),
                display_values[0],
            )
            self.port_var.set(selected_display)
        else:
            self.port_var.set("")
        self.set_status(self.i18n.format_text("Ready | {count} port(s) found", count=len(display_values)))
        self.logger.log("PORTS", f"refresh -> {display_values}")

    def toggle_connection(self) -> None:
        if self.serial_service.is_open():
            self.close_connection()
        else:
            self.open_connection()

    def open_connection(self) -> None:
        if not self.port_var.get():
            self.set_status(self.i18n.translate_text("Please select a serial port."), error=True)
            return
        selected_port = self.port_display_map.get(self.port_var.get(), self.port_var.get())
        try:
            self.serial_service.open(
                port=selected_port,
                baudrate=int(self.baud_var.get()),
                data_bits=self.data_bits_var.get(),
                parity=self.parity_var.get(),
                stop_bits=self.stop_bits_var.get(),
            )
        except (ValueError, KeyError) as exc:
            self.set_status(f"Serial settings are invalid: {exc}", error=True)
            return
        except serial.SerialException as exc:
            self.set_status(f"Open failed: {exc}", error=True)
            return

        self.serial_service.start_reader(
            auto_break_enabled_supplier=lambda: self.auto_break_var.get(),
            break_ms_supplier=self._current_break_ms,
            error_callback=lambda error: self.after(0, lambda error_message=error: self._handle_serial_error(error_message)),
        )
        self.frame_parser = FrameParser()
        self.wave_running = False
        self.wave_tab.set_running(False)
        self.pending_rx_hex_bytes.clear()
        self.pending_wave_batch.clear()
        self.wave_batch_open = False
        self.set_status(self.i18n.format_text("Connected to {port}", port=selected_port))
        self.upgrade_tab.set_connection_state(True, selected_port)
        self.parameter_tab.set_message("串口已连接，已向广播地址发送停止波形上传命令")
        self._set_open_button_text("Close")
        self.logger.log("SERIAL", f"open port={selected_port} baud={self.baud_var.get()} data_bits={self.data_bits_var.get()} parity={self.parity_var.get()} stop_bits={self.stop_bits_var.get()}")
        self.logger.log("WAVE", "send broadcast stop on connect dst=0x00 d_dst=0x00")
        self.send_protocol_frame(dst=0x00, d_dst=0x00, cmd_set=0x01, cmd_word=0x0C, payload=bytes([0]))
        if self.auto_send_var.get():
            self.schedule_auto_send()

    def close_connection(self) -> None:
        self.cancel_auto_send()
        self.stop_upgrade(self.i18n.translate_text("串口已断开，升级已停止。"), user_initiated=False)
        self.serial_service.close()
        self.pending_rx_hex_bytes.clear()
        self.upgrade_tab.set_connection_state(False)
        self.set_status(self.i18n.translate_text("Disconnected"))
        self.parameter_tab.set_message("串口已断开")
        self._set_open_button_text("Open")
        self.logger.log("SERIAL", "close")

    def _set_open_button_text(self, text: str) -> None:
        self.open_button.configure(text=self.i18n.translate_text(text))

    def _on_parameter_message_changed(self, *_args) -> None:
        self.parameter_status_var.set(self.i18n.format_text("参数提示: {message}", message=self.parameter_tab.message_var.get()))

    def set_status(self, message: str, *, error: bool = False) -> None:
        self.status_var.set(self.i18n.translate_text(message))
        if hasattr(self, "status_label"):
            self.status_label.configure(style="ErrorStatus.TLabel" if error else "Status.TLabel")

    def _handle_serial_error(self, exc: str) -> None:
        self.logger.log("ERROR", f"serial error: {exc}")
        self.close_connection()
        self.set_status(f"Serial error: {exc}", error=True)

    def load_upgrade_firmware(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Firmware Image",
            filetypes=[("Binary Files", "*.bin"), (self.i18n.translate_text("All Files"), "*.*")],
        )
        if not path:
            return
        try:
            image = load_firmware_image(path)
        except (OSError, ValueError) as exc:
            self.upgrade_tab.set_status("Failed to load firmware", str(exc), error_code="LOAD")
            self.set_status(f"Load firmware failed: {exc}", error=True)
            return

        self.loaded_firmware = image
        if image.footer.module_id in {0x02, 0x03}:
            self.upgrade_tab.download_addr_var.set("2")
        summary = {
            "version": format_version(image.footer.version),
            "compile_time": format_unix_time(image.footer.unix_time),
            "file_size": f"{len(image.data)} byte",
            "commit": image.footer.commit_id or "-",
            "module": module_name(image.footer.module_id),
            "footer_crc": "OK" if image.footer_crc_ok else "FAIL",
        }
        self.upgrade_tab.set_firmware(image, summary=summary)
        self.upgrade_tab.clear_log()
        self.upgrade_tab.reset_forward_progress(
            "PFC forwarding progress will appear here after the main upgrade is accepted by LLC."
            if image.footer.module_id == 0x03
            else "This firmware image does not require LLC -> PFC forward-progress tracking."
        )
        self.upgrade_tab.append_log(f"Loaded firmware: {image.path}")
        self.upgrade_tab.append_log(f"Version: {summary['version']}")
        self.upgrade_tab.append_log(f"Build Time: {summary['compile_time']}")
        self.upgrade_tab.append_log(f"Module: {summary['module']}")
        self.upgrade_tab.append_log(f"Footer CRC32: {summary['footer_crc']}")
        if image.footer.module_id == 0x03:
            self.upgrade_tab.append_log("PFC firmware is sent to 0x02 by default. LLC receives it first and forwards it to PFC.")
        for warning in image.warnings:
            self.upgrade_tab.append_log(f"Warning: {warning}")

        if not image.footer_crc_ok:
            self.upgrade_tab.set_status("Firmware loaded, but footer CRC check failed", "Please verify the package output.", error_code="CRC32")
        elif image.warnings:
            self.upgrade_tab.set_status("Firmware loaded", image.warnings[0], error_code="-")
        else:
            self.upgrade_tab.set_status("Firmware loaded", "Ready to start the upgrade.", error_code="-")

    def request_upgrade_device_version(self) -> None:
        if not self.serial_service.is_open():
            self.set_status("Open the serial port first.", error=True)
            self.upgrade_tab.set_status("Cannot read device version", "Connect the serial port first.", error_code="SERIAL")
            return
        try:
            target_addr, target_dynamic_addr = self.upgrade_tab.get_target_address()
        except ValueError:
            self.upgrade_tab.set_status("Cannot read device version", "Target and dynamic addresses must be integers.", error_code="ADDR")
            return

        self.send_protocol_frame(
            cmd_set=CMD_SET_UPDATE,
            cmd_word=CMD_WORD_FIRMWARE_VERSION_QUERY,
            payload=build_firmware_version_query_payload(),
            dst=target_addr,
            d_dst=target_dynamic_addr,
        )
        self.upgrade_tab.set_status(
            "Reading device version",
            f"Query sent to {module_name(target_addr)}.",
            error_code="-",
        )
        self.upgrade_tab.append_log(
            f"TX 0x{CMD_WORD_FIRMWARE_VERSION_QUERY:02X} -> query firmware version from {module_name(target_addr)}"
        )

    def toggle_upgrade(self) -> None:
        if self.update_session is not None:
            self.stop_upgrade("Upgrade stopped by the user.", user_initiated=True)
            return
        self.start_upgrade()

    def start_upgrade(self) -> None:
        if not self.serial_service.is_open():
            self.set_status("Open the serial port first.", error=True)
            self.upgrade_tab.set_status("Cannot start upgrade", "Connect the serial port first.", error_code="SERIAL")
            return
        if self.loaded_firmware is None:
            self.upgrade_tab.set_status("Cannot start upgrade", "Load a .bin firmware file first.", error_code="FILE")
            return
        if not self.loaded_firmware.footer_crc_ok:
            self.upgrade_tab.set_status("Cannot start upgrade", "Footer CRC32 validation failed.", error_code="CRC32")
            return
        if self.loaded_firmware.footer.fw_type != 1:
            self.upgrade_tab.set_status("Cannot start upgrade", "Only fw_type=1 IAP firmware is supported.", error_code="FW_TYPE")
            return
        try:
            target_addr, target_dynamic_addr = self.upgrade_tab.get_target_address()
        except ValueError:
            self.upgrade_tab.set_status("Cannot start upgrade", "Target and dynamic addresses must be integers.", error_code="ADDR")
            return

        self.update_session = FirmwareUpdateSession(
            image=self.loaded_firmware,
            target_addr=target_addr,
            target_dynamic_addr=target_dynamic_addr,
            update_type=self.upgrade_tab.get_update_type(),
        )
        self.upgrade_tab.clear_log()
        self.upgrade_tab.set_running(True)
        self.upgrade_tab.set_progress(0, len(self.loaded_firmware.data))
        self.upgrade_tab.reset_forward_progress(
            "Waiting for LLC -> PFC forward-progress polling to begin after 0x0B."
            if self.loaded_firmware.footer.module_id == 0x03
            else "This firmware image does not require LLC -> PFC forward-progress tracking."
        )
        self.upgrade_tab.append_log(
            f"Start upgrade -> module={module_name(self.loaded_firmware.footer.module_id)} target=0x{target_addr:02X} d_target=0x{target_dynamic_addr:02X}"
        )
        if self.loaded_firmware.footer.module_id == 0x03 and target_addr != 0x02:
            self.upgrade_tab.append_log("Note: current PFC firmware should normally be sent to 0x02 so LLC can receive it first.")
        self._send_upgrade_info()

    def stop_upgrade(self, message: str, *, user_initiated: bool) -> None:
        if self.update_tick_job:
            self.after_cancel(self.update_tick_job)
            self.update_tick_job = None
        if self.update_session is None:
            self.upgrade_tab.set_running(False)
            return
        self.upgrade_tab.append_log(message)
        self.upgrade_tab.set_status("Upgrade stopped", message, error_code="STOP" if user_initiated else "-")
        self.upgrade_tab.set_running(False)
        self.update_session = None

    def _schedule_update_tick(self) -> None:
        if self.update_tick_job:
            self.after_cancel(self.update_tick_job)
        self.update_tick_job = self.after(120, self._process_upgrade_tick)

    def _process_upgrade_tick(self) -> None:
        self.update_tick_job = None
        session = self.update_session
        if session is None:
            return
        now = time.monotonic()
        if session.stage in {"wait_info_ack", "wait_ready_ack", "wait_packet_ack", "wait_end_ack", "wait_forward_progress_ack"}:
            if now - session.last_tx_at >= 1.0:
                if session.timeout_error_since is None:
                    session.timeout_error_since = now
                elif now - session.timeout_error_since >= 10.0:
                    self._fail_upgrade("Upgrade failed", "Communication timeout persisted for more than 10 seconds.", "TIMEOUT")
                    return

                if session.stage == "wait_info_ack":
                    self.upgrade_tab.append_log("0x08 timeout, resend upgrade info")
                    self._send_upgrade_info()
                    return
                if session.stage == "wait_ready_ack":
                    self.upgrade_tab.append_log("0x09 timeout, retry upgrade-ready query")
                    self._send_upgrade_ready()
                    return
                if session.stage == "wait_packet_ack":
                    self.upgrade_tab.append_log(f"0x0A timeout, resend offset={session.current_packet_offset}")
                    self._send_upgrade_packet(retry=True)
                    return
                if session.stage == "wait_end_ack":
                    self.upgrade_tab.append_log("0x0B timeout, resend end packet")
                    self._send_upgrade_end()
                    return
                if session.stage == "wait_forward_progress_ack":
                    self.upgrade_tab.append_log("0x0D timeout, retry LLC -> PFC forward-progress query")
                    self._send_llc_pfc_upgrade_progress_query()
                    return
        elif session.stage == "poll_forward_progress":
            if now - session.last_tx_at >= session.llc_forward_query_interval_seconds:
                self._send_llc_pfc_upgrade_progress_query()
                return
        self._schedule_update_tick()

    def _send_upgrade_info(self) -> None:
        session = self.update_session
        if session is None:
            return
        payload = build_update_info_payload(session.image, session.update_type)
        session.stage = "wait_info_ack"
        session.last_tx_at = time.monotonic()
        self.upgrade_tab.set_status("Upgrade in progress", "Send upgrade info (0x01 0x08)", error_code="-")
        self.upgrade_tab.append_log(
            f"TX 0x08 -> module=0x{session.image.footer.module_id:02X} version={format_version(session.image.footer.version)} size={len(session.image.data)} update_type={session.update_type}"
        )
        self.send_protocol_frame(
            dst=session.target_addr,
            d_dst=session.target_dynamic_addr,
            cmd_set=CMD_SET_UPDATE,
            cmd_word=CMD_WORD_UPDATE_INFO,
            payload=payload,
        )
        self._schedule_update_tick()

    def _send_upgrade_ready(self) -> None:
        session = self.update_session
        if session is None:
            return
        session.stage = "wait_ready_ack"
        session.last_tx_at = time.monotonic()
        self.upgrade_tab.set_status("Upgrade in progress", "Query upgrade-ready state (0x01 0x09)", error_code="-")
        self.upgrade_tab.append_log("TX 0x09 -> query whether the bootloader is ready")
        self.send_protocol_frame(
            dst=session.target_addr,
            d_dst=session.target_dynamic_addr,
            cmd_set=CMD_SET_UPDATE,
            cmd_word=CMD_WORD_UPDATE_READY,
            payload=build_update_ready_payload(),
        )
        self._schedule_update_tick()

    def _send_upgrade_packet(self, *, retry: bool = False) -> None:
        session = self.update_session
        if session is None:
            return
        payload = build_update_packet_payload(session.image, session.offset, session.packet_size)
        session.current_packet_offset = session.offset
        actual_len = min(session.packet_size, len(session.image.data) - session.offset)
        session.sent_bytes = min(session.offset + actual_len, len(session.image.data))
        session.stage = "wait_packet_ack"
        session.last_tx_at = time.monotonic()
        self.upgrade_tab.set_progress(session.sent_bytes, len(session.image.data))
        self.upgrade_tab.set_status(
            "Upgrade in progress",
            f"{'Resend' if retry else 'Send'} firmware packet (0x01 0x0A), offset={session.offset}",
            error_code="-",
        )
        self.upgrade_tab.append_log(
            f"TX 0x0A -> {'resend' if retry else 'send'} offset={session.offset} len={actual_len} progress={session.sent_bytes}/{len(session.image.data)}"
        )
        self.send_protocol_frame(
            dst=session.target_addr,
            d_dst=session.target_dynamic_addr,
            cmd_set=CMD_SET_UPDATE,
            cmd_word=CMD_WORD_UPDATE_FW,
            payload=payload,
        )
        self._schedule_update_tick()

    def _send_upgrade_end(self) -> None:
        session = self.update_session
        if session is None:
            return
        session.stage = "wait_end_ack"
        session.last_tx_at = time.monotonic()
        self.upgrade_tab.set_progress(len(session.image.data), len(session.image.data))
        self.upgrade_tab.set_status("Upgrade in progress", "Send end packet (0x01 0x0B)", error_code="-")
        self.upgrade_tab.append_log(
            f"TX 0x0B -> fw_crc16=0x{session.image.payload_crc16:04X} total={len(session.image.data)}"
        )
        self.send_protocol_frame(
            dst=session.target_addr,
            d_dst=session.target_dynamic_addr,
            cmd_set=CMD_SET_UPDATE,
            cmd_word=CMD_WORD_UPDATE_END,
            payload=build_update_end_payload(session.image),
        )
        self._schedule_update_tick()

    def _send_llc_pfc_upgrade_progress_query(self) -> None:
        session = self.update_session
        if session is None:
            return
        session.stage = "wait_forward_progress_ack"
        session.last_tx_at = time.monotonic()
        self.upgrade_tab.set_status(
            "Upgrade in progress",
            "Query current LLC -> PFC forward progress (0x01 0x0D)",
            error_code="-",
        )
        self.upgrade_tab.append_log("TX 0x0D -> query current LLC -> PFC upgrade forward progress")
        self.send_protocol_frame(
            dst=session.target_addr,
            d_dst=session.target_dynamic_addr,
            cmd_set=CMD_SET_UPDATE,
            cmd_word=CMD_WORD_LLC_PFC_UPGRADE_PROGRESS_QUERY,
            payload=build_llc_pfc_upgrade_progress_query_payload(),
        )
        self._schedule_update_tick()

    def _fail_upgrade(self, title: str, detail: str, error_code: str) -> None:
        self.upgrade_tab.append_log(f"{title}: {detail}")
        self.upgrade_tab.set_status(title, detail, error_code=error_code)
        self.upgrade_tab.set_running(False)
        self.update_session = None
        if self.update_tick_job:
            self.after_cancel(self.update_tick_job)
            self.update_tick_job = None

    def _complete_upgrade(self, detail: str) -> None:
        self.upgrade_tab.append_log(detail)
        self.upgrade_tab.set_status("升级成功", detail, error_code="-")
        self.upgrade_tab.set_running(False)
        self.update_session = None
        if self.update_tick_job:
            self.after_cancel(self.update_tick_job)
            self.update_tick_job = None

    def process_incoming_data(self) -> None:
        next_delay = POLL_INTERVAL_MS
        try:
            updated = False
            processed_chunks = 0
            processed_bytes = 0
            receive_fragments: list[str] = []
            save_buffer = bytearray()
            while processed_chunks < MAX_RX_CHUNKS_PER_POLL and processed_bytes < MAX_RX_BYTES_PER_POLL:
                try:
                    chunk = self.serial_service.rx_queue.get_nowait()
                except queue.Empty:
                    break
                if chunk.data == b"\n":
                    receive_fragments.append("\n")
                    continue
                self.total_rx_bytes += len(chunk.data)
                processed_bytes += len(chunk.data)
                processed_chunks += 1
                if not self.wave_running:
                    self.logger.log("RX", chunk.data.hex(" ").upper())
                receive_fragments.append(self.format_incoming(chunk.timestamp, chunk.data))
                try:
                    frames = self.frame_parser.feed(chunk.data)
                except Exception as exc:
                    self.logger.log("ERROR", f"frame parser error: {exc}")
                    self.frame_parser = FrameParser()
                    frames = []
                for frame in frames:
                    self._log_protocol_frame(frame)
                    try:
                        self.handle_protocol_frame(frame)
                    except Exception as exc:
                        self.logger.log(
                            "ERROR",
                            "handle frame failed "
                            f"cmd_set=0x{frame.cmd_set:02X} cmd_word=0x{frame.cmd_word:02X} "
                            f"is_ack={frame.is_ack} err={exc}",
                        )
                updated = True
                if self.save_handle:
                    save_buffer.extend(chunk.data)
            if receive_fragments:
                self.monitor_tab.append_receive_batch(
                    receive_fragments,
                    source="rx",
                    ensure_separate_line=self.monitor_tab.receive_hex_enabled(),
                )
            if save_buffer and self.save_handle:
                self.save_handle.write(save_buffer)
                now = time.monotonic()
                if now - self.last_save_flush_at >= SAVE_FLUSH_INTERVAL_SECONDS:
                    self.save_handle.flush()
                    self.last_save_flush_at = now
            if updated:
                self.rx_count_var.set(self.i18n.format_text("Receive: {count} bytes", count=self.total_rx_bytes))
            next_delay = 1 if not self.serial_service.rx_queue.empty() else POLL_INTERVAL_MS
        except Exception as exc:
            self.logger.log("ERROR", f"process incoming loop failed: {exc}")
            next_delay = POLL_INTERVAL_MS
        finally:
            self.after(next_delay, self.process_incoming_data)

    def _log_protocol_frame(self, frame: ProtocolFrame) -> None:
        if frame.cmd_set == 0x01 and frame.cmd_word == 0x07:
            payload = frame.payload
            if len(payload) >= 6:
                name_len = payload[0]
                type_id = payload[1]
                data_raw = int.from_bytes(payload[2:6], "little")
                if name_len == 0 and type_id == 0 and data_raw == 0x55555555:
                    self.logger.log("FRAME", "wave batch start")
                elif name_len == 0 and type_id == 0 and data_raw == 0xAAAAAAAA:
                    self.logger.log("FRAME", "wave batch end")
                elif self.wave_debug_frame_budget > 0 and len(payload) >= 6 + name_len:
                    name = payload[6 : 6 + name_len].decode("utf-8", errors="replace")
                    self.logger.log(
                        "FRAME",
                        f"wave sample name={name} type={type_id} raw=0x{data_raw:08X} len={len(payload)}",
                    )
                    self.wave_debug_frame_budget -= 1
            return
        self.logger.log(
            "FRAME",
            f"cmd_set=0x{frame.cmd_set:02X} cmd_word=0x{frame.cmd_word:02X} is_ack={frame.is_ack} "
            f"src=0x{frame.src:02X} dst=0x{frame.dst:02X} len={len(frame.payload)} payload={frame.payload.hex(' ').upper()}",
        )

    def _log_wave_batch_summary(self, reason: str, batch: dict[str, float]) -> None:
        self.wave_batch_counter += 1
        if self.wave_debug_batches_remaining <= 0:
            return
        names = sorted(batch.keys(), key=str.lower)
        selected_names = list(self.wave_tab.selected_names)
        missing_selected = [name for name in selected_names if name not in batch]
        names_preview = ", ".join(names[:10])
        missing_preview = ", ".join(missing_selected[:10]) if missing_selected else "-"
        if len(names) > 10:
            names_preview += f", ...(+{len(names) - 10})"
        if len(missing_selected) > 10:
            missing_preview += f", ...(+{len(missing_selected) - 10})"
        self.logger.log(
            "WAVE",
            f"batch#{self.wave_batch_counter} {reason} size={len(batch)} "
            f"selected={len(selected_names)} missing_selected={len(missing_selected)} "
            f"names=[{names_preview}] missing=[{missing_preview}]",
        )
        self.wave_debug_batches_remaining -= 1

    def handle_protocol_frame(self, frame: ProtocolFrame) -> None:
        if self._handle_home_protocol_frame(frame):
            return
        if frame.cmd_set != 0x01:
            return
        if self._handle_upgrade_protocol_frame(frame):
            return
        if self._handle_factory_mode_protocol_frame(frame):
            return
        if self._handle_black_box_protocol_frame(frame):
            return
        if frame.cmd_word == 0x01 and frame.is_ack == 1 and len(frame.payload) >= 4:
            self.expected_param_count = int.from_bytes(frame.payload[:4], "little")
            self.parameters.clear()
            self.parameter_tab.clear_parameters()
            self.parameter_tab.set_expected_count(0, self.expected_param_count)
            self.parameter_tab.set_message("开始接收参数列表")
            self.sync_wave_selection()
            self.logger.log("PARAM", f"count ack total={self.expected_param_count}")
            return
        if frame.cmd_word == 0x04 and len(frame.payload) >= 15:
            entry = self._parse_parameter_list_item(frame.payload)
            if entry:
                self.parameters[entry.name] = entry
                self.parameter_tab.add_or_update_parameter(entry)
                current_count = len(self.parameters)
                self.parameter_tab.set_expected_count(current_count, self.expected_param_count)
                if current_count % 5 == 0 or current_count == self.expected_param_count:
                    self.parameter_tab.set_message(self.i18n.format_text("已加载参数: {name}", name=entry.name))
                if entry.auto_report and (current_count % 10 == 0 or current_count == self.expected_param_count):
                    self.sync_wave_selection()
                elif current_count == self.expected_param_count:
                    self.sync_wave_selection()
                self.logger.log("PARAM", f"list item name={entry.name} type={entry.type_id} raw={entry.data_raw}")
            return
        if frame.cmd_word == 0x02 and frame.is_ack == 1 and len(frame.payload) >= 6:
            entry = self._parse_single_parameter(frame.payload)
            if entry:
                previous = self.parameters.get(entry.name)
                if previous:
                    entry.min_raw = previous.min_raw
                    entry.max_raw = previous.max_raw
                    entry.status = previous.status
                    entry.auto_report = previous.auto_report
                    entry.important = previous.important
                self.parameters[entry.name] = entry
                self.parameter_tab.update_parameter(entry)
                self.parameter_tab.clear_busy(entry.name)
                self.parameter_tab.clear_invalid(entry.name)
                self.parameter_tab.set_message(
                    self.i18n.format_text(
                        "读取成功: {name} = {value}",
                        name=entry.name,
                        value=format_value(entry.data_raw, entry.type_id),
                    )
                )
                if not entry.is_command:
                    self.wave_tab.update_latest_value(entry.name, format_value(entry.data_raw, entry.type_id))
                self.logger.log("PARAM", f"read ack name={entry.name} raw={entry.data_raw}")
            return
        if frame.cmd_word == 0x03 and frame.is_ack == 1 and len(frame.payload) >= 14:
            entry = self._parse_write_response(frame.payload)
            if entry:
                self.parameters[entry.name] = entry
                self.parameter_tab.update_parameter(entry)
                self.parameter_tab.clear_busy(entry.name)
                self.parameter_tab.clear_invalid(entry.name)
                self.parameter_tab.set_message(
                    self.i18n.format_text(
                        "写入成功: {name} = {value}",
                        name=entry.name,
                        value=format_value(entry.data_raw, entry.type_id),
                    )
                )
                if not entry.is_command:
                    self.wave_tab.update_latest_value(entry.name, format_value(entry.data_raw, entry.type_id))
                self.logger.log("PARAM", f"write ack name={entry.name} raw={entry.data_raw}")
            return
        if frame.cmd_word == 0x05 and frame.is_ack == 1:
            self.parameter_tab.set_message("波形勾选状态已更新")
            self.sync_wave_selection()
            self.logger.log("WAVE", "auto report select ack")
            return
        if frame.cmd_word == 0x06 and frame.is_ack == 1 and len(frame.payload) >= 4:
            self.wave_report_period_ms = int.from_bytes(frame.payload[:4], "little")
            self.wave_tab.set_period(self.wave_report_period_ms)
            self.logger.log("WAVE", f"period ack {self.wave_report_period_ms}ms")
            return
        if frame.cmd_word == 0x0C and frame.is_ack == 1:
            self.wave_tab.set_running(self.wave_running)
            self.logger.log("WAVE", f"run ack running={self.wave_running}")
            return
        if frame.cmd_word == 0x07:
            if time.monotonic() < self.ignore_wave_frames_until:
                return
            self._handle_wave_report_payload(frame.payload)

    def _handle_home_protocol_frame(self, frame: ProtocolFrame) -> bool:
        if frame.cmd_set != 0x02:
            return False
        if frame.cmd_word == 0x02 and frame.is_ack == 0:
            info = self._parse_pcs_home_payload(frame.payload)
            if info is None:
                self.logger.log("WARN", f"pcs home payload invalid len={len(frame.payload)}")
                return True
            self.pending_home_info = info
            self.pending_home_fault_log = self._format_fault_log(info["fault"])
            self.pending_home_warning_log = self._format_warning_log(info["warning"])
            self._schedule_home_refresh()
            self.logger.log(
                "HOME",
                "pcs update "
                f"pv={info['mppt_pwr']:.3f}W grid={info['ac_pwr_grid']:.3f}W inv={info['ac_pwr_inv']:.3f}W "
                f"bat={info['bat_pwr']:.3f}W fault=0x{info['fault']:08X} warning=0x{info['warning']:08X}",
            )
            return True
        if frame.cmd_word == 0x01 and frame.is_ack == 1 and len(frame.payload) >= 4:
            ac_out_enable_trig, ac_out_disable_trig, ac_out_rms, ac_out_freq = frame.payload[:4]
            self.home_tab.apply_inv_cfg_ack(
                ac_out_enable_trig=ac_out_enable_trig,
                ac_out_disable_trig=ac_out_disable_trig,
                ac_out_rms=ac_out_rms,
                ac_out_freq=ac_out_freq,
            )
            self.logger.log(
                "HOME",
                "inv cfg ack "
                f"enable=0x{ac_out_enable_trig:02X} disable=0x{ac_out_disable_trig:02X} "
                f"rms=0x{ac_out_rms:02X} freq=0x{ac_out_freq:02X}",
            )
            return True
        return False

    def _handle_black_box_protocol_frame(self, frame: ProtocolFrame) -> bool:
        if frame.cmd_set != CMD_SET_BLACK_BOX:
            return False

        if frame.cmd_word == CMD_WORD_BLACK_BOX_RANGE_QUERY and frame.is_ack == 1:
            ack = parse_black_box_range_query_ack(frame.payload)
            self.black_box_tab.set_query_ack(
                accepted=int(ack["accepted"]),
                start_offset=int(ack["start_offset"]),
                read_length=int(ack["read_length"]),
            )
            self.logger.log(
                "BLACKBOX",
                "query ack "
                f"accepted={ack['accepted']} start=0x{int(ack['start_offset']):06X} "
                f"length=0x{int(ack['read_length']):X}",
            )
            return True

        if frame.cmd_word == CMD_WORD_BLACK_BOX_HEADER and frame.is_ack == 0:
            header_text = parse_black_box_header_payload(frame.payload)
            self.black_box_tab.set_header(header_text)
            self.logger.log("BLACKBOX", f"header {header_text!r}")
            return True

        if frame.cmd_word == CMD_WORD_BLACK_BOX_ROW and frame.is_ack == 0:
            row = parse_black_box_row_payload(frame.payload)
            self.black_box_tab.add_row(
                row_text=str(row["row_text"]),
                record_offset=int(row["record_offset"]),
            )
            self.logger.log(
                "BLACKBOX",
                f"row offset=0x{int(row['record_offset']):06X} text={str(row['row_text'])!r}",
            )
            return True

        if frame.cmd_word == CMD_WORD_BLACK_BOX_COMPLETE and frame.is_ack == 0:
            summary = parse_black_box_complete_payload(frame.payload)
            self.black_box_tab.finish_query(
                start_offset=int(summary["start_offset"]),
                end_offset=int(summary["end_offset"]),
                scanned_bytes=int(summary["scanned_bytes"]),
                row_count=int(summary["row_count"]),
                has_more=int(summary["has_more"]),
            )
            self.logger.log(
                "BLACKBOX",
                "complete "
                f"start=0x{int(summary['start_offset']):06X} end=0x{int(summary['end_offset']):06X} "
                f"scanned={summary['scanned_bytes']} rows={summary['row_count']} has_more={summary['has_more']}",
            )
            return True

        return False

    def _handle_factory_mode_protocol_frame(self, frame: ProtocolFrame) -> bool:
        if frame.cmd_word in {CMD_WORD_FACTORY_CALI_READ, CMD_WORD_FACTORY_CALI_WRITE} and frame.is_ack == 1:
            try:
                cali_info = parse_factory_cali_payload(frame.payload)
            except ValueError as exc:
                self.logger.log("ERROR", f"factory calibration payload parse failed: {exc}")
                self.factory_mode_tab.set_cali_status("Calibration response error", str(exc))
                return True

            self.factory_cali_snapshot = cali_info
            cali_id = int(cali_info["cali_id"])
            gain = float(cali_info["gain"])
            bias = float(cali_info["bias"])
            self.factory_mode_tab.set_cali_values(cali_id=cali_id, gain=gain, bias=bias)
            if frame.cmd_word == CMD_WORD_FACTORY_CALI_READ:
                status = "Calibration read successfully"
                detail = f"Device returned ID={cali_id}, gain={gain:.6g}, offset={bias:.6g}."
            else:
                status = "Calibration written successfully"
                detail = f"Device acknowledged ID={cali_id}, gain={gain:.6g}, offset={bias:.6g}."
            self.factory_mode_tab.set_cali_status(status, detail)
            self.logger.log(
                "FACTORY",
                f"rx cali cmd_word=0x{frame.cmd_word:02X} id={cali_id} gain={gain:.6g} bias={bias:.6g}",
            )
            return True

        if frame.cmd_word == CMD_WORD_FACTORY_CALI_SAVE and frame.is_ack == 1:
            self.factory_mode_tab.set_cali_status("Calibration save acknowledged", "The device acknowledged the calibration save command.")
            self.logger.log("FACTORY", "rx calibration save ack")
            return True

        if frame.cmd_word not in {CMD_WORD_FACTORY_TIME_QUERY, CMD_WORD_FACTORY_TIME_WRITE}:
            return False
        if frame.is_ack != 1:
            return False

        try:
            factory_time = parse_factory_time_payload(frame.payload)
        except ValueError as exc:
            self.logger.log("ERROR", f"factory mode payload parse failed: {exc}")
            self.factory_mode_tab.set_status("Factory mode response error", str(exc))
            return True

        self.factory_time_snapshot = factory_time
        unix_time_utc = int(factory_time["unix_time_utc"])
        timezone_half_hour = int(factory_time["timezone_half_hour"])
        timezone_text = format_timezone_label(timezone_half_hour)
        formatted_time = format_factory_time_string(unix_time_utc, timezone_half_hour)

        self.factory_mode_tab.set_device_time(
            formatted_time=formatted_time,
            unix_time_utc=unix_time_utc,
            timezone_text=timezone_text,
        )
        self.factory_mode_tab.set_timezone_input(timezone_text)

        if frame.cmd_word == CMD_WORD_FACTORY_TIME_QUERY:
            status = "Device time read successfully"
            detail = "The device returned its current Unix UTC time and timezone."
        else:
            status = "Factory time settings applied"
            detail = "The device acknowledged the new Unix UTC time and timezone."

        self.factory_mode_tab.set_status(status, detail)
        self.logger.log(
            "FACTORY",
            f"rx cmd_word=0x{frame.cmd_word:02X} unix={unix_time_utc} timezone_half_hour={timezone_half_hour} formatted={formatted_time}",
        )
        return True

    def _schedule_home_refresh(self) -> None:
        if self.home_refresh_job is not None:
            return
        self.home_refresh_job = self.after(HOME_REFRESH_INTERVAL_MS, self._flush_home_refresh)

    def _flush_home_refresh(self) -> None:
        self.home_refresh_job = None
        info = self.pending_home_info
        if info is None:
            return
        fault_log = self.pending_home_fault_log or self._format_fault_log(None)
        warning_log = self.pending_home_warning_log or self._format_warning_log(None)
        self.pending_home_info = None
        self.pending_home_fault_log = None
        self.pending_home_warning_log = None
        self.home_tab.update_pcs_info(**info)
        self.home_tab.set_fault_log(fault_log)
        self.home_tab.set_warning_log(warning_log)

    def _parse_pcs_home_payload(self, payload: bytes) -> dict[str, float | int] | None:
        expected_size = struct.calcsize("<15fBBIII5f")
        if len(payload) == 0:
            return None

        offset = 0

        def read(fmt: str):
            nonlocal offset
            size = struct.calcsize(fmt)
            if offset + size > min(len(payload), expected_size):
                return None
            value = struct.unpack_from(fmt, payload, offset)[0]
            offset += size
            return value

        return {
            "mppt_vin": read("<f"),
            "mppt_iin": read("<f"),
            "mppt_pwr": read("<f"),
            "ac_v_grid": read("<f"),
            "ac_i_grid": read("<f"),
            "ac_freq_grid": read("<f"),
            "ac_pwr_grid": read("<f"),
            "ac_v_inv": read("<f"),
            "ac_i_inv": read("<f"),
            "ac_pwr_inv": read("<f"),
            "ac_freq_inv": read("<f"),
            "pfc_temp": read("<f"),
            "llc_temp1": read("<f"),
            "llc_temp2": read("<f"),
            "mppt_temp": read("<f"),
            "fan_sta": read("<B"),
            "rly_sta": read("<B"),
            "protect": read("<I"),
            "fault": read("<I"),
            "warning": read("<I"),
            "bat_volt": read("<f"),
            "bat_curr": read("<f"),
            "bat_pwr": read("<f"),
            "bat_temp": read("<f"),
            "soc": read("<f"),
        }

    def _format_fault_log(self, fault: int | None) -> str:
        fault_text = f"0x{fault:08X}" if fault is not None else "--"
        lines = [self.i18n.format_text("故障信息: {fault}", fault=fault_text)]
        active = self._active_bits(fault, FAULT_MESSAGES)
        if active:
            lines.append("")
            lines.extend(active)
        else:
            lines.append("")
            lines.append(self.i18n.translate_text("当前无故障" if fault is not None else "故障数据未上报"))
        return "\n".join(lines)

    def _format_warning_log(self, warning: int | None) -> str:
        warning_text = f"0x{warning:08X}" if warning is not None else "--"
        lines = [self.i18n.format_text("告警信息: {warning}", warning=warning_text)]
        active = self._active_bits(warning, WARNING_MESSAGES)
        if active:
            lines.append("")
            lines.extend(active)
        else:
            lines.append("")
            lines.append(self.i18n.translate_text("当前无告警" if warning is not None else "告警数据未上报"))
        return "\n".join(lines)

    def _active_bits(self, value: int | None, mapping: dict[int, str]) -> list[str]:
        if value is None:
            return []
        lines: list[str] = []
        for bit, message in mapping.items():
            if value & (1 << bit):
                lines.append(self.i18n.format_text("代码 {bit}: {message}", bit=bit, message=self.i18n.translate_text(message)))
        return lines

    def request_enable_ac_output(self) -> None:
        self._send_home_inv_cfg(ac_out_enable_trig=1, ac_out_disable_trig=0xFF, ac_out_rms=0xFF, ac_out_freq=0xFF)

    def request_disable_ac_output(self) -> None:
        self._send_home_inv_cfg(ac_out_enable_trig=0xFF, ac_out_disable_trig=1, ac_out_rms=0xFF, ac_out_freq=0xFF)

    def send_home_inv_cfg(self) -> None:
        rms, freq = self.home_tab.get_selected_inv_cfg()
        self._send_home_inv_cfg(ac_out_enable_trig=0xFF, ac_out_disable_trig=0xFF, ac_out_rms=rms, ac_out_freq=freq)

    def request_home_inv_cfg(self) -> None:
        self._send_home_inv_cfg(ac_out_enable_trig=0xFF, ac_out_disable_trig=0xFF, ac_out_rms=0xFF, ac_out_freq=0xFF)

    def _send_home_inv_cfg(self, *, ac_out_enable_trig: int, ac_out_disable_trig: int, ac_out_rms: int, ac_out_freq: int) -> None:
        if not self.serial_service.is_open():
            self.set_status("Open the serial port first.", error=True)
            return
        payload = bytes([ac_out_enable_trig, ac_out_disable_trig, ac_out_rms, ac_out_freq])
        self.send_protocol_frame(cmd_set=0x02, cmd_word=0x01, payload=payload)
        self.logger.log(
            "HOME",
            "send inv cfg "
            f"payload={payload.hex(' ').upper()}",
        )

    def _handle_upgrade_protocol_frame(self, frame: ProtocolFrame) -> bool:
        if frame.is_ack != 1:
            return False

        if frame.cmd_word == CMD_WORD_FIRMWARE_VERSION_QUERY:
            try:
                version_info = parse_firmware_version_ack(frame.payload)
            except ValueError as exc:
                self.upgrade_tab.set_status("Device version query failed", str(exc), error_code="0x17_LEN")
                self.upgrade_tab.append_log(f"RX 0x17 ACK error <- {exc}")
                return True

            source_module = module_name(frame.src)
            version_text = str(version_info["version_text"])
            self.upgrade_tab.set_device_version(version_text)
            self.upgrade_tab.set_status(
                "Device version received",
                f"{source_module} firmware version: {version_text}",
                error_code="-",
            )
            self.upgrade_tab.append_log(
                f"RX 0x17 ACK <- {source_module} firmware version={version_text} raw=0x{int(version_info['version']):08X}"
            )
            return True

        session = self.update_session
        if session is None:
            return False
        if frame.cmd_word not in {
            CMD_WORD_UPDATE_INFO,
            CMD_WORD_UPDATE_READY,
            CMD_WORD_UPDATE_FW,
            CMD_WORD_UPDATE_END,
            CMD_WORD_LLC_PFC_UPGRADE_PROGRESS_QUERY,
        }:
            return False

        session.timeout_error_since = None

        if frame.cmd_word == CMD_WORD_UPDATE_INFO and session.stage == "wait_info_ack":
            if len(frame.payload) < 3:
                self._fail_upgrade("Upgrade failed", "Invalid 0x08 ACK length.", "0x08_LEN")
                return True
            allow_update = frame.payload[0]
            reject_reason = int.from_bytes(frame.payload[1:3], "little")
            self.upgrade_tab.append_log(
                f"RX 0x08 ACK <- allow_update={allow_update} reject_reason=0x{reject_reason:04X}"
            )
            if allow_update == 1:
                self.upgrade_tab.append_log("0x08 ACK allows the upgrade")
                self._send_upgrade_ready()
            elif allow_update == 2:
                self._fail_upgrade(
                    "Upgrade failed",
                    f"0x08 rejected the upgrade: {describe_reject_reason(reject_reason)}",
                    f"0x08:{reject_reason:04X}",
                )
            else:
                self._fail_upgrade("Upgrade failed", "0x08 returned an invalid allow_update value.", "0x08_ACK")
            return True

        if frame.cmd_word == CMD_WORD_UPDATE_READY and session.stage == "wait_ready_ack":
            if len(frame.payload) < 1:
                self._fail_upgrade("Upgrade failed", "Invalid 0x09 ACK length.", "0x09_LEN")
                return True
            self.upgrade_tab.append_log(f"RX 0x09 ACK <- ready={frame.payload[0]}")
            if frame.payload[0] == 1:
                self.upgrade_tab.append_log("0x09 returned ready=1, start sending firmware packets")
                self._send_upgrade_packet()
            else:
                self.upgrade_tab.append_log("0x09 returned ready=0, keep waiting for the bootloader")
                session.last_tx_at = time.monotonic()
                self._schedule_update_tick()
            return True

        if frame.cmd_word == CMD_WORD_UPDATE_FW and session.stage == "wait_packet_ack":
            if len(frame.payload) < 1:
                self._fail_upgrade("Upgrade failed", "Invalid 0x0A ACK length.", "0x0A_LEN")
                return True
            ack_offset = int.from_bytes(frame.payload[1:5], "little") if len(frame.payload) >= 5 else session.current_packet_offset
            self.upgrade_tab.append_log(
                f"RX 0x0A ACK <- data_is_ok={frame.payload[0]} offset={ack_offset}"
            )
            if len(frame.payload) >= 5:
                packet_offset = ack_offset
                if packet_offset != session.current_packet_offset:
                    self.upgrade_tab.append_log(
                        f"Ignore 0x0A ACK with offset mismatch: ack={packet_offset}, expect={session.current_packet_offset}"
                    )
                    return True
            if frame.payload[0] == 1:
                session.data_error_since = None
                actual_len = min(session.packet_size, len(session.image.data) - session.current_packet_offset)
                session.offset = session.current_packet_offset + actual_len
                self.upgrade_tab.append_log(
                    f"Packet confirmed offset={session.current_packet_offset} len={actual_len} -> acked {session.offset}/{len(session.image.data)}"
                )
                if session.offset >= len(session.image.data):
                    self.upgrade_tab.append_log("Last firmware packet confirmed, send the end packet")
                    self._send_upgrade_end()
                else:
                    self._send_upgrade_packet()
            else:
                now = time.monotonic()
                if session.data_error_since is None:
                    session.data_error_since = now
                elif now - session.data_error_since >= 10.0:
                    self._fail_upgrade("Upgrade failed", "Data errors persisted for more than 10 seconds.", "0x0A_DATA")
                    return True
                self.upgrade_tab.append_log(f"0x0A returned data_is_ok=0, resend offset={session.current_packet_offset}")
                session.offset = session.current_packet_offset
                self._send_upgrade_packet(retry=True)
            return True

        if frame.cmd_word == CMD_WORD_UPDATE_END and session.stage == "wait_end_ack":
            if len(frame.payload) < 1:
                self._fail_upgrade("Upgrade failed", "Invalid 0x0B ACK length.", "0x0B_LEN")
                return True
            self.upgrade_tab.append_log(f"RX 0x0B ACK <- success_flg={frame.payload[0]}")
            if frame.payload[0] == 1:
                if session.image.footer.module_id == 0x03:
                    self.upgrade_tab.append_log("0x0B ACK accepted. Switch to LLC -> PFC forward-progress polling.")
                    self.upgrade_tab.set_forward_progress(
                        status="Waiting for LLC -> PFC forward progress",
                        detail="The main download to LLC has finished. Polling 0x01/0x0D now.",
                        forwarded_bytes=0,
                        total_bytes=len(session.image.data),
                        progress_permille=0,
                    )
                    self._send_llc_pfc_upgrade_progress_query()
                elif session.image.footer.module_id == 0x01:
                    detail = "Upgrade completed. LLC will reboot and continue the APP flow."
                    self._complete_upgrade(detail)
                else:
                    detail = "Upgrade completed. The device will reboot and jump to the new APP."
                    self._complete_upgrade(detail)
            else:
                self._fail_upgrade("Upgrade failed", "0x0B returned success_flg=0.", "0x0B_FAIL")
            return True

        if frame.cmd_word == CMD_WORD_LLC_PFC_UPGRADE_PROGRESS_QUERY and session.stage in {"wait_forward_progress_ack", "poll_forward_progress"}:
            try:
                progress = parse_llc_pfc_upgrade_progress_ack(frame.payload)
            except ValueError as exc:
                self._fail_upgrade("Upgrade failed", str(exc), "0x0D_LEN")
                return True

            session.llc_forward_progress_sent_bytes = int(progress["forwarded_bytes"])
            session.llc_forward_progress_total_bytes = int(progress["total_bytes"])
            session.llc_forward_progress_permille = int(progress["progress_permille"])

            source_module = module_name(int(progress["source_module_id"]))
            target_module = module_name(int(progress["target_module_id"]))
            detail = (
                f"stage={progress['stage_name']} result={progress['result_name']} "
                f"offset={progress['packet_offset']} len={progress['packet_length']} "
                f"error={progress['error_name']}"
            )
            self.upgrade_tab.append_log(
                f"RX 0x0D <- {source_module} -> {target_module} "
                f"stage={progress['stage_name']} result={progress['result_name']} "
                f"forwarded={progress['forwarded_bytes']}/{progress['total_bytes']} "
                f"offset={progress['packet_offset']} len={progress['packet_length']} "
                f"error={progress['error_name']}"
            )
            self.upgrade_tab.set_forward_progress(
                status=f"LLC -> PFC: {progress['stage_name']}",
                detail=detail,
                forwarded_bytes=int(progress["forwarded_bytes"]),
                total_bytes=int(progress["total_bytes"]),
                progress_permille=int(progress["progress_permille"]),
            )
            result_name = str(progress["result_name"])
            stage_name = str(progress["stage_name"])
            error_name = describe_llc_pfc_upgrade_error(int(progress["error_code"]))
            if result_name == "success" or stage_name == "done":
                self._complete_upgrade("Upgrade completed. LLC finished forwarding the PFC firmware.")
            elif result_name == "failed" or stage_name == "failed":
                self._fail_upgrade(
                    "Upgrade failed",
                    f"LLC reported PFC forwarding failure: {error_name}",
                    f"0x0D:{int(progress['error_code']):04X}",
                )
            else:
                session.stage = "poll_forward_progress"
                session.last_tx_at = time.monotonic()
                self.upgrade_tab.set_status(
                    "Upgrade in progress",
                    "Waiting for the next LLC -> PFC forward-progress poll.",
                    error_code="-",
                )
                self._schedule_update_tick()
            return True

        return False

    def _handle_wave_report_payload(self, payload: bytes) -> None:
        if len(payload) < 6:
            return
        name_len = payload[0]
        type_id = payload[1]
        data_raw = int.from_bytes(payload[2:6], "little")
        if name_len == 0 and type_id == 0 and data_raw == 0x55555555:
            if self.wave_batch_open and self.pending_wave_batch:
                self.wave_tab.append_batch(dict(self.pending_wave_batch), batch_time=time.time())
                self._log_wave_batch_summary("flushed-before-nested-start", dict(self.pending_wave_batch))
                if self.wave_debug_batches_remaining > 0:
                    self.logger.log("WAVE", f"nested batch start, flushed partial batch size={len(self.pending_wave_batch)}")
            self.pending_wave_batch = {}
            self.wave_batch_open = True
            if self.wave_debug_batches_remaining > 0:
                self.logger.log("WAVE", "batch start")
            return
        if name_len == 0 and type_id == 0 and data_raw == 0xAAAAAAAA:
            if self.pending_wave_batch:
                self.wave_tab.append_batch(dict(self.pending_wave_batch), batch_time=time.time())
                self._log_wave_batch_summary("batch-end", dict(self.pending_wave_batch))
                if self.wave_debug_batches_remaining > 0:
                    self.logger.log("WAVE", f"batch end size={len(self.pending_wave_batch)}")
                self.pending_wave_batch.clear()
            elif not self.wave_batch_open and self.wave_debug_batches_remaining > 0:
                self.logger.log("WAVE", "stray batch end ignored")
            self.wave_batch_open = False
            return
        if len(payload) < 6 + name_len:
            self.logger.log("WARN", f"wave payload too short len={len(payload)} name_len={name_len}")
            return
        name = payload[6 : 6 + name_len].decode("utf-8", errors="replace")
        entry = self.parameters.get(name)
        if entry:
            entry.data_raw = data_raw
            if not entry.is_command:
                self.wave_tab.update_latest_value(name, format_value(entry.data_raw, entry.type_id))
        if type_id == 7:
            return
        value = u32_to_value(data_raw, type_id)
        if isinstance(value, (int, float)):
            numeric_value = float(value)
            if self.wave_batch_open:
                self.pending_wave_batch[name] = numeric_value
            else:
                self.wave_tab.append_batch({name: numeric_value}, batch_time=time.time())
                if self.wave_debug_frame_budget > 0:
                    self.logger.log("WAVE", f"single sample name={name} value={numeric_value}")

    def _parse_parameter_list_item(self, payload: bytes) -> ParameterEntry | None:
        name_len = payload[0]
        if len(payload) < 15 + name_len:
            self.logger.log("WARN", f"list item payload too short len={len(payload)} name_len={name_len}")
            return None
        type_id = payload[1]
        data = int.from_bytes(payload[2:6], "little")
        data_max = int.from_bytes(payload[6:10], "little")
        data_min = int.from_bytes(payload[10:14], "little")
        status = payload[14]
        name = payload[15 : 15 + name_len].decode("utf-8", errors="replace")
        return ParameterEntry(name=name, type_id=type_id, data_raw=data, min_raw=data_min, max_raw=data_max, status=status, auto_report=bool(status & 0x01), important=bool(status & 0x02), dirty=False)

    def _parse_single_parameter(self, payload: bytes) -> ParameterEntry | None:
        name_len = payload[0]
        if len(payload) < 6 + name_len:
            self.logger.log("WARN", f"single read payload too short len={len(payload)} name_len={name_len}")
            return None
        type_id = payload[1]
        data = int.from_bytes(payload[2:6], "little")
        name = payload[6 : 6 + name_len].decode("utf-8", errors="replace")
        previous = self.parameters.get(name)
        return ParameterEntry(name=name, type_id=type_id, data_raw=data, min_raw=previous.min_raw if previous else 0, max_raw=previous.max_raw if previous else 0, status=previous.status if previous else 0, auto_report=previous.auto_report if previous else False, important=previous.important if previous else False, dirty=False)

    def _parse_write_response(self, payload: bytes) -> ParameterEntry | None:
        name_len = payload[0]
        if len(payload) < 14 + name_len:
            self.logger.log("WARN", f"write payload too short len={len(payload)} name_len={name_len}")
            return None
        type_id = payload[1]
        data = int.from_bytes(payload[2:6], "little")
        data_max = int.from_bytes(payload[6:10], "little")
        data_min = int.from_bytes(payload[10:14], "little")
        name = payload[14 : 14 + name_len].decode("utf-8", errors="replace")
        previous = self.parameters.get(name)
        return ParameterEntry(name=name, type_id=type_id, data_raw=data, min_raw=data_min, max_raw=data_max, status=previous.status if previous else 0, auto_report=previous.auto_report if previous else False, important=previous.important if previous else False, dirty=False)

    def request_parameter_list(self) -> None:
        if not self.serial_service.is_open():
            self.set_status("Open the serial port first.", error=True)
            return
        if self.parameter_list_request_job is not None:
            self.after_cancel(self.parameter_list_request_job)
            self.parameter_list_request_job = None

        self.expected_param_count = 0
        self.parameters.clear()
        self.parameter_tab.clear_parameters()
        self.parameter_tab.set_message("正在停止波形上报并准备读取参数列表")
        self.sync_wave_selection()
        self.wave_running = False
        self.wave_tab.set_running(False)
        self.ignore_wave_frames_until = time.monotonic() + 0.8
        self.logger.log("PARAM", "auto stop wave upload before reading parameter list")
        self.send_protocol_frame(cmd_set=0x01, cmd_word=0x0C, payload=bytes([0]))
        self.parameter_list_request_job = self.after(180, self._send_parameter_list_request)

    def _send_parameter_list_request(self) -> None:
        self.parameter_list_request_job = None
        self.parameter_tab.set_message("已发送读取参数列表命令")
        self.logger.log("PARAM", "send read parameter list request")
        self.send_protocol_frame(cmd_set=0x01, cmd_word=0x01, payload=b"")

    def request_black_box_range_query(self) -> None:
        if not self.serial_service.is_open():
            self.set_status("Open the serial port first.", error=True)
            self.black_box_tab.set_status("Cannot start black box query", "Connect the serial port first.")
            return
        try:
            start_offset, read_length = self.black_box_tab.get_query_range()
        except ValueError:
            self.set_status("Black box query range must be an integer.", error=True)
            self.black_box_tab.set_status("Invalid black box query", "Start offset and read length must be valid integers.")
            return
        if start_offset < 0 or read_length <= 0:
            self.set_status("Black box query range is invalid.", error=True)
            self.black_box_tab.set_status("Invalid black box query", "Start offset must be >= 0 and read length must be > 0.")
            return

        self.black_box_tab.begin_query(start_offset=start_offset, read_length=read_length)
        payload = build_black_box_range_query_payload(start_offset, read_length)
        self.logger.log(
            "BLACKBOX",
            f"send range query dst=0x02 d_dst=0x00 start=0x{start_offset:06X} length=0x{read_length:X}",
        )
        self.send_protocol_frame(
            dst=0x02,
            d_dst=0x00,
            cmd_set=CMD_SET_BLACK_BOX,
            cmd_word=CMD_WORD_BLACK_BOX_RANGE_QUERY,
            payload=payload,
        )

    def request_factory_time_read(self) -> None:
        if not self.serial_service.is_open():
            self.set_status("Open the serial port first.", error=True)
            self.factory_mode_tab.set_status("Cannot read device time", "Connect the serial port first.")
            return
        try:
            dst, d_dst = self.factory_mode_tab.get_target_address()
        except ValueError:
            self.set_status("Factory Mode target address must be an integer.", error=True)
            self.factory_mode_tab.set_status("Invalid target address", "Target address and dynamic address must be integers.")
            return

        self.factory_mode_tab.set_status("Reading device time", "Waiting for the device time and timezone response.")
        self.logger.log("FACTORY", f"send time query dst=0x{dst:02X} d_dst=0x{d_dst:02X}")
        self.send_protocol_frame(
            dst=dst,
            d_dst=d_dst,
            cmd_set=CMD_SET_FACTORY_TIME_QUERY,
            cmd_word=CMD_WORD_FACTORY_TIME_QUERY,
            payload=build_factory_time_query_payload(),
        )

    def _send_factory_time_write(self, *, unix_time_utc: int, timezone_half_hour: int, detail: str) -> None:
        try:
            dst, d_dst = self.factory_mode_tab.get_target_address()
        except ValueError:
            self.set_status("Factory Mode target address must be an integer.", error=True)
            self.factory_mode_tab.set_status("Invalid target address", "Target address and dynamic address must be integers.")
            return

        payload = build_factory_time_write_payload(unix_time_utc, timezone_half_hour)
        self.factory_mode_tab.set_status("Applying factory time settings", detail)
        self.logger.log(
            "FACTORY",
            f"send time write dst=0x{dst:02X} d_dst=0x{d_dst:02X} unix={unix_time_utc} timezone_half_hour={timezone_half_hour}",
        )
        self.send_protocol_frame(
            dst=dst,
            d_dst=d_dst,
            cmd_set=CMD_SET_FACTORY_TIME_WRITE,
            cmd_word=CMD_WORD_FACTORY_TIME_WRITE,
            payload=payload,
        )

    def send_factory_current_pc_time(self) -> None:
        if not self.serial_service.is_open():
            self.set_status("Open the serial port first.", error=True)
            self.factory_mode_tab.set_status("Cannot set device time", "Connect the serial port first.")
            return
        try:
            timezone_half_hour = parse_timezone_input(self.factory_mode_tab.get_timezone_text())
        except ValueError as exc:
            self.set_status(str(exc), error=True)
            self.factory_mode_tab.set_status("Invalid timezone", str(exc))
            return

        self._send_factory_time_write(
            unix_time_utc=int(time.time()),
            timezone_half_hour=timezone_half_hour,
            detail="Send the current PC UTC Unix time and timezone to the device.",
        )

    def apply_factory_timezone(self) -> None:
        if not self.serial_service.is_open():
            self.set_status("Open the serial port first.", error=True)
            self.factory_mode_tab.set_status("Cannot apply timezone", "Connect the serial port first.")
            return
        try:
            timezone_half_hour = parse_timezone_input(self.factory_mode_tab.get_timezone_text())
        except ValueError as exc:
            self.set_status(str(exc), error=True)
            self.factory_mode_tab.set_status("Invalid timezone", str(exc))
            return

        unix_time_utc = int(time.time())
        if self.factory_time_snapshot is not None:
            unix_time_utc = int(self.factory_time_snapshot["unix_time_utc"])
        self._send_factory_time_write(
            unix_time_utc=unix_time_utc,
            timezone_half_hour=timezone_half_hour,
            detail="Apply the requested timezone on the device while keeping the current Unix UTC time.",
        )

    def request_factory_cali_read(self) -> None:
        if not self.serial_service.is_open():
            self.set_status("Open the serial port first.", error=True)
            self.factory_mode_tab.set_cali_status("Cannot read calibration", "Connect the serial port first.")
            return
        try:
            dst, d_dst = self.factory_mode_tab.get_cali_target_address()
            cali_id, _, _ = self.factory_mode_tab.get_cali_values()
        except ValueError:
            self.set_status("Calibration destination, ID, gain, and offset must be numeric.", error=True)
            self.factory_mode_tab.set_cali_status("Invalid calibration input", "Destination address and calibration ID must be valid numbers.")
            return

        self.factory_mode_tab.set_cali_status("Reading calibration", f"Requesting the current gain and offset for ID={cali_id}.")
        self.logger.log("FACTORY", f"send cali read dst=0x{dst:02X} d_dst=0x{d_dst:02X} id={cali_id}")
        self.send_protocol_frame(
            dst=dst,
            d_dst=d_dst,
            cmd_set=CMD_SET_FACTORY_CALI_READ,
            cmd_word=CMD_WORD_FACTORY_CALI_READ,
            payload=build_factory_cali_read_payload(cali_id),
        )

    def send_factory_cali_write(self) -> None:
        if not self.serial_service.is_open():
            self.set_status("Open the serial port first.", error=True)
            self.factory_mode_tab.set_cali_status("Cannot write calibration", "Connect the serial port first.")
            return
        try:
            dst, d_dst = self.factory_mode_tab.get_cali_target_address()
            cali_id, gain, bias = self.factory_mode_tab.get_cali_values()
        except ValueError:
            self.set_status("Calibration destination, ID, gain, and offset must be numeric.", error=True)
            self.factory_mode_tab.set_cali_status("Invalid calibration input", "Destination address, ID, gain, and offset must be valid numbers.")
            return

        self.factory_mode_tab.set_cali_status(
            "Writing calibration",
            f"Sending ID={cali_id}, gain={gain:.6g}, offset={bias:.6g} to the device.",
        )
        self.logger.log(
            "FACTORY",
            f"send cali write dst=0x{dst:02X} d_dst=0x{d_dst:02X} id={cali_id} gain={gain:.6g} bias={bias:.6g}",
        )
        self.send_protocol_frame(
            dst=dst,
            d_dst=d_dst,
            cmd_set=CMD_SET_FACTORY_CALI_WRITE,
            cmd_word=CMD_WORD_FACTORY_CALI_WRITE,
            payload=build_factory_cali_write_payload(cali_id, gain, bias),
        )

    def send_factory_cali_save(self) -> None:
        if not self.serial_service.is_open():
            self.set_status("Open the serial port first.", error=True)
            self.factory_mode_tab.set_cali_status("Cannot save calibration", "Connect the serial port first.")
            return
        try:
            dst, d_dst = self.factory_mode_tab.get_cali_target_address()
        except ValueError:
            self.set_status("Calibration destination address must be numeric.", error=True)
            self.factory_mode_tab.set_cali_status("Invalid destination address", "Destination address and dynamic address must be valid integers.")
            return

        self.factory_mode_tab.set_cali_status("Saving calibration", "Requesting the device to store current calibration values.")
        self.logger.log("FACTORY", f"send cali save dst=0x{dst:02X} d_dst=0x{d_dst:02X}")
        self.send_protocol_frame(
            dst=dst,
            d_dst=d_dst,
            cmd_set=CMD_SET_FACTORY_CALI_SAVE,
            cmd_word=CMD_WORD_FACTORY_CALI_SAVE,
            payload=build_factory_cali_save_payload(),
        )

    def request_single_parameter(self, name: str) -> None:
        if not self.serial_service.is_open():
            self.set_status("Open the serial port first.", error=True)
            return
        payload = bytes([len(name.encode("utf-8"))]) + name.encode("utf-8")
        self.parameter_tab.mark_busy(name)
        self.parameter_tab.set_message(self.i18n.format_text("正在读取: {name}", name=name))
        self.logger.log("PARAM", f"send read single name={name}")
        self.send_protocol_frame(cmd_set=0x01, cmd_word=0x02, payload=payload)

    def write_single_parameter(self, name: str) -> None:
        entry = self.parameters.get(name)
        if entry is None:
            return
        if entry.is_command:
            payload = bytes([len(name.encode("utf-8"))]) + (0).to_bytes(4, "little") * 3 + name.encode("utf-8")
            self.parameter_tab.mark_busy(name)
            self.parameter_tab.set_message(self.i18n.format_text("正在执行: {name}", name=name))
            self.logger.log("PARAM", f"send execute command name={name}")
            self.send_protocol_frame(cmd_set=0x01, cmd_word=0x03, payload=payload)
            return
        pending_values = self.parameter_tab.get_pending_display_values(name)
        if pending_values is None:
            return
        pending_value, pending_min, pending_max = pending_values
        try:
            raw_value = value_to_u32(pending_value, entry.type_id)
            min_raw = value_to_u32(pending_min, entry.type_id)
            max_raw = value_to_u32(pending_max, entry.type_id)
            typed_value = u32_to_value(raw_value, entry.type_id)
            min_value = u32_to_value(min_raw, entry.type_id)
            max_value = u32_to_value(max_raw, entry.type_id)
        except ValueError as exc:
            self.parameter_tab.clear_busy(name)
            self.parameter_tab.mark_invalid(name)
            self.parameter_tab.set_message(f"Invalid parameter input: {name}")
            self.set_status(str(exc), error=True)
            self.logger.log("ERROR", f"write value error name={name} err={exc}")
            return
        if isinstance(typed_value, float):
            typed_min = float(min_value)
            typed_max = float(max_value)
            typed_data = float(typed_value)
        else:
            typed_min = int(min_value)
            typed_max = int(max_value)
            typed_data = int(typed_value)

        if typed_min > typed_max:
            self.parameter_tab.clear_busy(name)
            self.parameter_tab.mark_invalid(name)
            self.parameter_tab.set_message(f"Invalid range: {name} min {min_value} > max {max_value}")
            self.set_status(f"Invalid range: {name}", error=True)
            self.logger.log(
                "WARN",
                f"write invalid range name={name} min={min_value} max={max_value}",
            )
            return

        in_range = typed_min <= typed_data <= typed_max
        if not in_range:
            self.parameter_tab.clear_busy(name)
            self.parameter_tab.mark_invalid(name)
            self.parameter_tab.set_message(
                self.i18n.format_text(
                    "写入越界: {name} 需要在 {min_value} 到 {max_value} 之间",
                    name=name,
                    min_value=min_value,
                    max_value=max_value,
                )
            )
            self.set_status(f"Write out of range: {name}", error=True)
            self.logger.log(
                "WARN",
                f"write out of range name={name} value={typed_value} min={min_value} max={max_value}",
            )
            return
        self.parameter_tab.clear_invalid(name)
        payload = (
            bytes([len(name.encode("utf-8"))])
            + raw_value.to_bytes(4, "little")
            + max_raw.to_bytes(4, "little", signed=False)
            + min_raw.to_bytes(4, "little", signed=False)
            + name.encode("utf-8")
        )
        self.parameter_tab.mark_busy(name)
        self.parameter_tab.set_message(self.i18n.format_text("正在写入: {name}", name=name))
        self.logger.log(
            "PARAM",
            f"send write name={name} raw=0x{raw_value:08X} min=0x{min_raw:08X} max=0x{max_raw:08X} "
            f"display={pending_value} display_min={pending_min} display_max={pending_max}",
        )
        self.send_protocol_frame(cmd_set=0x01, cmd_word=0x03, payload=payload)

    def toggle_auto_report(self, name: str, enabled: bool) -> None:
        if not self.serial_service.is_open():
            self.set_status("Open the serial port first.", error=True)
            return
        if self.wave_running:
            self.set_status("Please stop waveform streaming before changing selections.", error=True)
            return
        payload = bytes([len(name.encode("utf-8")), 1 if enabled else 0]) + name.encode("utf-8")
        entry = self.parameters.get(name)
        if entry:
            entry.auto_report = enabled
            self.parameter_tab.update_wave_state(name, enabled)
        self.sync_wave_selection()
        self.parameter_tab.set_message(self.i18n.format_text("已更新波形勾选: {name}", name=name))
        self.logger.log("PARAM", f"toggle auto report name={name} enabled={enabled}")
        self.send_protocol_frame(cmd_set=0x01, cmd_word=0x05, payload=payload)

    def sync_wave_selection(self) -> None:
        names = [name for name, entry in self.parameters.items() if entry.auto_report and not entry.is_command]
        self.wave_tab.set_selected_parameters(sorted(names, key=str.lower))

    def apply_wave_period(self) -> None:
        if not self.serial_service.is_open():
            self.set_status("Open the serial port first.", error=True)
            return
        period_ms = self._get_wave_period_ms()
        if period_ms is None:
            return
        self.wave_report_period_ms = period_ms
        self.logger.log("WAVE", f"send set period {period_ms}ms")
        self.send_protocol_frame(cmd_set=0x01, cmd_word=0x06, payload=period_ms.to_bytes(4, "little"))

    def toggle_wave_run(self) -> None:
        if not self.serial_service.is_open():
            self.set_status("Open the serial port first.", error=True)
            return
        start = not self.wave_running
        if start:
            period_ms = self._get_wave_period_ms()
            if period_ms is None:
                return
            self.wave_report_period_ms = period_ms
            self.logger.log("WAVE", f"send set period before start {period_ms}ms")
            self.send_protocol_frame(cmd_set=0x01, cmd_word=0x06, payload=period_ms.to_bytes(4, "little"))
        self.wave_running = start
        self.wave_tab.set_running(start)
        if start:
            self.pending_wave_batch.clear()
            self.wave_batch_open = False
            self.wave_batch_counter = 0
            self.wave_debug_batches_remaining = 8
            self.wave_debug_frame_budget = 120
            self.logger.log("WAVE", "armed detailed batch capture for first 8 batches")
        else:
            saved_path = self.wave_tab.auto_save_waveform_file(reason="stop stream")
            if saved_path is not None:
                self.logger.log("WAVE", f"auto save on stop -> {saved_path}")
        self.logger.log("WAVE", f"send run toggle start={start}")
        self.send_protocol_frame(cmd_set=0x01, cmd_word=0x0C, payload=bytes([1 if start else 0]))

    def _get_wave_period_ms(self) -> int | None:
        try:
            period_ms = int(self.wave_tab.period_var.get().strip())
        except ValueError:
            self.set_status("Wave period must be an integer.", error=True)
            return None
        if period_ms <= 0:
            self.set_status("Wave period must be greater than 0.", error=True)
            return None
        return period_ms

    def clear_wave_data(self) -> None:
        self.pending_wave_batch.clear()
        self.wave_batch_open = False
        self.wave_tab.clear_plot()
        self.logger.log("WAVE", "clear waveform")

    def send_protocol_frame(
        self,
        *,
        cmd_set: int,
        cmd_word: int,
        payload: bytes,
        dst: int | None = None,
        d_dst: int | None = None,
    ) -> None:
        if dst is None or d_dst is None:
            try:
                dst, d_dst = self.parameter_tab.get_target_address()
            except ValueError:
                self.set_status("模块地址和动态地址必须是整数。", error=True)
                self.logger.log("ERROR", "invalid target address")
                return
        frame = build_frame(dst=dst, d_dst=d_dst, cmd_set=cmd_set, cmd_word=cmd_word, payload=payload)
        self.logger.log("TX", f"dst=0x{dst:02X} d_dst=0x{d_dst:02X} cmd_set=0x{cmd_set:02X} cmd_word=0x{cmd_word:02X} frame={frame.hex(' ').upper()}")
        try:
            sent = self.serial_service.write(frame)
        except serial.SerialException as exc:
            self._handle_serial_error(str(exc))
            return
        self.total_tx_bytes += sent
        self.tx_count_var.set(self.i18n.format_text("Send: {count} bytes", count=self.total_tx_bytes))
        self._echo_sent_payload(frame, hex_mode=self.monitor_tab.send_hex_enabled())

    def format_incoming(self, timestamp: float, data: bytes) -> str:
        prefix = time.strftime("[%H:%M:%S] ", time.localtime(timestamp)) if self.timestamp_var.get() else ""
        display_text = self._format_display_payload(
            data,
            prefix=prefix,
            hex_mode=self.monitor_tab.receive_hex_enabled(),
            pending_hex_bytes=self.pending_rx_hex_bytes,
            repeat_prefix_after_newline=True,
        )
        if not self.monitor_tab.receive_hex_enabled():
            self.pending_rx_hex_bytes.clear()
        return display_text

    def _format_display_payload(
        self,
        payload: bytes,
        *,
        prefix: str,
        hex_mode: bool,
        append_trailing_newline: bool = False,
        pending_hex_bytes: bytearray | None = None,
        repeat_prefix_after_newline: bool = False,
    ) -> str:
        if not payload and not pending_hex_bytes:
            return ""
        if not hex_mode:
            text = f"{prefix}{payload.decode('utf-8', errors='replace')}"
            if append_trailing_newline and text and not text.endswith("\n"):
                text += "\n"
            return text
        return self._format_hex_display_payload(
            payload,
            prefix=prefix,
            append_trailing_newline=append_trailing_newline,
            pending_hex_bytes=pending_hex_bytes,
            repeat_prefix_after_newline=repeat_prefix_after_newline,
        )

    def _format_hex_display_payload(
        self,
        payload: bytes,
        *,
        prefix: str,
        append_trailing_newline: bool,
        pending_hex_bytes: bytearray | None,
        repeat_prefix_after_newline: bool,
    ) -> str:
        if pending_hex_bytes is not None:
            buffered = bytes(pending_hex_bytes) + payload
            pending_hex_bytes.clear()
        else:
            buffered = payload

        if not buffered:
            return ""

        parts: list[str] = [prefix] if prefix else []
        index = 0
        while index < len(buffered):
            byte = buffered[index]
            if byte == 0x0D:
                if index + 1 >= len(buffered):
                    if pending_hex_bytes is not None:
                        pending_hex_bytes.append(byte)
                    break
                if buffered[index + 1] == 0x0A:
                    parts.append("0D 0A\n")
                    if repeat_prefix_after_newline and prefix and index + 2 < len(buffered):
                        parts.append(prefix)
                    index += 2
                    continue
            parts.append(f"{byte:02X} ")
            index += 1

        text = "".join(parts)
        if append_trailing_newline and text and not text.endswith("\n"):
            text += "\n"
        return text

    def clear_receive_area(self) -> None:
        self.monitor_tab.clear_receive()
        self.logger.log("UI", "clear monitor receive area")

    def save_receive_snapshot(self) -> None:
        self.paths.exports_dir.mkdir(parents=True, exist_ok=True)
        path = filedialog.asksaveasfilename(
            title="Save Receive Data",
            initialdir=str(self.paths.exports_dir),
            defaultextension=".txt",
            filetypes=[("Text Files", "*.txt"), (self.i18n.translate_text("All Files"), "*.*")],
        )
        if not path:
            return
        Path(path).write_text(self.monitor_tab.receive_text.get("1.0", "end-1c"), encoding="utf-8")
        self.set_status(f"Saved text to {path}")
        self.logger.log("UI", f"save monitor snapshot -> {path}")

    def on_toggle_save_to_file(self) -> None:
        if self.save_to_file_var.get():
            self.paths.exports_dir.mkdir(parents=True, exist_ok=True)
            path = filedialog.asksaveasfilename(
                title="Select output file",
                initialdir=str(self.paths.exports_dir),
                defaultextension=".bin",
            filetypes=[("Binary Files", "*.bin"), (self.i18n.translate_text("All Files"), "*.*")],
            )
            if not path:
                self.save_to_file_var.set(False)
                return
            self.save_path = Path(path)
            self.save_handle = self.save_path.open("ab")
            self.last_save_flush_at = time.monotonic()
            self.set_status(f"Saving receive data to {self.save_path}")
            self.logger.log("UI", f"start save receive stream -> {self.save_path}")
            return
        if self.save_handle:
            self.save_handle.flush()
            self.save_handle.close()
        self.save_handle = None
        self.save_path = None
        self.set_status("Receive file saving stopped")
        self.logger.log("UI", "stop save receive stream")

    def send_payload(self) -> None:
        if not self.serial_service.is_open():
            self.set_status("Open the serial port first.", error=True)
            return
        raw_text = self.monitor_tab.get_send_text()
        if not raw_text.strip():
            return
        try:
            payload = self.build_send_bytes(raw_text, hex_mode=self.monitor_tab.send_hex_enabled(), append_crlf=self.line_mode_var.get())
            self.logger.log("TX", f"manual send frame={payload.hex(' ').upper()}")
            sent = self.serial_service.write(payload)
        except ValueError as exc:
            self.set_status(str(exc), error=True)
            self.logger.log("ERROR", f"manual send parse error: {exc}")
            return
        except serial.SerialException as exc:
            self._handle_serial_error(str(exc))
            return
        self.total_tx_bytes += sent
        self.tx_count_var.set(self.i18n.format_text("Send: {count} bytes", count=self.total_tx_bytes))
        self._echo_sent_payload(payload, hex_mode=self.monitor_tab.send_hex_enabled())
        self.set_status(f"Sent {sent} byte(s)")

    def send_preset_payload(self, index: int, raw_text: str, hex_mode: bool, append_crlf: bool) -> None:
        if not self.serial_service.is_open():
            self.set_status("Open the serial port first.", error=True)
            return
        if not raw_text.strip():
            self.set_status(self.i18n.format_text("快捷发送 {index} 为空", index=index + 1), error=True)
            return
        try:
            payload = self.build_send_bytes(raw_text, hex_mode=hex_mode, append_crlf=append_crlf)
            self.logger.log("TX", f"preset send index={index + 1} frame={payload.hex(' ').upper()}")
            sent = self.serial_service.write(payload)
        except ValueError as exc:
            self.set_status(str(exc), error=True)
            self.logger.log("ERROR", f"preset send parse error index={index + 1}: {exc}")
            return
        except serial.SerialException as exc:
            self._handle_serial_error(str(exc))
            return
        self.total_tx_bytes += sent
        self.tx_count_var.set(self.i18n.format_text("Send: {count} bytes", count=self.total_tx_bytes))
        self._echo_sent_payload(payload, hex_mode=hex_mode)
        self.set_status(self.i18n.format_text("快捷发送 {index} 已发送 {sent} byte(s)", index=index + 1, sent=sent))

    def build_send_bytes(self, raw_text: str, *, hex_mode: bool, append_crlf: bool) -> bytes:
        if hex_mode:
            tokens = raw_text.replace(",", " ").split()
            if not tokens:
                return b""
            try:
                return bytes(int(token, 16) for token in tokens)
            except ValueError as exc:
                raise ValueError("HEX send format is invalid. Example: 01 03 00 00 FF") from exc
        payload = raw_text.encode("utf-8")
        if append_crlf:
            payload += b"\r\n"
        return payload

    def _echo_sent_payload(self, payload: bytes, *, hex_mode: bool) -> None:
        if not self.display_send_string_var.get() or not payload:
            return
        prefix = time.strftime("[%H:%M:%S] ", time.localtime(time.time())) if self.timestamp_var.get() else ""
        display_text = self._format_display_payload(
            payload,
            prefix=prefix,
            hex_mode=hex_mode,
            append_trailing_newline=True,
        )
        self.monitor_tab.append_receive(display_text, "tx", ensure_separate_line=True)

    def on_toggle_auto_send(self) -> None:
        if self.auto_send_var.get():
            self.schedule_auto_send()
        else:
            self.cancel_auto_send()

    def schedule_auto_send(self) -> None:
        self.cancel_auto_send()
        interval_ms = max(int(self._parse_float(self.auto_send_seconds_var.get(), 1.0) * 1000), 100)
        self.auto_send_job = self.after(interval_ms, self._auto_send_tick)
        self.logger.log("UI", f"auto send enabled interval_ms={interval_ms}")

    def _auto_send_tick(self) -> None:
        if self.auto_send_var.get() and self.serial_service.is_open():
            self.send_payload()
            self.schedule_auto_send()
        else:
            self.auto_send_job = None

    def cancel_auto_send(self) -> None:
        if self.auto_send_job:
            self.after_cancel(self.auto_send_job)
            self.auto_send_job = None
            self.logger.log("UI", "auto send cancelled")

    def reset_counters(self) -> None:
        self.total_rx_bytes = 0
        self.total_tx_bytes = 0
        self.rx_count_var.set(self.i18n.format_text("Receive: {count} bytes", count=0))
        self.tx_count_var.set(self.i18n.format_text("Send: {count} bytes", count=0))
        self.set_status(self.i18n.translate_text("Counters reset"))
        self.logger.log("UI", "reset counters")

    def _parse_float(self, value: str, default: float) -> float:
        try:
            return float(value)
        except ValueError:
            return default

    def _current_break_ms(self) -> float:
        return self._parse_float(self.break_ms_var.get(), default=20.0)

    def on_close(self) -> None:
        self.logger.log("APP", "shutdown")
        self.cancel_auto_send()
        self.stop_upgrade("Application closing, upgrade stopped.", user_initiated=False)
        saved_path = self.wave_tab.auto_save_waveform_file(reason="application close")
        if saved_path is not None:
            self.logger.log("WAVE", f"auto save on app close -> {saved_path}")
        self.serial_service.close()
        if self.save_handle:
            self.save_handle.flush()
            self.save_handle.close()
            self.save_handle = None
        self.logger.close()
        self.destroy()


def launch_app() -> None:
    app = SerialDebugAssistant()
    app.mainloop()
