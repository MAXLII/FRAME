from __future__ import annotations

from pathlib import Path
import time
import tkinter as tk
from tkinter import filedialog, ttk

import serial
from serial_debug_assistant.app_paths import ensure_runtime_dirs, get_app_paths, migrate_legacy_data

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
    CMD_WORD_UPDATE_END,
    CMD_WORD_UPDATE_FW,
    CMD_WORD_UPDATE_INFO,
    CMD_WORD_UPDATE_READY,
    build_update_end_payload,
    build_update_info_payload,
    build_update_packet_payload,
    build_update_ready_payload,
    describe_reject_reason,
    format_unix_time,
    format_version,
    load_firmware_image,
    module_name,
)
from serial_debug_assistant.models import FirmwareImage, FirmwareUpdateSession, ParameterEntry, ProtocolFrame
from serial_debug_assistant.protocol import (
    FrameParser,
    build_frame,
    format_value,
    u32_to_value,
    value_to_u32,
)
from serial_debug_assistant.services.serial_service import SerialService
from serial_debug_assistant.ui.monitor_tab import SerialMonitorTab
from serial_debug_assistant.ui.parameter_tab import ParameterReadWriteTab
from serial_debug_assistant.ui.upgrade_tab import UpgradeTab
from serial_debug_assistant.ui.wave_tab import WaveformTab


