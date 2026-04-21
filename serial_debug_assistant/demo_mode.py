from __future__ import annotations

import math
import struct
import time
from dataclasses import replace

from serial_debug_assistant.firmware_update import FW_TYPE_IAP, calculate_crc32
from serial_debug_assistant.models import (
    FirmwareFooter,
    FirmwareImage,
    ParameterEntry,
    ScopeCapture,
    ScopeInfo,
    ScopeListItem,
)
from serial_debug_assistant.protocol import crc16_ccitt, value_to_u32
from serial_debug_assistant.scope_protocol import (
    SCOPE_READ_MODE_FORCE,
    SCOPE_READ_MODE_NORMAL,
    SCOPE_TOOL_STATE_IDLE,
    SCOPE_TOOL_STATE_RUNNING,
    SCOPE_TOOL_STATE_TRIGGERED,
    SCOPE_TOOL_STATUS_OK,
)


class DemoRuntime:
    def __init__(self) -> None:
        self.started_at = time.monotonic()
        self.ac_output_enabled = True
        self.inv_cfg = (220, 50)
        self._parameters = self._build_initial_parameters()
        self._command_counter = 0
        self._scope_specs = self._build_scope_specs()

    def list_parameters(self) -> dict[str, ParameterEntry]:
        self._update_dynamic_parameters()
        return {name: replace(entry) for name, entry in self._parameters.items()}

    def read_parameter(self, name: str) -> ParameterEntry | None:
        self._update_dynamic_parameters()
        entry = self._parameters.get(name)
        if entry is None:
            return None
        return replace(entry)

    def write_parameter(self, name: str, *, data_raw: int, min_raw: int, max_raw: int) -> ParameterEntry | None:
        entry = self._parameters.get(name)
        if entry is None or entry.is_command:
            return None
        updated = replace(entry, data_raw=data_raw, min_raw=min_raw, max_raw=max_raw, dirty=False)
        self._parameters[name] = updated
        return replace(updated)

    def execute_command(self, name: str) -> str:
        entry = self._parameters.get(name)
        if entry is None or not entry.is_command:
            return "演示命令不存在"
        self._command_counter += 1
        return f"已执行演示命令: {name} (第 {self._command_counter} 次)"

    def set_auto_report(self, name: str, enabled: bool) -> ParameterEntry | None:
        entry = self._parameters.get(name)
        if entry is None or entry.is_command:
            return None
        updated = replace(entry, auto_report=enabled)
        self._parameters[name] = updated
        return replace(updated)

    def set_inv_cfg(self, *, enabled: bool | None = None, rms: int | None = None, freq: int | None = None) -> dict[str, int]:
        if enabled is not None:
            self.ac_output_enabled = enabled
        if rms is not None and freq is not None:
            self.inv_cfg = (rms, freq)
        return {
            "ac_out_enable_trig": 1 if enabled is True else 0xFF,
            "ac_out_disable_trig": 1 if enabled is False else 0xFF,
            "ac_out_rms": self.inv_cfg[0],
            "ac_out_freq": self.inv_cfg[1],
        }

    def current_home_info(self) -> tuple[dict[str, float | int], str, str]:
        elapsed = time.monotonic() - self.started_at
        grid_voltage = 219.0 + 4.5 * math.sin(elapsed / 3.8)
        grid_current = 5.2 + 1.1 * math.sin(elapsed / 2.2)
        grid_power = max(grid_voltage * grid_current * 0.92, 0.0)
        inv_voltage = float(self.inv_cfg[0]) if self.ac_output_enabled else 0.0
        inv_current = (4.8 + 1.0 * math.sin(elapsed / 1.9)) if self.ac_output_enabled else 0.0
        inv_power = inv_voltage * inv_current * 0.88 if self.ac_output_enabled else 0.0
        battery_voltage = 51.4 + 0.7 * math.sin(elapsed / 9.5)
        battery_current = -12.0 + 6.5 * math.sin(elapsed / 2.7)
        battery_power = battery_voltage * battery_current
        battery_temp = 27.5 + 2.0 * math.sin(elapsed / 8.4)
        mppt_voltage = 378.0 + 18.0 * math.sin(elapsed / 4.1)
        mppt_current = 7.8 + 1.3 * math.sin(elapsed / 3.4)
        mppt_power = mppt_voltage * mppt_current * 0.96
        mppt_temp = 39.0 + 3.5 * math.sin(elapsed / 6.0)
        pfc_temp = 43.0 + 2.8 * math.sin(elapsed / 6.8)
        llc_temp1 = 45.0 + 2.4 * math.sin(elapsed / 5.2)
        llc_temp2 = 44.0 + 2.2 * math.sin(elapsed / 5.6)
        soc = 68.0 + 4.0 * math.sin(elapsed / 14.0)
        warning = 0x01 if math.sin(elapsed / 12.0) > 0.8 else 0x00

        info = {
            "mppt_vin": mppt_voltage,
            "mppt_iin": mppt_current,
            "mppt_pwr": mppt_power,
            "mppt_temp": mppt_temp,
            "ac_v_grid": grid_voltage,
            "ac_i_grid": grid_current,
            "ac_freq_grid": float(self.inv_cfg[1]) + 0.08 * math.sin(elapsed / 7.5),
            "ac_pwr_grid": grid_power,
            "ac_v_inv": inv_voltage,
            "ac_i_inv": inv_current,
            "ac_pwr_inv": inv_power,
            "ac_freq_inv": float(self.inv_cfg[1]) if self.ac_output_enabled else 0.0,
            "pfc_temp": pfc_temp,
            "llc_temp1": llc_temp1,
            "llc_temp2": llc_temp2,
            "fan_sta": 1,
            "rly_sta": 0x1F if self.ac_output_enabled else 0x11,
            "protect": 0,
            "fault": 0,
            "warning": warning,
            "bat_volt": battery_voltage,
            "bat_curr": battery_current,
            "bat_pwr": battery_power,
            "bat_temp": battery_temp,
            "soc": soc,
        }
        fault_log = "故障信息: 0x00000000\n\n当前无故障"
        warning_log = "告警信息: 0x00000000\n\n当前无告警"
        if warning:
            warning_log = "告警信息: 0x00000001\n\n代码 0: 市电过压"
        return info, fault_log, warning_log

    def current_wave_batch(self, names: list[str]) -> dict[str, float]:
        elapsed = time.monotonic() - self.started_at
        values: dict[str, float] = {}
        base_values = {
            "GridVoltage": 220.0 + 4.2 * math.sin(elapsed / 3.0),
            "GridCurrent": 5.0 + 0.9 * math.sin(elapsed / 2.0),
            "BusVoltage": 398.0 + 7.0 * math.sin(elapsed / 4.6),
            "BatteryVoltage": 51.3 + 0.5 * math.sin(elapsed / 7.2),
            "BatteryCurrent": -10.0 + 4.8 * math.sin(elapsed / 2.5),
            "OutputPowerLimit": 3200.0 + 50.0 * math.sin(elapsed / 11.0),
            "TempCoefficient": 1.015 + 0.01 * math.sin(elapsed / 5.0),
            "FanDuty": 42.0 + 8.0 * math.sin(elapsed / 3.3),
        }
        for name in names:
            if name in base_values:
                values[name] = base_values[name]
        return values

    def create_demo_firmware(self) -> FirmwareImage:
        body = bytes((index * 7 + 13) % 256 for index in range(16 * 1024))
        footer_without_crc = struct.pack(
            "<IBII16sB",
            int(time.time()) - 7200,
            FW_TYPE_IAP,
            0x01020304,
            len(body),
            b"DEMO20260421\x00\x00\x00\x00",
            0x02,
        )
        footer_crc = calculate_crc32(footer_without_crc)
        footer_raw = footer_without_crc + struct.pack("<I", footer_crc)
        data = body + footer_raw
        footer = FirmwareFooter(
            unix_time=int(time.time()) - 7200,
            fw_type=FW_TYPE_IAP,
            version=0x01020304,
            file_size=len(body),
            commit_id="DEMO20260421",
            module_id=0x02,
            crc32=footer_crc,
        )
        return FirmwareImage(
            path="demo_firmware_v1.2.3.4.bin",
            data=data,
            footer=footer,
            footer_crc_ok=True,
            payload_crc16=crc16_ccitt(data),
            warnings=[],
        )

    def get_black_box_records(self, start_offset: int, read_length: int) -> tuple[list[str], list[list[str]], dict[str, int]]:
        rows: list[list[str]] = []
        row_count = max(8, min(24, max(read_length // 8192, 10)))
        base_time = int(time.time()) - row_count * 90
        for index in range(row_count):
            elapsed = index / 3.0
            rows.append(
                [
                    str(base_time + index * 90),
                    f"{51.2 + 0.6 * math.sin(elapsed):.2f}",
                    f"{-9.5 + 4.0 * math.sin(elapsed / 1.7):.2f}",
                    f"{221.0 + 3.5 * math.sin(elapsed / 1.3):.2f}",
                    f"{1600.0 + 180.0 * math.sin(elapsed / 2.1):.1f}",
                    "RUN" if index % 5 else "WARN",
                ]
            )
        meta = {
            "start_offset": start_offset,
            "end_offset": start_offset + max(read_length, row_count * 128),
            "scanned_bytes": max(read_length, row_count * 128),
            "row_count": len(rows),
            "has_more": 1 if read_length < 0x40000 else 0,
        }
        return ["time", "BatVolt", "BatCurr", "AcVolt", "AcPower", "State"], rows, meta

    def list_scope_items(self) -> list[ScopeListItem]:
        return [ScopeListItem(scope_id=spec["scope_id"], name=name) for name, spec in self._scope_specs.items()]

    def get_scope_info(self, scope_id: int) -> ScopeInfo | None:
        spec = self._scope_spec_by_id(scope_id)
        if spec is None:
            return None
        return ScopeInfo(
            scope_id=scope_id,
            status=SCOPE_TOOL_STATUS_OK,
            state=int(spec["state"]),
            data_ready=bool(spec["data_ready"]),
            var_count=len(spec["var_names"]),
            sample_count=int(spec["sample_count"]),
            write_index=int(spec["sample_count"]) if spec["data_ready"] else 0,
            trigger_index=int(spec["trigger_index"]),
            trigger_post_cnt=max(int(spec["sample_count"]) - int(spec["trigger_index"]), 0),
            trigger_display_index=int(spec["trigger_index"]),
            sample_period_us=int(spec["sample_period_us"]),
            capture_tag=int(spec["capture_tag"]),
        )

    def get_scope_var_names(self, scope_id: int) -> list[str]:
        spec = self._scope_spec_by_id(scope_id)
        if spec is None:
            return []
        return list(spec["var_names"])

    def scope_command(self, scope_id: int, action: str) -> tuple[ScopeInfo | None, str]:
        spec = self._scope_spec_by_id(scope_id)
        if spec is None:
            return None, "演示录波对象不存在"
        if action == "start":
            spec["state"] = SCOPE_TOOL_STATE_RUNNING
            spec["data_ready"] = False
            return self.get_scope_info(scope_id), "演示录波已启动，等待触发"
        if action == "trigger":
            spec["state"] = SCOPE_TOOL_STATE_TRIGGERED
            spec["data_ready"] = True
            spec["capture_tag"] = int(spec["capture_tag"]) + 1
            return self.get_scope_info(scope_id), "演示录波已触发，可拉取数据"
        if action == "stop":
            spec["state"] = SCOPE_TOOL_STATE_IDLE
            spec["data_ready"] = True
            return self.get_scope_info(scope_id), "演示录波已停止，保留本次采样"
        if action == "reset":
            spec["state"] = SCOPE_TOOL_STATE_IDLE
            spec["data_ready"] = False
            spec["capture_tag"] = int(spec["capture_tag"]) + 1
            return self.get_scope_info(scope_id), "演示录波已复位"
        return self.get_scope_info(scope_id), "演示录波命令已处理"

    def build_scope_capture(self, scope_id: int, read_mode: int) -> ScopeCapture | None:
        spec = self._scope_spec_by_id(scope_id)
        if spec is None:
            return None
        if not spec["data_ready"] and read_mode == SCOPE_READ_MODE_NORMAL:
            return None
        capture_tag = int(spec["capture_tag"])
        sample_count = int(spec["sample_count"])
        sample_period_us = int(spec["sample_period_us"])
        var_names = list(spec["var_names"])
        samples: list[list[float]] = []
        for sample_index in range(sample_count):
            t = sample_index / max(sample_count - 1, 1)
            wave_a = math.sin(t * math.tau * 1.1)
            wave_b = math.sin(t * math.tau * 2.4 + 0.8)
            wave_c = math.sin(t * math.tau * 0.55 + 1.3)
            if scope_id == 1:
                row = [
                    220.0 + 8.0 * wave_a,
                    5.0 + 1.2 * wave_b,
                    50.0 + 0.15 * wave_c,
                    52.0 + 0.8 * wave_b,
                ]
            else:
                row = [
                    395.0 + 10.0 * wave_a,
                    42.0 + 5.0 * wave_b,
                    44.0 + 4.0 * wave_c,
                    36.0 + 2.0 * wave_a,
                ]
            samples.append(row)
        return ScopeCapture(
            scope_id=scope_id,
            scope_name=str(spec["name"]),
            capture_tag=capture_tag,
            read_mode=read_mode,
            sample_period_us=sample_period_us,
            sample_count=sample_count,
            trigger_display_index=int(spec["trigger_index"]),
            var_names=var_names,
            samples=samples,
            capture_index=1,
            capture_changed_during_pull=False,
        )

    def demo_device_version(self, target_addr: int) -> str:
        if target_addr == 0x03:
            return "PFC Demo v2.4.1"
        return "LLC Demo v1.8.6"

    def _build_initial_parameters(self) -> dict[str, ParameterEntry]:
        return {
            "GridVoltage": self._entry("GridVoltage", 6, 220.0, 180.0, 260.0, auto_report=True),
            "GridCurrent": self._entry("GridCurrent", 6, 5.1, 0.0, 32.0, auto_report=True),
            "BusVoltage": self._entry("BusVoltage", 6, 398.0, 320.0, 450.0, auto_report=True),
            "BatteryVoltage": self._entry("BatteryVoltage", 6, 51.4, 40.0, 60.0, auto_report=True),
            "BatteryCurrent": self._entry("BatteryCurrent", 6, -8.5, -120.0, 120.0, auto_report=True),
            "OutputPowerLimit": self._entry("OutputPowerLimit", 5, 3200, 500, 5000),
            "ChargeCurrentLimit": self._entry("ChargeCurrentLimit", 5, 45, 5, 100),
            "MpptEnable": self._entry("MpptEnable", 1, 1, 0, 1),
            "FanDuty": self._entry("FanDuty", 1, 42, 10, 100, auto_report=True),
            "TempCoefficient": self._entry("TempCoefficient", 6, 1.015, 0.8, 1.2, auto_report=True),
            "SaveParameters": self._entry("SaveParameters", 7, 0, 0, 0),
            "FactoryReset": self._entry("FactoryReset", 7, 0, 0, 0),
        }

    def _build_scope_specs(self) -> dict[str, dict[str, object]]:
        return {
            "INV_DEMO_MAIN": {
                "scope_id": 1,
                "name": "INV_DEMO_MAIN",
                "state": SCOPE_TOOL_STATE_IDLE,
                "data_ready": True,
                "var_names": ["VacInv", "IacInv", "FreqInv", "BatVolt"],
                "sample_count": 240,
                "sample_period_us": 500,
                "trigger_index": 72,
                "capture_tag": 3,
            },
            "PWR_STAGE_DEMO": {
                "scope_id": 2,
                "name": "PWR_STAGE_DEMO",
                "state": SCOPE_TOOL_STATE_IDLE,
                "data_ready": True,
                "var_names": ["BusVolt", "PfcTemp", "LlcTemp", "MpptTemp"],
                "sample_count": 180,
                "sample_period_us": 800,
                "trigger_index": 54,
                "capture_tag": 7,
            },
        }

    def _update_dynamic_parameters(self) -> None:
        elapsed = time.monotonic() - self.started_at
        self._set_value("GridVoltage", 220.0 + 4.2 * math.sin(elapsed / 3.0))
        self._set_value("GridCurrent", 5.0 + 0.9 * math.sin(elapsed / 2.0))
        self._set_value("BusVoltage", 398.0 + 7.0 * math.sin(elapsed / 4.6))
        self._set_value("BatteryVoltage", 51.3 + 0.5 * math.sin(elapsed / 7.2))
        self._set_value("BatteryCurrent", -10.0 + 4.8 * math.sin(elapsed / 2.5))
        self._set_value("FanDuty", max(10.0, min(100.0, 42.0 + 8.0 * math.sin(elapsed / 3.3))))
        self._set_value("TempCoefficient", 1.015 + 0.01 * math.sin(elapsed / 5.0))

    def _scope_spec_by_id(self, scope_id: int) -> dict[str, object] | None:
        for spec in self._scope_specs.values():
            if int(spec["scope_id"]) == scope_id:
                return spec
        return None

    def _set_value(self, name: str, value: float) -> None:
        entry = self._parameters.get(name)
        if entry is None or entry.is_command:
            return
        self._parameters[name] = replace(entry, data_raw=value_to_u32(str(value), entry.type_id))

    def _entry(
        self,
        name: str,
        type_id: int,
        data: float | int,
        minimum: float | int,
        maximum: float | int,
        *,
        auto_report: bool = False,
    ) -> ParameterEntry:
        return ParameterEntry(
            name=name,
            type_id=type_id,
            data_raw=value_to_u32(str(data), type_id),
            min_raw=value_to_u32(str(minimum), type_id),
            max_raw=value_to_u32(str(maximum), type_id),
            auto_report=auto_report,
        )
