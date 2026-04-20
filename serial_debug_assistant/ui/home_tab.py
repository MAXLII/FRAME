from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional

from serial_debug_assistant.i18n import I18nManager


class HomeTab(ttk.Frame):
    def __init__(self, master, *, i18n: I18nManager) -> None:
        super().__init__(master, style="Panel.TFrame", padding=12)
        self.i18n = i18n
        self._translatable_widgets: list[tuple[object, str, str]] = []
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.value_width = 10

        self.grid_voltage_var = tk.StringVar(value="-- V")
        self.grid_current_var = tk.StringVar(value="-- A")
        self.grid_power_var = tk.StringVar(value="-- W")
        self.grid_freq_var = tk.StringVar(value="-- Hz")

        self.inv_voltage_var = tk.StringVar(value="-- V")
        self.inv_current_var = tk.StringVar(value="-- A")
        self.inv_power_var = tk.StringVar(value="-- W")
        self.inv_freq_var = tk.StringVar(value="-- Hz")

        self.battery_voltage_var = tk.StringVar(value="-- V")
        self.battery_current_var = tk.StringVar(value="-- A")
        self.battery_soc_var = tk.StringVar(value="-- %")
        self.battery_power_var = tk.StringVar(value="-- W")
        self.battery_temp_var = tk.StringVar(value="-- C")

        self.mppt_voltage_var = tk.StringVar(value="-- V")
        self.mppt_current_var = tk.StringVar(value="-- A")
        self.mppt_power_var = tk.StringVar(value="-- W")
        self.mppt_temp_var = tk.StringVar(value="-- C")

        self.pfc_temp_var = tk.StringVar(value="-- C")
        self.llc_temp1_var = tk.StringVar(value="-- C")
        self.llc_temp2_var = tk.StringVar(value="-- C")
        self.inv_cfg_var = tk.StringVar(value="220V/50Hz")
        self.inv_cfg_status_var = tk.StringVar(value=self.i18n.translate_text("等待读取逆变设置"))
        self._inv_cfg_choices = ("220V/50Hz", "230V/50Hz", "240V/50Hz")

        self.indicator_dots: dict[str, tk.Canvas] = {}
        self._indicator_state_cache: dict[str, Optional[bool]] = {}
        self._fault_log_cache: str | None = None
        self._warning_log_cache: str | None = None

        body = ttk.Frame(self, style="Panel.TFrame")
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        body.rowconfigure(1, weight=0)

        content = ttk.Frame(body, style="Panel.TFrame")
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.columnconfigure(1, weight=1)
        content.rowconfigure(0, weight=4, minsize=180)
        content.rowconfigure(1, weight=3, minsize=150)
        content.rowconfigure(2, weight=2, minsize=96)

        bottom_strip = ttk.Frame(body, style="Panel.TFrame")
        bottom_strip.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        bottom_strip.columnconfigure(0, weight=1, uniform="bottom")
        bottom_strip.columnconfigure(1, weight=1, uniform="bottom")
        bottom_strip.columnconfigure(2, weight=1, uniform="bottom")

        self._build_ac_section(content, row=0, column=0, columnspan=2)
        self._build_section(
            content,
            row=1,
            column=0,
            title="电池",
            rows=[
                ("电池电压", self.battery_voltage_var),
                ("电池电流", self.battery_current_var),
                ("SOC", self.battery_soc_var),
                ("电池功率", self.battery_power_var),
                ("电池温度", self.battery_temp_var),
            ],
        )
        self._build_section(
            content,
            row=1,
            column=1,
            title="MPPT / PV",
            rows=[
                ("输入电压", self.mppt_voltage_var),
                ("输入电流", self.mppt_current_var),
                ("输入功率", self.mppt_power_var),
                ("MPPT 温度", self.mppt_temp_var),
            ],
        )
        self._build_state_section(content, row=2, column=0, columnspan=2)

        self._build_settings_section(bottom_strip, row=0, column=0)
        self.fault_text = self._build_log_section(bottom_strip, row=0, column=1, title="故障信息")
        self.warning_text = self._build_log_section(bottom_strip, row=0, column=2, title="告警信息")

        self.set_fault_log(self.i18n.translate_text("暂无故障信息"))
        self.set_warning_log(self.i18n.translate_text("暂无告警信息"))

    def update_pcs_info(
        self,
        *,
        mppt_vin: Optional[float],
        mppt_iin: Optional[float],
        mppt_pwr: Optional[float],
        mppt_temp: Optional[float],
        ac_v_grid: Optional[float],
        ac_i_grid: Optional[float],
        ac_freq_grid: Optional[float],
        ac_pwr_grid: Optional[float],
        ac_v_inv: Optional[float],
        ac_i_inv: Optional[float],
        ac_pwr_inv: Optional[float],
        ac_freq_inv: Optional[float],
        pfc_temp: Optional[float],
        llc_temp1: Optional[float],
        llc_temp2: Optional[float],
        fan_sta: Optional[int],
        rly_sta: Optional[int],
        protect: Optional[int],
        fault: Optional[int],
        warning: Optional[int],
        bat_volt: Optional[float],
        bat_curr: Optional[float],
        bat_pwr: Optional[float],
        bat_temp: Optional[float],
        soc: Optional[float],
    ) -> None:
        self._set_var_if_changed(self.grid_voltage_var, self._fmt(ac_v_grid, "V"))
        self._set_var_if_changed(self.grid_current_var, self._fmt(ac_i_grid, "A"))
        self._set_var_if_changed(self.grid_power_var, self._fmt(ac_pwr_grid, "W"))
        self._set_var_if_changed(self.grid_freq_var, self._fmt(ac_freq_grid, "Hz"))

        self._set_var_if_changed(self.inv_voltage_var, self._fmt(ac_v_inv, "V"))
        self._set_var_if_changed(self.inv_current_var, self._fmt(ac_i_inv, "A"))
        self._set_var_if_changed(self.inv_power_var, self._fmt(ac_pwr_inv, "W"))
        self._set_var_if_changed(self.inv_freq_var, self._fmt(ac_freq_inv, "Hz"))

        self._set_var_if_changed(self.battery_voltage_var, self._fmt(bat_volt, "V"))
        self._set_var_if_changed(self.battery_current_var, self._fmt(bat_curr, "A"))
        self._set_var_if_changed(self.battery_power_var, self._fmt(bat_pwr, "W"))
        self._set_var_if_changed(self.battery_temp_var, self._fmt(bat_temp, "C"))
        self._set_var_if_changed(self.battery_soc_var, self._fmt(soc, "%"))

        self._set_var_if_changed(self.mppt_voltage_var, self._fmt(mppt_vin, "V"))
        self._set_var_if_changed(self.mppt_current_var, self._fmt(mppt_iin, "A"))
        self._set_var_if_changed(self.mppt_power_var, self._fmt(mppt_pwr, "W"))
        self._set_var_if_changed(self.mppt_temp_var, self._fmt(mppt_temp, "C"))

        self._set_var_if_changed(self.pfc_temp_var, self._fmt(pfc_temp, "C"))
        self._set_var_if_changed(self.llc_temp1_var, self._fmt(llc_temp1, "C"))
        self._set_var_if_changed(self.llc_temp2_var, self._fmt(llc_temp2, "C"))

        self._set_indicator("fan", None if fan_sta is None else fan_sta == 1)
        self._set_indicator("grid_rly", None if rly_sta is None else bool(rly_sta & 0x01))
        self._set_indicator("inv_rly", None if rly_sta is None else bool(rly_sta & 0x02))
        self._set_indicator("predsg_mos", None if rly_sta is None else bool(rly_sta & 0x04))
        self._set_indicator("dsg_mos", None if rly_sta is None else bool(rly_sta & 0x08))
        self._set_indicator("pv_mos", None if rly_sta is None else bool(rly_sta & 0x10))

    def _build_section(
        self,
        parent: ttk.Frame,
        *,
        row: int,
        column: int,
        title: str,
        rows: list[tuple[str, tk.StringVar]],
        columnspan: int = 1,
    ) -> None:
        frame = ttk.LabelFrame(parent, text=self.i18n.translate_text(title), style="Section.TLabelframe", padding=10)
        self._remember_text(frame, title)
        frame.grid(row=row, column=column, columnspan=columnspan, sticky="nsew", padx=6, pady=6)
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=0, minsize=92)

        for index, (label_text, value_var) in enumerate(rows):
            item = ttk.Frame(frame, style="Panel.TFrame")
            item.grid(row=index, column=0, columnspan=2, sticky="ew", pady=(0, 4 if index < len(rows) - 1 else 0))
            item.columnconfigure(0, weight=1)
            label = ttk.Label(item, text=self.i18n.translate_text(label_text), style="TLabel")
            self._remember_text(label, label_text)
            label.grid(row=0, column=0, sticky="w")
            ttk.Label(
                item,
                textvariable=value_var,
                style="Header.TLabel",
                anchor="e",
                justify="right",
                width=self.value_width,
            ).grid(row=0, column=1, sticky="e", padx=(18, 0))

    def _build_log_section(self, parent: ttk.Frame, *, row: int, column: int, title: str) -> tk.Text:
        frame = ttk.LabelFrame(parent, text=self.i18n.translate_text(title), style="Section.TLabelframe", padding=6)
        self._remember_text(frame, title)
        frame.grid(row=row, column=column, sticky="nsew", padx=6, pady=0)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        text = tk.Text(
            frame,
            height=5,
            wrap="word",
            bg="#f8fbfe",
            fg="#223548",
            insertbackground="#223548",
            relief="flat",
            highlightthickness=1,
            highlightbackground="#bfd0e3",
            padx=8,
            pady=8,
            font=("Consolas", 10),
        )
        text.grid(row=0, column=0, sticky="nsew")

        scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        text.configure(yscrollcommand=scroll.set)
        text.configure(state="disabled")
        return text

    def _build_ac_section(
        self,
        parent: ttk.Frame,
        *,
        row: int,
        column: int,
        columnspan: int = 1,
    ) -> None:
        frame = ttk.LabelFrame(parent, text=self.i18n.translate_text("交流侧"), style="Section.TLabelframe", padding=10)
        self._remember_text(frame, "交流侧")
        frame.grid(row=row, column=column, columnspan=columnspan, sticky="nsew", padx=6, pady=6)
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=0, minsize=1)
        frame.columnconfigure(2, weight=1)
        frame.columnconfigure(3, weight=0, minsize=1)
        frame.columnconfigure(4, weight=1)

        self._build_subsection(
            frame,
            row=0,
            column=0,
            title="市电",
            rows=[
                ("电压", self.grid_voltage_var),
                ("电流", self.grid_current_var),
                ("功率", self.grid_power_var),
                ("频率", self.grid_freq_var),
            ],
        )

        ttk.Separator(frame, orient="vertical").grid(row=0, column=1, sticky="ns", padx=8)

        self._build_subsection(
            frame,
            row=0,
            column=2,
            title="输出",
            rows=[
                ("电压", self.inv_voltage_var),
                ("电流", self.inv_current_var),
                ("功率", self.inv_power_var),
                ("频率", self.inv_freq_var),
            ],
        )

        ttk.Separator(frame, orient="vertical").grid(row=0, column=3, sticky="ns", padx=8)

        self._build_subsection(
            frame,
            row=0,
            column=4,
            title="温度",
            rows=[
                ("PFC", self.pfc_temp_var),
                ("LLC 1", self.llc_temp1_var),
                ("LLC 2", self.llc_temp2_var),
            ],
        )

    def _build_subsection(
        self,
        parent: ttk.Frame,
        *,
        row: int,
        column: int,
        title: str,
        rows: list[tuple[str, tk.StringVar]],
    ) -> None:
        panel = ttk.Frame(parent, style="Panel.TFrame")
        panel.grid(row=row, column=column, sticky="nsew")
        panel.columnconfigure(0, weight=1)
        panel.columnconfigure(1, weight=0, minsize=92)
        title_label = ttk.Label(panel, text=self.i18n.translate_text(title), style="Header.TLabel")
        self._remember_text(title_label, title)
        title_label.grid(row=0, column=0, sticky="w", pady=(0, 6))

        for index, (label_text, value_var) in enumerate(rows, start=1):
            self._build_value_row(panel, row=index, label_text=label_text, value_var=value_var)

    def _build_state_section(
        self,
        parent: ttk.Frame,
        *,
        row: int,
        column: int,
        columnspan: int = 1,
    ) -> None:
        frame = ttk.LabelFrame(parent, text=self.i18n.translate_text("状态"), style="Section.TLabelframe", padding=10)
        self._remember_text(frame, "状态")
        frame.grid(row=row, column=column, columnspan=columnspan, sticky="nsew", padx=6, pady=6)
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

        ttk.Separator(frame, orient="horizontal").grid(
            row=0,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(0, 8),
        )

        indicator_panel = ttk.Frame(frame, style="Panel.TFrame")
        indicator_panel.grid(row=1, column=0, columnspan=2, sticky="ew")
        indicator_panel.columnconfigure(0, weight=1)
        indicator_panel.columnconfigure(1, weight=1)

        self._build_indicator_item(
            indicator_panel,
            row=0,
            column=0,
            key="fan",
            title="风扇状态",
        )
        self._build_indicator_item(
            indicator_panel,
            row=0,
            column=1,
            key="grid_rly",
            title="市电输入继电器",
        )
        self._build_indicator_item(
            indicator_panel,
            row=1,
            column=0,
            key="inv_rly",
            title="逆变输出继电器",
        )
        self._build_indicator_item(
            indicator_panel,
            row=1,
            column=1,
            key="predsg_mos",
            title="电池预放 MOS",
        )
        self._build_indicator_item(
            indicator_panel,
            row=2,
            column=0,
            key="dsg_mos",
            title="电池放电 MOS",
        )
        self._build_indicator_item(
            indicator_panel,
            row=2,
            column=1,
            key="pv_mos",
            title="MPPT 输入 MOS",
        )

    def _build_settings_section(
        self,
        parent: ttk.Frame,
        *,
        row: int,
        column: int,
    ) -> None:
        frame = ttk.LabelFrame(parent, text=self.i18n.translate_text("设置"), style="Section.TLabelframe", padding=10)
        self._remember_text(frame, "设置")
        frame.grid(row=row, column=column, sticky="nsew", padx=6, pady=0)
        frame.columnconfigure(0, weight=1)

        top_row = ttk.Frame(frame, style="Panel.TFrame")
        top_row.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        top_row.columnconfigure(2, weight=1)

        top_label = ttk.Label(top_row, text=self.i18n.translate_text("AC 输出控制"), style="TLabel")
        self._remember_text(top_label, "AC 输出控制")
        top_label.grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.enable_output_button = ttk.Button(top_row, text=self.i18n.translate_text("打开 AC 输出"), style="TButton")
        self._remember_text(self.enable_output_button, "打开 AC 输出")
        self.enable_output_button.grid(row=0, column=1, sticky="w", padx=(0, 8))
        self.disable_output_button = ttk.Button(top_row, text=self.i18n.translate_text("关闭 AC 输出"), style="TButton")
        self._remember_text(self.disable_output_button, "关闭 AC 输出")
        self.disable_output_button.grid(row=0, column=2, sticky="w")

        bottom_row = ttk.Frame(frame, style="Panel.TFrame")
        bottom_row.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        bottom_row.columnconfigure(3, weight=1)

        bottom_label = ttk.Label(bottom_row, text=self.i18n.translate_text("输出配置"), style="TLabel")
        self._remember_text(bottom_label, "输出配置")
        bottom_label.grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.config_combo = ttk.Combobox(
            bottom_row,
            textvariable=self.inv_cfg_var,
            state="readonly",
            values=self._inv_cfg_choices,
            width=14,
        )
        self.config_combo.grid(row=0, column=1, sticky="w", padx=(0, 10))

        self.send_cfg_button = ttk.Button(bottom_row, text=self.i18n.translate_text("发送设置"), style="Primary.TButton")
        self._remember_text(self.send_cfg_button, "发送设置")
        self.send_cfg_button.grid(row=0, column=2, sticky="w")

        third_row = ttk.Frame(frame, style="Panel.TFrame")
        third_row.grid(row=2, column=0, sticky="ew")
        third_row.columnconfigure(0, weight=1)

        ttk.Label(third_row, textvariable=self.inv_cfg_status_var, style="TLabel").grid(
            row=0,
            column=0,
            sticky="w",
        )
        self.read_cfg_button = ttk.Button(third_row, text=self.i18n.translate_text("读取当前设置"), style="TButton")
        self._remember_text(self.read_cfg_button, "读取当前设置")
        self.read_cfg_button.grid(row=0, column=1, sticky="w", padx=(10, 0))


    def _build_value_row(self, parent: ttk.Frame, *, row: int, label_text: str, value_var: tk.StringVar) -> None:
        item = ttk.Frame(parent, style="Panel.TFrame")
        item.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        item.columnconfigure(0, weight=1)
        label = ttk.Label(item, text=self.i18n.translate_text(label_text), style="TLabel")
        self._remember_text(label, label_text)
        label.grid(row=0, column=0, sticky="w")
        ttk.Label(
            item,
            textvariable=value_var,
            style="Header.TLabel",
            anchor="e",
            justify="right",
            width=self.value_width,
        ).grid(row=0, column=1, sticky="e", padx=(18, 0))

    def _build_indicator_item(
        self,
        parent: ttk.Frame,
        *,
        row: int,
        column: int,
        key: str,
        title: str,
    ) -> None:
        item = ttk.Frame(parent, style="Panel.TFrame")
        item.grid(row=row, column=column, sticky="ew", padx=(0 if column == 0 else 8, 0), pady=(0, 8 if row < 2 else 0))
        item.columnconfigure(1, weight=1)

        dot = tk.Canvas(item, width=16, height=16, bg="#fbfdff", highlightthickness=0, bd=0)
        dot.grid(row=0, column=0, padx=(0, 8), sticky="w")
        dot.create_oval(2, 2, 14, 14, fill="#c4c4c4", outline="")
        self.indicator_dots[key] = dot

        label = ttk.Label(item, text=self.i18n.translate_text(title), style="TLabel")
        self._remember_text(label, title)
        label.grid(row=0, column=1, sticky="w")

    def set_fault_log(self, message: str) -> None:
        if message == self._fault_log_cache:
            return
        self._fault_log_cache = message
        self._replace_text(self.fault_text, message)

    def set_warning_log(self, message: str) -> None:
        if message == self._warning_log_cache:
            return
        self._warning_log_cache = message
        self._replace_text(self.warning_text, message)

    def bind_inv_cfg_actions(self, *, on_enable, on_disable, on_send, on_read) -> None:
        self.enable_output_button.configure(command=on_enable)
        self.disable_output_button.configure(command=on_disable)
        self.send_cfg_button.configure(command=on_send)
        self.read_cfg_button.configure(command=on_read)

    def get_selected_inv_cfg(self) -> tuple[int, int]:
        try:
            voltage_text, freq_text = self.inv_cfg_var.get().split("/")
            return int(voltage_text.rstrip("Vv")), int(freq_text.rstrip("Hzhz"))
        except (ValueError, AttributeError):
            return 220, 50

    def apply_inv_cfg_ack(self, *, ac_out_enable_trig: int, ac_out_disable_trig: int, ac_out_rms: int, ac_out_freq: int) -> None:
        if ac_out_rms != 0xFF and ac_out_freq != 0xFF:
            combo_value = f"{ac_out_rms}V/{ac_out_freq}Hz"
            if combo_value in self._inv_cfg_choices:
                self.inv_cfg_var.set(combo_value)
        if ac_out_enable_trig == 0xFF and ac_out_disable_trig == 0xFF and ac_out_rms == 0xFF and ac_out_freq == 0xFF:
            self.inv_cfg_status_var.set(self.i18n.translate_text("已读取当前逆变设置"))
        elif ac_out_enable_trig == 1:
            self.inv_cfg_status_var.set(self.i18n.translate_text("已应答: 打开 AC 输出"))
        elif ac_out_disable_trig == 1:
            self.inv_cfg_status_var.set(self.i18n.translate_text("已应答: 关闭 AC 输出"))
        else:
            display = f"{ac_out_rms}V/{ac_out_freq}Hz" if ac_out_rms != 0xFF and ac_out_freq != 0xFF else self.i18n.translate_text("保持当前")
            self.inv_cfg_status_var.set(self.i18n.format_text("逆变设置已更新: {display}", display=display))

    def refresh_texts(self) -> None:
        for widget, source_text, option in self._translatable_widgets:
            widget.configure(**{option: self.i18n.translate_text(source_text)})
        self.inv_cfg_status_var.set(self.i18n.translate_text(self.inv_cfg_status_var.get()))
        if self._fault_log_cache is not None:
            self._replace_text(self.fault_text, self.i18n.translate_text(self._fault_log_cache))
        if self._warning_log_cache is not None:
            self._replace_text(self.warning_text, self.i18n.translate_text(self._warning_log_cache))

    def _remember_text(self, widget: object, source_text: str, option: str = "text") -> None:
        self._translatable_widgets.append((widget, source_text, option))

    def _replace_text(self, widget: tk.Text, message: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", message)
        widget.configure(state="disabled")

    def _set_indicator(self, key: str, active: Optional[bool]) -> None:
        dot = self.indicator_dots.get(key)
        if dot is None:
            return
        if self._indicator_state_cache.get(key) is active:
            return
        self._indicator_state_cache[key] = active
        fill = "#c4c4c4" if active is None else ("#2fb36d" if active else "#c4c4c4")
        dot.delete("all")
        dot.create_oval(2, 2, 14, 14, fill=fill, outline="")

    def _set_var_if_changed(self, var: tk.StringVar, value: str) -> None:
        if var.get() == value:
            return
        var.set(value)

    def _fmt(self, value: Optional[float], unit: str) -> str:
        if value is None:
            return f"-- {unit}"
        text = f"{value:7.3f}".rstrip("0").rstrip(".")
        return f"{text} {unit}"