class SerialDebugAssistant(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry(APP_GEOMETRY)
        self.minsize(APP_MIN_WIDTH, APP_MIN_HEIGHT)
        self.configure(bg="#eef2f7")

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
        self.expected_param_count = 0
        self.parameters: dict[str, ParameterEntry] = {}
        self.wave_running = False
        self.wave_report_period_ms = 300
        self.pending_wave_batch: dict[str, float] = {}
        self.wave_batch_open = False
        self.last_wave_table_sync = 0.0
        self.parameter_list_request_job: str | None = None
        self.ignore_wave_frames_until = 0.0
        self.loaded_firmware: FirmwareImage | None = None
        self.update_session: FirmwareUpdateSession | None = None
        self.update_tick_job: str | None = None

        self.port_var = tk.StringVar()
        self.baud_var = tk.StringVar(value=DEFAULT_BAUD_RATE)
        self.data_bits_var = tk.StringVar(value=DEFAULT_DATA_BITS)
        self.parity_var = tk.StringVar(value=DEFAULT_PARITY)
        self.stop_bits_var = tk.StringVar(value=DEFAULT_STOP_BITS)
        self.status_var = tk.StringVar(value="Ready")
        self.rx_count_var = tk.StringVar(value="Receive: 0 bytes")
        self.tx_count_var = tk.StringVar(value="Send: 0 bytes")
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
        style.configure("App.TFrame", background="#eef2f7")
        style.configure("Panel.TFrame", background="#f8fafc", relief="flat")
        style.configure("Section.TLabelframe", background="#f8fafc", borderwidth=1, relief="solid")
        style.configure(
            "Section.TLabelframe.Label",
            background="#f8fafc",
            foreground="#374151",
            font=("Segoe UI", 10, "bold"),
        )
        style.configure("TLabel", background="#f8fafc", foreground="#1f2937", font=("Segoe UI", 10))
        style.configure("Status.TLabel", background="#eef2f7", foreground="#475569", font=("Segoe UI", 10))
        style.configure("ErrorStatus.TLabel", background="#eef2f7", foreground="#dc2626", font=("Segoe UI", 10))
        style.configure(
            "Header.TLabel",
            background="#eef2f7",
            foreground="#0f172a",
            font=("Segoe UI Semibold", 11),
        )
        style.configure("TButton", font=("Segoe UI", 10), padding=(10, 6))
        style.configure(
            "Accent.TButton",
            foreground="#ffffff",
            background="#2563eb",
            borderwidth=0,
            font=("Segoe UI Semibold", 10),
            padding=(12, 8),
        )
        style.map("Accent.TButton", background=[("active", "#1d4ed8"), ("disabled", "#93c5fd")])
        style.configure("TCheckbutton", background="#f8fafc", font=("Segoe UI", 10))
        style.configure("TCombobox", padding=4)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, style="App.TFrame", padding=14)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=0, minsize=300)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)
        root.rowconfigure(1, weight=0)

        self.sidebar = ttk.Frame(root, style="Panel.TFrame", padding=12)
        self.sidebar.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

        content = ttk.Frame(root, style="Panel.TFrame", padding=0)
        content.grid(row=0, column=1, sticky="nsew")
        content.rowconfigure(0, weight=1)
        content.columnconfigure(0, weight=1)

        self.notebook = ttk.Notebook(content)
        self.notebook.grid(row=0, column=0, sticky="nsew")

        self.monitor_tab = SerialMonitorTab(
            self.notebook,
            on_send=self.send_payload,
            on_send_preset=self.send_preset_payload,
            on_reset_count=self.reset_counters,
            config_path=self.paths.quick_send_config,
            on_layout_change=self._log_monitor_layout,
        )
        self.parameter_tab = ParameterReadWriteTab(
            self.notebook,
            on_read_list=self.request_parameter_list,
            on_read_param=self.request_single_parameter,
            on_write_param=self.write_single_parameter,
            on_toggle_wave=self.toggle_auto_report,
        )
        self.wave_tab = WaveformTab(
            self.notebook,
            on_apply_period=self.apply_wave_period,
            on_toggle_run=self.toggle_wave_run,
            on_clear=self.clear_wave_data,
            export_dir=self.paths.exports_dir,
            on_status=lambda message, is_error=False: self.set_status(message, error=is_error),
        )
        self.upgrade_tab = UpgradeTab(
            self.notebook,
            on_browse=self.load_upgrade_firmware,
            on_start_stop=self.toggle_upgrade,
        )

        self.notebook.add(self.monitor_tab, text="串口调试")
        self.notebook.add(self.parameter_tab, text="参数读写")
        self.notebook.add(self.wave_tab, text="参数波形")
        self.notebook.add(self.upgrade_tab, text="固件升级")
        self.notebook.select(self.monitor_tab)

        footer = ttk.Frame(root, style="App.TFrame")
        footer.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        footer.columnconfigure(0, weight=1)
        footer.columnconfigure(1, weight=1)
        footer.columnconfigure(2, weight=1)
        ttk.Label(footer, textvariable=self.tx_count_var, style="Status.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(footer, textvariable=self.rx_count_var, style="Status.TLabel").grid(row=0, column=1, sticky="w")
        self.status_label = ttk.Label(footer, textvariable=self.status_var, style="Status.TLabel")
        self.status_label.grid(row=0, column=2, sticky="e")

        self._build_sidebar()

    def _build_sidebar(self) -> None:
        self.sidebar.columnconfigure(1, weight=1)
        ttk.Label(self.sidebar, text="Serial Port", style="Header.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

        controls = [
            ("Port Name", self._build_port_selector),
            ("Baud Rate", self._build_baud_selector),
            ("Data Bits", self._build_data_bits_selector),
            ("Parity", self._build_parity_selector),
            ("Stop Bits", self._build_stop_bits_selector),
        ]
        row = 1
        for label, builder in controls:
            ttk.Label(self.sidebar, text=f"{label} :").grid(row=row, column=0, sticky="w", pady=4)
            builder(row)
            row += 1

        self.open_button = ttk.Button(self.sidebar, text="Open", command=self.toggle_connection, style="Accent.TButton")
        self.open_button.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(10, 12))
        row += 1

        receive_frame = ttk.LabelFrame(self.sidebar, text="Receive Settings", style="Section.TLabelframe", padding=10)
        receive_frame.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        receive_frame.columnconfigure(0, weight=1)
        receive_frame.columnconfigure(1, weight=1)
        row += 1

        ttk.Checkbutton(receive_frame, text="Save receiving to file", variable=self.save_to_file_var, command=self.on_toggle_save_to_file).grid(row=0, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Checkbutton(receive_frame, text="HEX display", variable=self.recv_hex_var).grid(row=1, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Checkbutton(receive_frame, text="Auto break frame", variable=self.auto_break_var).grid(row=2, column=0, sticky="w", pady=2)
        ttk.Entry(receive_frame, textvariable=self.break_ms_var, width=8).grid(row=2, column=1, sticky="e", pady=2)
        ttk.Checkbutton(receive_frame, text="Add timestamp", variable=self.timestamp_var).grid(row=3, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Button(receive_frame, text="Clear data", command=self.clear_receive_area).grid(row=4, column=0, sticky="ew", pady=(8, 0), padx=(0, 6))
        ttk.Button(receive_frame, text="Save data", command=self.save_receive_snapshot).grid(row=4, column=1, sticky="ew", pady=(8, 0))

        send_frame = ttk.LabelFrame(self.sidebar, text="Send Settings", style="Section.TLabelframe", padding=10)
        send_frame.grid(row=row, column=0, columnspan=3, sticky="ew")
        send_frame.columnconfigure(0, weight=1)
        send_frame.columnconfigure(1, weight=1)
        ttk.Checkbutton(send_frame, text="HEX send", variable=self.send_hex_var).grid(row=0, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Checkbutton(send_frame, text="Timing send", variable=self.auto_send_var, command=self.on_toggle_auto_send).grid(row=1, column=0, sticky="w", pady=2)
        ttk.Entry(send_frame, textvariable=self.auto_send_seconds_var, width=8).grid(row=1, column=1, sticky="e", pady=2)
        ttk.Checkbutton(send_frame, text="Send line ending (CRLF)", variable=self.line_mode_var).grid(row=2, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Checkbutton(send_frame, text="Display send string", variable=self.display_send_string_var).grid(row=3, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Button(send_frame, text="Refresh Ports", command=self.refresh_ports).grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))

    def _build_port_selector(self, row: int) -> None:
        self.port_combo = ttk.Combobox(self.sidebar, textvariable=self.port_var, state="readonly", width=18)
        self.port_combo.grid(row=row, column=1, sticky="ew", pady=4)
        ttk.Button(self.sidebar, text="R", command=self.refresh_ports, width=3).grid(row=row, column=2, padx=(6, 0), pady=4)

    def _build_baud_selector(self, row: int) -> None:
        ttk.Combobox(self.sidebar, textvariable=self.baud_var, values=BAUD_RATES, width=22).grid(row=row, column=1, columnspan=2, sticky="ew", pady=4)

    def _build_data_bits_selector(self, row: int) -> None:
        ttk.Combobox(self.sidebar, textvariable=self.data_bits_var, values=tuple(BYTE_SIZES.keys()), state="readonly", width=22).grid(row=row, column=1, columnspan=2, sticky="ew", pady=4)

    def _build_parity_selector(self, row: int) -> None:
        ttk.Combobox(self.sidebar, textvariable=self.parity_var, values=tuple(PARITY_OPTIONS.keys()), state="readonly", width=22).grid(row=row, column=1, columnspan=2, sticky="ew", pady=4)

    def _build_stop_bits_selector(self, row: int) -> None:
        ttk.Combobox(self.sidebar, textvariable=self.stop_bits_var, values=tuple(STOP_BITS_OPTIONS.keys()), state="readonly", width=22).grid(row=row, column=1, columnspan=2, sticky="ew", pady=4)

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
        self.set_status(f"Ready | {len(display_values)} port(s) found")
        self.logger.log("PORTS", f"refresh -> {display_values}")

    def toggle_connection(self) -> None:
        if self.serial_service.is_open():
            self.close_connection()
        else:
            self.open_connection()

    def open_connection(self) -> None:
        if not self.port_var.get():
            self.set_status("Please select a serial port.", error=True)
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
        self.pending_wave_batch.clear()
        self.wave_batch_open = False
        self.set_status(f"Connected to {selected_port}")
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
        self.stop_upgrade("串口已断开，升级已停止。", user_initiated=False)
        self.serial_service.close()
        self.upgrade_tab.set_connection_state(False)
        self.set_status("Disconnected")
        self.parameter_tab.set_message("串口已断开")
        self._set_open_button_text("Open")
        self.logger.log("SERIAL", "close")

    def _set_open_button_text(self, text: str) -> None:
        self.open_button.configure(text=text)

    def set_status(self, message: str, *, error: bool = False) -> None:
        self.status_var.set(message)
        if hasattr(self, "status_label"):
            self.status_label.configure(style="ErrorStatus.TLabel" if error else "Status.TLabel")

    def _handle_serial_error(self, exc: str) -> None:
        self.logger.log("ERROR", f"serial error: {exc}")
        self.close_connection()
        self.set_status(f"Serial error: {exc}", error=True)

    def load_upgrade_firmware(self) -> None:
        path = filedialog.askopenfilename(
            title="选择升级固件",
            filetypes=[("Binary Files", "*.bin"), ("All Files", "*.*")],
        )
        if not path:
            return
        try:
            image = load_firmware_image(path)
        except (OSError, ValueError) as exc:
            self.upgrade_tab.set_status("固件加载失败", str(exc), error_code="LOAD")
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
        self.upgrade_tab.append_log(f"已加载固件: {image.path}")
        self.upgrade_tab.append_log(f"版本: {summary['version']}")
        self.upgrade_tab.append_log(f"编译时间: {summary['compile_time']}")
        self.upgrade_tab.append_log(f"模块: {summary['module']}")
        self.upgrade_tab.append_log(f"Footer CRC32: {summary['footer_crc']}")
        if image.footer.module_id == 0x03:
            self.upgrade_tab.append_log("PFC 固件默认下发到 0x02，由 LLC 负责接收并转发升级。")
        for warning in image.warnings:
            self.upgrade_tab.append_log(f"警告: {warning}")

        if not image.footer_crc_ok:
            self.upgrade_tab.set_status("固件已加载，但 footer CRC 校验失败", "请确认打包结果。", error_code="CRC32")
        elif image.warnings:
            self.upgrade_tab.set_status("固件已加载", image.warnings[0], error_code="-")
        else:
            self.upgrade_tab.set_status("固件已加载", "可以开始升级。", error_code="-")

    def toggle_upgrade(self) -> None:
        if self.update_session is not None:
            self.stop_upgrade("用户手动停止升级。", user_initiated=True)
            return
        self.start_upgrade()

    def start_upgrade(self) -> None:
        if not self.serial_service.is_open():
            self.set_status("Open the serial port first.", error=True)
            self.upgrade_tab.set_status("无法开始升级", "请先连接串口。", error_code="SERIAL")
            return
        if self.loaded_firmware is None:
            self.upgrade_tab.set_status("无法开始升级", "请先加载 .bin 固件。", error_code="FILE")
            return
        if not self.loaded_firmware.footer_crc_ok:
            self.upgrade_tab.set_status("无法开始升级", "footer CRC32 校验失败。", error_code="CRC32")
            return
        if self.loaded_firmware.footer.fw_type != 1:
            self.upgrade_tab.set_status("无法开始升级", "仅支持 fw_type=1 的 IAP 固件。", error_code="FW_TYPE")
            return
        try:
            target_addr, target_dynamic_addr = self.upgrade_tab.get_target_address()
        except ValueError:
            self.upgrade_tab.set_status("无法开始升级", "下载地址和动态地址必须是整数。", error_code="ADDR")
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
        self.upgrade_tab.append_log(
            f"开始升级 -> module={module_name(self.loaded_firmware.footer.module_id)} target=0x{target_addr:02X} d_target=0x{target_dynamic_addr:02X}"
        )
        if self.loaded_firmware.footer.module_id == 0x03 and target_addr != 0x02:
            self.upgrade_tab.append_log("注意: 你说明当前 PFC 固件应发往 0x02，由 LLC 接收。")
        self._send_upgrade_info()

    def stop_upgrade(self, message: str, *, user_initiated: bool) -> None:
        if self.update_tick_job:
            self.after_cancel(self.update_tick_job)
            self.update_tick_job = None
        if self.update_session is None:
            self.upgrade_tab.set_running(False)
            return
        self.upgrade_tab.append_log(message)
        self.upgrade_tab.set_status("升级已停止", message, error_code="STOP" if user_initiated else "-")
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
        if session.stage in {"wait_info_ack", "wait_ready_ack", "wait_packet_ack", "wait_end_ack"}:
            if now - session.last_tx_at >= 1.0:
                if session.timeout_error_since is None:
                    session.timeout_error_since = now
                elif now - session.timeout_error_since >= 10.0:
                    self._fail_upgrade("升级失败", "持续通信超时超过 10 秒。", "TIMEOUT")
                    return

                if session.stage == "wait_info_ack":
                    self.upgrade_tab.append_log("0x08 超时，重发升级信息")
                    self._send_upgrade_info()
                    return
                if session.stage == "wait_ready_ack":
                    self.upgrade_tab.append_log("0x09 超时，重试查询升级准备状态")
                    self._send_upgrade_ready()
                    return
                if session.stage == "wait_packet_ack":
                    self.upgrade_tab.append_log(f"0x0A 超时，重发 offset={session.current_packet_offset}")
                    self._send_upgrade_packet(retry=True)
                    return
                if session.stage == "wait_end_ack":
                    self.upgrade_tab.append_log("0x0B 超时，重发结束帧")
                    self._send_upgrade_end()
                    return
        self._schedule_update_tick()

    def _send_upgrade_info(self) -> None:
        session = self.update_session
        if session is None:
            return
        payload = build_update_info_payload(session.image, session.update_type)
        session.stage = "wait_info_ack"
        session.last_tx_at = time.monotonic()
        self.upgrade_tab.set_status("升级中", "发送升级信息 (0x01 0x08)", error_code="-")
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
        self.upgrade_tab.set_status("升级中", "查询升级准备状态 (0x01 0x09)", error_code="-")
        self.upgrade_tab.append_log("TX 0x09 -> 查询 Bootloader 是否准备完成")
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
            "升级中",
            f"{'重发' if retry else '发送'}固件分包 (0x01 0x0A), offset={session.offset}",
            error_code="-",
        )
        self.upgrade_tab.append_log(
            f"TX 0x0A -> {'重发' if retry else '发送'} offset={session.offset} len={actual_len} progress={session.sent_bytes}/{len(session.image.data)}"
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
        self.upgrade_tab.set_status("升级中", "发送结束帧 (0x01 0x0B)", error_code="-")
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
        updated = False
        while not self.serial_service.rx_queue.empty():
            chunk = self.serial_service.rx_queue.get()
            if chunk.data == b"\n":
                self.monitor_tab.append_receive("\n", "rx")
                continue
            self.total_rx_bytes += len(chunk.data)
            if not self.wave_running:
                self.logger.log("RX", chunk.data.hex(" ").upper())
            self.monitor_tab.append_receive(
                self.format_incoming(chunk.timestamp, chunk.data),
                "rx",
                ensure_separate_line=self.recv_hex_var.get(),
            )
            for frame in self.frame_parser.feed(chunk.data):
                self._log_protocol_frame(frame)
                self.handle_protocol_frame(frame)
            updated = True
            if self.save_handle:
                self.save_handle.write(chunk.data)
                self.save_handle.flush()
        if updated:
            self.rx_count_var.set(f"Receive: {self.total_rx_bytes} bytes")
        self.after(POLL_INTERVAL_MS, self.process_incoming_data)

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
            return
        self.logger.log(
            "FRAME",
            f"cmd_set=0x{frame.cmd_set:02X} cmd_word=0x{frame.cmd_word:02X} is_ack={frame.is_ack} "
            f"src=0x{frame.src:02X} dst=0x{frame.dst:02X} len={len(frame.payload)} payload={frame.payload.hex(' ').upper()}",
        )

    def handle_protocol_frame(self, frame: ProtocolFrame) -> None:
        if frame.cmd_set != 0x01:
            return
        if self._handle_upgrade_protocol_frame(frame):
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
                    self.parameter_tab.set_message(f"已加载参数: {entry.name}")
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
                self.parameter_tab.set_message(f"读取成功: {entry.name} = {format_value(entry.data_raw, entry.type_id)}")
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
                self.parameter_tab.set_message(f"写入成功: {entry.name} = {format_value(entry.data_raw, entry.type_id)}")
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

    def _handle_upgrade_protocol_frame(self, frame: ProtocolFrame) -> bool:
        session = self.update_session
        if session is None or frame.is_ack != 1:
            return False
        if frame.cmd_word not in {CMD_WORD_UPDATE_INFO, CMD_WORD_UPDATE_READY, CMD_WORD_UPDATE_FW, CMD_WORD_UPDATE_END}:
            return False

        session.timeout_error_since = None

        if frame.cmd_word == CMD_WORD_UPDATE_INFO and session.stage == "wait_info_ack":
            if len(frame.payload) < 3:
                self._fail_upgrade("升级失败", "0x08 应答长度无效。", "0x08_LEN")
                return True
            allow_update = frame.payload[0]
            reject_reason = int.from_bytes(frame.payload[1:3], "little")
            self.upgrade_tab.append_log(
                f"RX 0x08 ACK <- allow_update={allow_update} reject_reason=0x{reject_reason:04X}"
            )
            if allow_update == 1:
                self.upgrade_tab.append_log("0x08 应答允许升级")
                self._send_upgrade_ready()
            elif allow_update == 2:
                self._fail_upgrade(
                    "升级失败",
                    f"0x08 拒绝升级: {describe_reject_reason(reject_reason)}",
                    f"0x08:{reject_reason:04X}",
                )
            else:
                self._fail_upgrade("升级失败", "0x08 返回 allow_update 非法。", "0x08_ACK")
            return True

        if frame.cmd_word == CMD_WORD_UPDATE_READY and session.stage == "wait_ready_ack":
            if len(frame.payload) < 1:
                self._fail_upgrade("升级失败", "0x09 应答长度无效。", "0x09_LEN")
                return True
            self.upgrade_tab.append_log(f"RX 0x09 ACK <- ready={frame.payload[0]}")
            if frame.payload[0] == 1:
                self.upgrade_tab.append_log("0x09 返回 ready=1，开始发送固件")
                self._send_upgrade_packet()
            else:
                self.upgrade_tab.append_log("0x09 返回 ready=0，继续等待 Bootloader 准备完成")
                session.last_tx_at = time.monotonic()
                self._schedule_update_tick()
            return True

        if frame.cmd_word == CMD_WORD_UPDATE_FW and session.stage == "wait_packet_ack":
            if len(frame.payload) < 1:
                self._fail_upgrade("升级失败", "0x0A 应答长度无效。", "0x0A_LEN")
                return True
            ack_offset = int.from_bytes(frame.payload[1:5], "little") if len(frame.payload) >= 5 else session.current_packet_offset
            self.upgrade_tab.append_log(
                f"RX 0x0A ACK <- data_is_ok={frame.payload[0]} offset={ack_offset}"
            )
            if len(frame.payload) >= 5:
                packet_offset = ack_offset
                if packet_offset != session.current_packet_offset:
                    self.upgrade_tab.append_log(
                        f"忽略 offset 不匹配的 0x0A 应答: ack={packet_offset}, expect={session.current_packet_offset}"
                    )
                    return True
            if frame.payload[0] == 1:
                session.data_error_since = None
                actual_len = min(session.packet_size, len(session.image.data) - session.current_packet_offset)
                session.offset = session.current_packet_offset + actual_len
                self.upgrade_tab.append_log(
                    f"分包完成 offset={session.current_packet_offset} len={actual_len} -> 已确认 {session.offset}/{len(session.image.data)}"
                )
                if session.offset >= len(session.image.data):
                    self.upgrade_tab.append_log("最后一个分包确认完成，开始发送结束帧")
                    self._send_upgrade_end()
                else:
                    self._send_upgrade_packet()
            else:
                now = time.monotonic()
                if session.data_error_since is None:
                    session.data_error_since = now
                elif now - session.data_error_since >= 10.0:
                    self._fail_upgrade("升级失败", "持续数据错误超过 10 秒。", "0x0A_DATA")
                    return True
                self.upgrade_tab.append_log(f"0x0A 返回 data_is_ok=0，重发 offset={session.current_packet_offset}")
                session.offset = session.current_packet_offset
                self._send_upgrade_packet(retry=True)
            return True

        if frame.cmd_word == CMD_WORD_UPDATE_END and session.stage == "wait_end_ack":
            if len(frame.payload) < 1:
                self._fail_upgrade("升级失败", "0x0B 应答长度无效。", "0x0B_LEN")
                return True
            self.upgrade_tab.append_log(f"RX 0x0B ACK <- success_flg={frame.payload[0]}")
            if frame.payload[0] == 1:
                if session.image.footer.module_id == 0x01:
                    detail = "升级成功，LLC 将复位并按 APP 流程继续转发 PFC 固件。"
                else:
                    detail = "升级成功，设备将复位并跳转到新的 APP。"
                self._complete_upgrade(detail)
            else:
                self._fail_upgrade("升级失败", "0x0B 返回 success_flg=0。", "0x0B_FAIL")
            return True

        return False

    def _handle_wave_report_payload(self, payload: bytes) -> None:
        if len(payload) < 6:
            return
        name_len = payload[0]
        type_id = payload[1]
        data_raw = int.from_bytes(payload[2:6], "little")
        if name_len == 0 and type_id == 0 and data_raw == 0x55555555:
            self.pending_wave_batch = {}
            self.wave_batch_open = True
            self.logger.log("WAVE", "batch start")
            return
        if name_len == 0 and type_id == 0 and data_raw == 0xAAAAAAAA:
            if self.pending_wave_batch:
                self.wave_tab.append_batch(dict(self.pending_wave_batch), batch_time=time.time())
                self.logger.log("WAVE", f"batch end size={len(self.pending_wave_batch)}")
                self.pending_wave_batch.clear()
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
            self.pending_wave_batch[name] = float(value)

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

    def request_single_parameter(self, name: str) -> None:
        if not self.serial_service.is_open():
            self.set_status("Open the serial port first.", error=True)
            return
        payload = bytes([len(name.encode("utf-8"))]) + name.encode("utf-8")
        self.parameter_tab.mark_busy(name)
        self.parameter_tab.set_message(f"正在读取: {name}")
        self.logger.log("PARAM", f"send read single name={name}")
        self.send_protocol_frame(cmd_set=0x01, cmd_word=0x02, payload=payload)

    def write_single_parameter(self, name: str) -> None:
        entry = self.parameters.get(name)
        if entry is None:
            return
        if entry.is_command:
            payload = bytes([len(name.encode("utf-8"))]) + (0).to_bytes(4, "little") * 3 + name.encode("utf-8")
            self.parameter_tab.mark_busy(name)
            self.parameter_tab.set_message(f"正在执行: {name}")
            self.logger.log("PARAM", f"send execute command name={name}")
            self.send_protocol_frame(cmd_set=0x01, cmd_word=0x03, payload=payload)
            return
        pending_value = self.parameter_tab.get_pending_display_value(name)
        if pending_value is None:
            return
        try:
            raw_value = value_to_u32(pending_value, entry.type_id)
            min_value = u32_to_value(entry.min_raw, entry.type_id)
            max_value = u32_to_value(entry.max_raw, entry.type_id)
            typed_value = u32_to_value(raw_value, entry.type_id)
        except ValueError as exc:
            self.set_status(str(exc), error=True)
            self.logger.log("ERROR", f"write value error name={name} err={exc}")
            return
        if isinstance(typed_value, float):
            in_range = float(min_value) <= float(typed_value) <= float(max_value)
        else:
            in_range = int(min_value) <= int(typed_value) <= int(max_value)
        if not in_range:
            self.parameter_tab.clear_busy(name)
            self.parameter_tab.mark_invalid(name)
            self.parameter_tab.set_message(f"写入越界: {name} 需要在 {min_value} 到 {max_value} 之间")
            self.set_status(f"Write out of range: {name}", error=True)
            self.logger.log(
                "WARN",
                f"write out of range name={name} value={typed_value} min={min_value} max={max_value}",
            )
            return
        self.parameter_tab.clear_invalid(name)
        payload = bytes([len(name.encode("utf-8"))]) + raw_value.to_bytes(4, "little") + entry.max_raw.to_bytes(4, "little", signed=False) + entry.min_raw.to_bytes(4, "little", signed=False) + name.encode("utf-8")
        self.parameter_tab.mark_busy(name)
        self.parameter_tab.set_message(f"正在写入: {name}")
        self.logger.log("PARAM", f"send write name={name} raw=0x{raw_value:08X} display={pending_value}")
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
        self.parameter_tab.set_message(f"已更新波形勾选: {name}")
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
        self.tx_count_var.set(f"Send: {self.total_tx_bytes} bytes")

    def format_incoming(self, timestamp: float, data: bytes) -> str:
        prefix = time.strftime("[%H:%M:%S] ", time.localtime(timestamp)) if self.timestamp_var.get() else ""
        body = " ".join(f"{byte:02X}" for byte in data) if self.recv_hex_var.get() else data.decode("utf-8", errors="replace")
        formatted = f"{prefix}{body}"
        if self.recv_hex_var.get() and not formatted.endswith("\n"):
            formatted += "\n"
        return formatted

    def clear_receive_area(self) -> None:
        self.monitor_tab.clear_receive()
        self.logger.log("UI", "clear monitor receive area")

    def save_receive_snapshot(self) -> None:
        self.paths.exports_dir.mkdir(parents=True, exist_ok=True)
        path = filedialog.asksaveasfilename(
            title="Save Receive Data",
            initialdir=str(self.paths.exports_dir),
            defaultextension=".txt",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
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
                filetypes=[("Binary Files", "*.bin"), ("All Files", "*.*")],
            )
            if not path:
                self.save_to_file_var.set(False)
                return
            self.save_path = Path(path)
            self.save_handle = self.save_path.open("ab")
            self.set_status(f"Saving receive data to {self.save_path}")
            self.logger.log("UI", f"start save receive stream -> {self.save_path}")
            return
        if self.save_handle:
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
            payload = self.build_send_bytes(raw_text, hex_mode=self.send_hex_var.get(), append_crlf=self.line_mode_var.get())
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
        self.tx_count_var.set(f"Send: {self.total_tx_bytes} bytes")
        self._echo_sent_payload(payload, hex_mode=self.send_hex_var.get())
        self.set_status(f"Sent {sent} byte(s)")

    def send_preset_payload(self, index: int, raw_text: str, hex_mode: bool, append_crlf: bool) -> None:
        if not self.serial_service.is_open():
            self.set_status("Open the serial port first.", error=True)
            return
        if not raw_text.strip():
            self.set_status(f"快捷发送 {index + 1} 为空", error=True)
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
        self.tx_count_var.set(f"Send: {self.total_tx_bytes} bytes")
        self._echo_sent_payload(payload, hex_mode=hex_mode)
        self.set_status(f"快捷发送 {index + 1} 已发送 {sent} byte(s)")

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
        if hex_mode:
            body = " ".join(f"{byte:02X}" for byte in payload)
        else:
            body = payload.decode("utf-8", errors="replace")
        display_text = f"{prefix}{body}"
        if not display_text.endswith("\n"):
            display_text += "\n"
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
        self.rx_count_var.set("Receive: 0 bytes")
        self.tx_count_var.set("Send: 0 bytes")
        self.set_status("Counters reset")
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
        self.stop_upgrade("应用关闭，升级已停止。", user_initiated=False)
        self.serial_service.close()
        if self.save_handle:
            self.save_handle.close()
            self.save_handle = None
        self.destroy()


def launch_app() -> None:
    app = SerialDebugAssistant()
    app.mainloop()
