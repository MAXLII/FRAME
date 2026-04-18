from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from serial_debug_assistant.factory_mode import get_factory_cali_label_pairs


class FactoryModeTab(ttk.Frame):
    def __init__(self, master, *, on_read_time, on_set_current_time, on_read_cali, on_write_cali, on_save_cali) -> None:
        super().__init__(master, style="Panel.TFrame", padding=12)
        self.on_read_time = on_read_time
        self.on_set_current_time = on_set_current_time
        self.on_read_cali = on_read_cali
        self.on_write_cali = on_write_cali
        self.on_save_cali = on_save_cali

        self.target_addr_var = tk.StringVar(value="2")
        self.dynamic_addr_var = tk.StringVar(value="0")
        self.timezone_var = tk.StringVar(value="+8")
        self.device_time_var = tk.StringVar(value="-")
        self.device_unix_var = tk.StringVar(value="-")
        self.device_timezone_var = tk.StringVar(value="-")
        self.cali_dst_var = tk.StringVar(value="2")
        self.cali_d_dst_var = tk.StringVar(value="0")
        self.cali_options = get_factory_cali_label_pairs()
        self.cali_label_to_id = {label: cali_id for cali_id, label in self.cali_options}
        self.cali_id_to_label = {cali_id: label for cali_id, label in self.cali_options}
        default_cali_label = self.cali_id_to_label.get(0, "")
        self.cali_id_var = tk.StringVar(value=default_cali_label)
        self.cali_gain_var = tk.StringVar(value="1.0")
        self.cali_bias_var = tk.StringVar(value="0.0")
        self.cali_status_var = tk.StringVar(value="Waiting for calibration actions")
        self.cali_detail_var = tk.StringVar(value="Read the current gain and offset, then write and save if needed.")
        self.status_var = tk.StringVar(value="Waiting for factory mode actions")
        self.detail_var = tk.StringVar(value="Read the device time first, then set the current PC UTC time if needed.")

        self._build()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        control_frame = ttk.LabelFrame(self, text="Factory Mode", style="Section.TLabelframe", padding=12)
        control_frame.grid(row=0, column=0, sticky="ew")
        for column in range(6):
            control_frame.columnconfigure(column, weight=1 if column in {1, 3, 5} else 0)

        ttk.Label(control_frame, text="Target Address").grid(row=0, column=0, sticky="w")
        ttk.Entry(control_frame, textvariable=self.target_addr_var, width=10).grid(row=0, column=1, sticky="ew", padx=(8, 16))
        ttk.Label(control_frame, text="Dynamic Address").grid(row=0, column=2, sticky="w")
        ttk.Entry(control_frame, textvariable=self.dynamic_addr_var, width=10).grid(row=0, column=3, sticky="ew", padx=(8, 16))
        button_row = ttk.Frame(control_frame, style="Panel.TFrame")
        button_row.grid(row=0, column=4, columnspan=2, sticky="e")
        ttk.Button(button_row, text="Read Device Time", command=self.on_read_time, width=16).grid(row=0, column=0, sticky="w")
        ttk.Button(button_row, text="Set PC UTC Time", command=self.on_set_current_time, style="Accent.TButton", width=16).grid(row=0, column=1, sticky="w", padx=(12, 0))

        ttk.Label(control_frame, text="Timezone").grid(row=1, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(control_frame, textvariable=self.timezone_var, width=10).grid(row=1, column=1, sticky="ew", padx=(8, 16), pady=(12, 0))
        ttk.Label(control_frame, text="Supports UTC+8, UTC+5:30, -3.5").grid(row=1, column=2, columnspan=4, sticky="w", pady=(12, 0))

        info_frame = ttk.LabelFrame(self, text="Device Time", style="Section.TLabelframe", padding=12)
        info_frame.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        info_frame.columnconfigure(1, weight=1)

        rows = [
            ("Timezone-Aware Time", self.device_time_var),
            ("Unix Time (UTC)", self.device_unix_var),
            ("Timezone", self.device_timezone_var),
            ("Status", self.status_var),
            ("Detail", self.detail_var),
        ]
        for row, (label, variable) in enumerate(rows):
            ttk.Label(info_frame, text=label).grid(row=row, column=0, sticky="w", pady=4)
            ttk.Label(info_frame, textvariable=variable).grid(row=row, column=1, sticky="w", pady=4, padx=(12, 0))

        cali_frame = ttk.LabelFrame(self, text="Calibration", style="Section.TLabelframe", padding=12)
        cali_frame.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        for column in range(6):
            cali_frame.columnconfigure(column, weight=1 if column in {1, 3, 5} else 0)

        ttk.Label(cali_frame, text="Destination Address").grid(row=0, column=0, sticky="w")
        ttk.Entry(cali_frame, textvariable=self.cali_dst_var, width=10).grid(row=0, column=1, sticky="ew", padx=(8, 16))
        ttk.Label(cali_frame, text="Dynamic Address").grid(row=0, column=2, sticky="w")
        ttk.Entry(cali_frame, textvariable=self.cali_d_dst_var, width=10).grid(row=0, column=3, sticky="ew", padx=(8, 16))
        ttk.Button(cali_frame, text="Read Current", command=self.on_read_cali, width=14).grid(row=0, column=4, sticky="w")
        ttk.Button(cali_frame, text="Save To Flash", command=self.on_save_cali, width=14).grid(row=0, column=5, sticky="e")

        ttk.Label(cali_frame, text="Calibration ID").grid(row=1, column=0, sticky="w", pady=(12, 0))
        ttk.Combobox(
            cali_frame,
            textvariable=self.cali_id_var,
            values=[label for _, label in self.cali_options],
            state="readonly",
            width=24,
        ).grid(row=1, column=1, sticky="ew", padx=(8, 16), pady=(12, 0))
        ttk.Label(cali_frame, text="Gain").grid(row=1, column=2, sticky="w", pady=(12, 0))
        ttk.Entry(cali_frame, textvariable=self.cali_gain_var, width=10).grid(row=1, column=3, sticky="ew", padx=(8, 16), pady=(12, 0))
        ttk.Label(cali_frame, text="Offset").grid(row=1, column=4, sticky="w", pady=(12, 0))
        ttk.Entry(cali_frame, textvariable=self.cali_bias_var, width=10).grid(row=1, column=5, sticky="ew", pady=(12, 0))

        ttk.Button(cali_frame, text="Send Calibration", command=self.on_write_cali, style="Accent.TButton", width=18).grid(
            row=2, column=4, columnspan=2, sticky="e", pady=(12, 0)
        )

        ttk.Label(cali_frame, text="Calibration Status").grid(row=3, column=0, sticky="w", pady=(12, 0))
        ttk.Label(cali_frame, textvariable=self.cali_status_var).grid(row=3, column=1, columnspan=5, sticky="w", padx=(12, 0), pady=(12, 0))
        ttk.Label(cali_frame, text="Calibration Detail").grid(row=4, column=0, sticky="w", pady=(4, 0))
        ttk.Label(cali_frame, textvariable=self.cali_detail_var).grid(row=4, column=1, columnspan=5, sticky="w", padx=(12, 0), pady=(4, 0))

    def get_target_address(self) -> tuple[int, int]:
        return int(self.target_addr_var.get() or "0"), int(self.dynamic_addr_var.get() or "0")

    def get_timezone_text(self) -> str:
        return self.timezone_var.get().strip()

    def get_cali_target_address(self) -> tuple[int, int]:
        return int(self.cali_dst_var.get() or "0"), int(self.cali_d_dst_var.get() or "0")

    def get_cali_values(self) -> tuple[int, float, float]:
        cali_label = self.cali_id_var.get().strip()
        if cali_label not in self.cali_label_to_id:
            raise ValueError("Calibration selection is invalid.")
        return (
            self.cali_label_to_id[cali_label],
            float(self.cali_gain_var.get().strip() or "0"),
            float(self.cali_bias_var.get().strip() or "0"),
        )

    def set_device_time(self, *, formatted_time: str, unix_time_utc: int, timezone_text: str) -> None:
        self.device_time_var.set(formatted_time)
        self.device_unix_var.set(str(unix_time_utc))
        self.device_timezone_var.set(timezone_text)

    def set_timezone_input(self, timezone_text: str) -> None:
        self.timezone_var.set(timezone_text)

    def set_cali_values(self, *, cali_id: int, gain: float, bias: float) -> None:
        self.cali_id_var.set(self.cali_id_to_label.get(cali_id, self.cali_id_var.get()))
        self.cali_gain_var.set(f"{gain:.6g}")
        self.cali_bias_var.set(f"{bias:.6g}")

    def set_cali_status(self, status: str, detail: str = "") -> None:
        self.cali_status_var.set(status)
        self.cali_detail_var.set(detail)

    def set_status(self, status: str, detail: str = "") -> None:
        self.status_var.set(status)
        self.detail_var.set(detail)
