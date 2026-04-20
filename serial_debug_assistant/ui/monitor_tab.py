from __future__ import annotations

import configparser
from pathlib import Path
import re
import tkinter as tk
from tkinter import ttk

from serial_debug_assistant.i18n import I18nManager


class SerialMonitorTab(ttk.Frame):
    PRESET_ROWS = 50
    PRESET_HEX_WIDTH = 52
    PRESET_CRLF_WIDTH = 64
    PRESET_SEND_WIDTH = 76
    LOG_TEXT_LIMIT = 200_000
    LOG_TEXT_TRIM_TO = 160_000

    def __init__(
        self,
        master,
        *,
        on_send,
        on_send_preset,
        on_reset_count,
        config_path: Path,
        on_layout_change=None,
        receive_hex_var: tk.BooleanVar | None = None,
        send_hex_var: tk.BooleanVar | None = None,
        i18n: I18nManager,
    ) -> None:
        super().__init__(master, style="Panel.TFrame", padding=12)
        self.i18n = i18n
        self._translatable_widgets: list[tuple[object, str, str]] = []
        self.on_send = on_send
        self.on_send_preset = on_send_preset
        self.on_reset_count = on_reset_count
        self.config_path = config_path
        self.on_layout_change = on_layout_change
        self.preset_hex_vars: list[tk.BooleanVar] = []
        self.preset_line_vars: list[tk.BooleanVar] = []
        self.preset_text_vars: list[tk.StringVar] = []
        self._suspend_save = False
        self._saved_sash_y: int | None = None
        self._saved_sash_ratio: float | None = None
        self._last_sash_y: int | None = None
        self._last_layout_signature: tuple[int, ...] | None = None
        self._layout_restored = False
        self.receive_hex_var = receive_hex_var or tk.BooleanVar(value=False)
        self.send_hex_var = send_hex_var or tk.BooleanVar(value=False)
        self.receive_hex_var.trace_add("write", self._on_receive_mode_change)
        self._build()
        self._load_preset_config()

    def _build(self) -> None:
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        paned = tk.PanedWindow(
            self,
            orient="vertical",
            sashrelief="raised",
            sashwidth=6,
            bg="#c7d6e5",
            bd=0,
            relief="flat",
        )
        paned.grid(row=0, column=0, sticky="nsew")
        self.main_paned = paned
        self.main_paned.bind("<Configure>", self._on_main_paned_configure)
        self.main_paned.bind("<ButtonRelease-1>", self._on_main_paned_release)

        io_container = ttk.Frame(self, style="Panel.TFrame")
        io_container.rowconfigure(0, weight=1)
        io_container.columnconfigure(0, weight=1)
        self.io_container = io_container

        io_paned = tk.PanedWindow(
            io_container,
            orient="horizontal",
            sashrelief="raised",
            sashwidth=6,
            bg="#c7d6e5",
            bd=0,
            relief="flat",
        )
        io_paned.grid(row=0, column=0, sticky="nsew")
        self.io_paned = io_paned

        send_log_container = ttk.LabelFrame(io_container, text=self.i18n.translate_text("发送信息"), style="Section.TLabelframe", padding=8)
        self._remember_text(send_log_container, "发送信息")
        send_log_container.rowconfigure(1, weight=1)
        send_log_container.columnconfigure(0, weight=1)
        self.send_log_container = send_log_container

        send_log_toolbar = ttk.Frame(send_log_container, style="Panel.TFrame")
        send_log_toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Radiobutton(send_log_toolbar, text="ASCII", value=False, variable=self.send_hex_var).grid(row=0, column=0, padx=(0, 8))
        ttk.Radiobutton(send_log_toolbar, text="HEX", value=True, variable=self.send_hex_var).grid(row=0, column=1)

        self.send_log_text = tk.Text(
            send_log_container,
            wrap="char",
            relief="flat",
            borderwidth=0,
            font=("Consolas", 11),
            bg="#f8fbfe",
            fg="#122033",
            insertbackground="#1f6feb",
            padx=12,
            pady=12,
        )
        self.send_log_text.grid(row=1, column=0, sticky="nsew")
        self.send_log_text.tag_configure("tx", foreground="#0f766e")

        send_log_scroll = ttk.Scrollbar(send_log_container, orient="vertical", command=self.send_log_text.yview)
        send_log_scroll.grid(row=1, column=1, sticky="ns")
        self.send_log_text.configure(yscrollcommand=send_log_scroll.set)

        receive_container = ttk.LabelFrame(io_container, text=self.i18n.translate_text("接收信息"), style="Section.TLabelframe", padding=8)
        self._remember_text(receive_container, "接收信息")
        receive_container.rowconfigure(1, weight=1)
        receive_container.columnconfigure(0, weight=1)
        self.receive_container = receive_container

        receive_toolbar = ttk.Frame(receive_container, style="Panel.TFrame")
        receive_toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Radiobutton(receive_toolbar, text="ASCII", value=False, variable=self.receive_hex_var).grid(row=0, column=0, padx=(0, 8))
        ttk.Radiobutton(receive_toolbar, text="HEX", value=True, variable=self.receive_hex_var).grid(row=0, column=1)

        self.receive_text = tk.Text(
            receive_container,
            wrap="char",
            relief="flat",
            borderwidth=0,
            font=("Consolas", 11),
            bg="#f8fbfe",
            fg="#122033",
            insertbackground="#1f6feb",
            padx=12,
            pady=12,
        )
        self.receive_text.grid(row=1, column=0, sticky="nsew")
        self.receive_text.tag_configure("rx", foreground="#122033")

        recv_scroll = ttk.Scrollbar(receive_container, orient="vertical", command=self.receive_text.yview)
        recv_scroll.grid(row=1, column=1, sticky="ns")
        self.receive_text.configure(yscrollcommand=recv_scroll.set)

        send_container = ttk.Frame(self, style="Panel.TFrame", height=240)
        send_container.rowconfigure(0, weight=1)
        send_container.columnconfigure(0, weight=1)
        send_container.grid_propagate(False)
        self.send_container = send_container

        send_tabs = ttk.Notebook(send_container, height=210)
        send_tabs.grid(row=0, column=0, sticky="nsew")
        self.send_tabs = send_tabs

        manual_tab = ttk.Frame(send_tabs, style="Panel.TFrame", padding=8)
        manual_tab.rowconfigure(0, weight=1)
        manual_tab.columnconfigure(0, weight=1)
        send_tabs.add(manual_tab, text=self.i18n.translate_text("手动发送"))
        self.manual_tab = manual_tab

        manual_editor = ttk.Frame(manual_tab, style="Panel.TFrame")
        manual_editor.grid(row=0, column=0, sticky="nsew")
        manual_editor.rowconfigure(0, weight=1)
        manual_editor.columnconfigure(0, weight=1)

        self.send_text = tk.Text(
            manual_editor,
            height=8,
            wrap="word",
            relief="solid",
            borderwidth=1,
            font=("Consolas", 11),
            bg="#f8fbfe",
            fg="#122033",
            insertbackground="#1f6feb",
            padx=10,
            pady=8,
        )
        self.send_text.grid(row=0, column=0, sticky="nsew")

        send_scroll = ttk.Scrollbar(manual_editor, orient="vertical", command=self.send_text.yview)
        send_scroll.grid(row=0, column=1, sticky="ns")
        self.send_text.configure(yscrollcommand=send_scroll.set)

        send_actions = ttk.Frame(manual_tab, style="Panel.TFrame")
        send_actions.grid(row=0, column=1, sticky="ns", padx=(10, 0))
        send_actions.rowconfigure(1, weight=1)

        self.send_button = ttk.Button(
            send_actions,
            text=self.i18n.translate_text("Send"),
            command=self.on_send,
            style="Accent.TButton",
            width=10,
        )
        self.send_button.grid(row=0, column=0, sticky="ew")
        self._remember_text(self.send_button, "Send")
        self.reset_count_button = ttk.Button(
            send_actions,
            text=self.i18n.translate_text("Reset count"),
            command=self.on_reset_count,
            width=10,
        )
        self.reset_count_button.grid(row=1, column=0, sticky="sew", pady=(8, 0))
        self._remember_text(self.reset_count_button, "Reset count")

        preset_tab = ttk.Frame(send_tabs, style="Panel.TFrame", padding=8)
        preset_tab.rowconfigure(0, weight=1)
        preset_tab.columnconfigure(0, weight=1)
        send_tabs.add(preset_tab, text=self.i18n.translate_text("快捷发送"))
        self.preset_tab = preset_tab

        preset_frame = ttk.Frame(preset_tab, style="Panel.TFrame")
        preset_frame.grid(row=0, column=0, sticky="nsew")
        preset_frame.rowconfigure(1, weight=1)
        preset_frame.columnconfigure(0, weight=1)

        preset_header = ttk.Frame(preset_frame, style="Panel.TFrame")
        preset_header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self._configure_preset_columns(preset_header)
        hex_label = ttk.Label(preset_header, text="HEX", anchor="center")
        hex_label.grid(row=0, column=0, sticky="ew")
        payload_label = ttk.Label(preset_header, text=self.i18n.translate_text("发送内容"), anchor="w")
        payload_label.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        send_label = ttk.Label(preset_header, text=self.i18n.translate_text("发送"), anchor="center")
        send_label.grid(row=0, column=3, sticky="ew", padx=(8, 0))
        ttk.Label(preset_header, text="\\r\\n", anchor="center").grid(row=0, column=2, sticky="ew", padx=(8, 0))
        self._remember_text(payload_label, "发送内容")
        self._remember_text(send_label, "发送")

        self.preset_canvas = tk.Canvas(
            preset_frame,
            bg="#f4f8fc",
            highlightthickness=1,
            highlightbackground="#bfd0e3",
            relief="flat",
            height=160,
        )
        self.preset_canvas.grid(row=1, column=0, sticky="nsew")
        preset_scroll = ttk.Scrollbar(preset_frame, orient="vertical", command=self.preset_canvas.yview)
        preset_scroll.grid(row=1, column=1, sticky="ns")
        self.preset_canvas.configure(yscrollcommand=preset_scroll.set)

        self.preset_inner = ttk.Frame(self.preset_canvas, style="Panel.TFrame")
        self.preset_inner.columnconfigure(0, weight=1)
        self.preset_window = self.preset_canvas.create_window((0, 0), window=self.preset_inner, anchor="nw")
        self.preset_inner.bind("<Configure>", self._on_preset_frame_configure)
        self.preset_canvas.bind("<Configure>", self._on_preset_canvas_configure)
        self.preset_canvas.bind("<MouseWheel>", self._on_preset_mousewheel)

        for index in range(self.PRESET_ROWS):
            hex_var = tk.BooleanVar(value=False)
            line_var = tk.BooleanVar(value=True)
            text_var = tk.StringVar(value="")
            hex_var.trace_add("write", lambda *_args: self._save_preset_config())
            line_var.trace_add("write", lambda *_args: self._save_preset_config())
            text_var.trace_add("write", lambda *_args: self._save_preset_config())
            self.preset_hex_vars.append(hex_var)
            self.preset_line_vars.append(line_var)
            self.preset_text_vars.append(text_var)

            row = ttk.Frame(self.preset_inner, style="Panel.TFrame")
            row.grid(row=index, column=0, sticky="ew", pady=2)
            self._configure_preset_columns(row)

            hex_button = ttk.Checkbutton(row, variable=hex_var)
            hex_button.grid(row=0, column=0, sticky="n")

            entry = ttk.Entry(row, textvariable=text_var, font=("Consolas", 10))
            entry.grid(row=0, column=1, sticky="ew", padx=(6, 0))

            line_button = ttk.Checkbutton(row, variable=line_var)
            line_button.grid(row=0, column=2, sticky="n", padx=(8, 0))

            send_button = ttk.Button(
                row,
                text=str(index + 1),
                width=5,
                command=lambda item=index: self._send_preset(item),
            )
            send_button.grid(row=0, column=3, sticky="ew", padx=(8, 0))

            for widget in (row, hex_button, entry, line_button, send_button):
                widget.bind("<MouseWheel>", self._on_preset_mousewheel)

        preset_actions = ttk.Frame(preset_tab, style="Panel.TFrame")
        preset_actions.grid(row=1, column=0, sticky="e", pady=(8, 0))
        self.preset_reset_count_button = ttk.Button(
            preset_actions,
            text=self.i18n.translate_text("Reset count"),
            command=self.on_reset_count,
            width=12,
        )
        self.preset_reset_count_button.grid(row=0, column=0)
        self._remember_text(self.preset_reset_count_button, "Reset count")

        io_paned.add(send_log_container, minsize=280, stretch="always")
        io_paned.add(receive_container, minsize=280, stretch="always")

        paned.add(io_container, minsize=260, stretch="always")
        paned.add(send_container, minsize=170, stretch="never")
        self._update_receive_wrap()
        self.after(80, self._restore_or_set_default_pane_ratio)

    def append_receive(self, text: str, source: str = "rx", ensure_separate_line: bool = False) -> None:
        self.append_receive_batch([text], source=source, ensure_separate_line=ensure_separate_line)

    def append_receive_batch(
        self,
        chunks: list[str],
        *,
        source: str = "rx",
        ensure_separate_line: bool = False,
    ) -> None:
        if not chunks:
            return
        target = self.send_log_text if source == "tx" else self.receive_text
        tag = "tx" if source == "tx" else "rx"
        text = "".join(chunks)
        if ensure_separate_line and text and not text.startswith("\n"):
            last_char = target.get("end-2c", "end-1c")
            if last_char and last_char != "\n":
                text = "\n" + text
        target.insert("end", text, tag)
        self._trim_log_text(target)
        target.see("end")

    def clear_receive(self) -> None:
        self.send_log_text.delete("1.0", "end")
        self.receive_text.delete("1.0", "end")

    def get_send_text(self) -> str:
        return self.send_text.get("1.0", "end-1c")

    def send_hex_enabled(self) -> bool:
        return bool(self.send_hex_var.get())

    def receive_hex_enabled(self) -> bool:
        return bool(self.receive_hex_var.get())

    def get_receive_hex_bytes_per_line(self) -> int:
        return 0

    def refresh_texts(self) -> None:
        for widget, source_text, option in self._translatable_widgets:
            widget.configure(**{option: self.i18n.translate_text(source_text)})
        self.send_tabs.tab(self.manual_tab, text=self.i18n.translate_text("手动发送"))
        self.send_tabs.tab(self.preset_tab, text=self.i18n.translate_text("快捷发送"))

    def _remember_text(self, widget: object, source_text: str, option: str = "text") -> None:
        self._translatable_widgets.append((widget, source_text, option))

    def _on_receive_mode_change(self, *_args) -> None:
        self._update_receive_wrap()

    def _update_receive_wrap(self) -> None:
        self.receive_text.configure(wrap="char")

    def _trim_log_text(self, target: tk.Text) -> None:
        current_length = int(target.count("1.0", "end-1c", "chars")[0])
        if current_length <= self.LOG_TEXT_LIMIT:
            return
        trim_chars = current_length - self.LOG_TEXT_TRIM_TO
        target.delete("1.0", f"1.0 + {trim_chars} chars")

    def _send_preset(self, index: int) -> None:
        raw_text = self.preset_text_vars[index].get()
        self.on_send_preset(index, raw_text, self.preset_hex_vars[index].get(), self.preset_line_vars[index].get())

    def _restore_or_set_default_pane_ratio(self) -> None:
        total_height = self.main_paned.winfo_height()
        if total_height < 300:
            self.after(80, self._restore_or_set_default_pane_ratio)
            return
        if self._saved_sash_ratio is not None:
            sash_y = max(220, min(int(total_height * self._saved_sash_ratio), max(total_height - 170, 220)))
            self.main_paned.sash_place(0, 0, sash_y)
            self._last_sash_y = sash_y
            self._layout_restored = True
            self.after_idle(lambda: self._report_layout("restore_ratio"))
            return
        if self._saved_sash_y is not None:
            sash_y = max(220, min(self._saved_sash_y, max(total_height - 170, 220)))
            self.main_paned.sash_place(0, 0, sash_y)
            self._last_sash_y = sash_y
            self._layout_restored = True
            self.after_idle(lambda: self._report_layout("restore_pixel"))
            return
        self._set_default_pane_ratio()

    def _set_default_pane_ratio(self) -> None:
        total_height = self.main_paned.winfo_height()
        if total_height < 300:
            self.after(80, self._set_default_pane_ratio)
            return
        top_height = max(int(total_height * 0.78), 300)
        self.main_paned.sash_place(0, 0, top_height)
        self._last_sash_y = top_height
        self._layout_restored = True
        self._report_layout("default")

    def _on_main_paned_release(self, _event) -> None:
        try:
            _x, sash_y = self.main_paned.sash_coord(0)
        except tk.TclError:
            return
        if sash_y != self._last_sash_y:
            self._last_sash_y = sash_y
            self._saved_sash_y = sash_y
            total_height = self.main_paned.winfo_height()
            if total_height > 0:
                self._saved_sash_ratio = sash_y / total_height
            self._save_preset_config()
            self.after_idle(lambda: self._report_layout("manual"))

    def _on_main_paned_configure(self, _event) -> None:
        if not self._layout_restored and self.main_paned.winfo_height() >= 300:
            self.after_idle(self._restore_or_set_default_pane_ratio)
            return
        self.after_idle(lambda: self._report_layout("configure"))

    def _report_layout(self, source: str) -> None:
        if self.on_layout_change is None:
            return
        try:
            _x, sash_y = self.main_paned.sash_coord(0)
        except tk.TclError:
            sash_y = self._last_sash_y or 0
        self._last_sash_y = sash_y
        total_height = max(self.main_paned.winfo_height(), 0)
        top_height = max(self.receive_container.winfo_height(), 0)
        bottom_height = max(self.send_container.winfo_height(), 0)
        io_width = max(self.io_container.winfo_width(), 0)
        receive_width = max(self.receive_container.winfo_width(), 0)
        send_width = max(self.send_container.winfo_width(), 0)
        preset_tab_height = max(self.preset_tab.winfo_height(), 0)
        receive_reqheight = self.receive_container.winfo_reqheight()
        send_reqheight = self.send_container.winfo_reqheight()
        io_reqheight = self.io_container.winfo_reqheight()
        preset_reqheight = self.preset_tab.winfo_reqheight()
        signature = (
            total_height,
            sash_y,
            top_height,
            bottom_height,
            io_width,
            receive_width,
            send_width,
            preset_tab_height,
            receive_reqheight,
            send_reqheight,
            io_reqheight,
            preset_reqheight,
        )
        if source == "configure" and signature == self._last_layout_signature:
            return
        self._last_layout_signature = signature
        self.on_layout_change(
            {
                "source": source,
                "total_height": total_height,
                "sash_y": sash_y,
                "top_height": top_height,
                "bottom_height": bottom_height,
                "io_width": io_width,
                "receive_width": receive_width,
                "send_width": send_width,
                "preset_tab_height": preset_tab_height,
                "receive_reqheight": receive_reqheight,
                "send_reqheight": send_reqheight,
                "io_reqheight": io_reqheight,
                "preset_reqheight": preset_reqheight,
            }
        )

    def _configure_preset_columns(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(0, minsize=self.PRESET_HEX_WIDTH, weight=0)
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(2, minsize=self.PRESET_CRLF_WIDTH, weight=0)
        frame.columnconfigure(3, minsize=self.PRESET_SEND_WIDTH, weight=0)

    def _on_preset_frame_configure(self, _event) -> None:
        self.preset_canvas.configure(scrollregion=self.preset_canvas.bbox("all"))

    def _on_preset_canvas_configure(self, event) -> None:
        self.preset_canvas.itemconfigure(self.preset_window, width=event.width)

    def _on_preset_mousewheel(self, event) -> None:
        delta = event.delta
        if delta == 0:
            return
        self.preset_canvas.yview_scroll(int(-delta / 120), "units")

    def _load_config_parser(self) -> tuple[configparser.ConfigParser, bool]:
        config = configparser.ConfigParser()
        if not self.config_path.exists():
            return config, False
        try:
            with self.config_path.open("r", encoding="utf-8") as handle:
                config.read_file(handle)
            return config, False
        except (OSError, UnicodeError, configparser.Error):
            repaired_text = self._repair_config_text()
            repaired = configparser.ConfigParser()
            try:
                repaired.read_string(repaired_text)
            except configparser.Error:
                return configparser.ConfigParser(), False
            return repaired, True

    def _repair_config_text(self) -> str:
        try:
            raw_text = self.config_path.read_text(encoding="utf-8")
        except OSError:
            return ""

        repaired_lines: list[str] = []
        section_pattern = re.compile(r"\[(preset_\d+|layout)\]\s*$")
        for line in raw_text.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("["):
                match = section_pattern.search(stripped)
                if match:
                    repaired_lines.append(match.group(0))
                    continue
            repaired_lines.append(line)
        return "\n".join(repaired_lines) + ("\n" if raw_text.endswith(("\n", "\r")) else "")

    def _load_preset_config(self) -> None:
        self._suspend_save = True
        should_rewrite = False
        try:
            config, should_rewrite = self._load_config_parser()
            for index in range(self.PRESET_ROWS):
                section = f"preset_{index + 1}"
                text_value = ""
                hex_value = False
                line_value = True
                if config.has_section(section):
                    text_value = config.get(section, "text", fallback="")
                    hex_value = config.getboolean(section, "hex", fallback=False)
                    line_value = config.getboolean(section, "crlf", fallback=True)
                self.preset_hex_vars[index].set(hex_value)
                self.preset_line_vars[index].set(line_value)
                self.preset_text_vars[index].set(text_value)
            if config.has_section("layout"):
                self._saved_sash_y = config.getint("layout", "main_sash_y", fallback=0) or None
                ratio_value = config.get("layout", "main_sash_ratio", fallback="").strip()
                if ratio_value:
                    try:
                        ratio = float(ratio_value)
                    except ValueError:
                        ratio = 0.0
                    self._saved_sash_ratio = ratio if 0.0 < ratio < 1.0 else None
        finally:
            self._suspend_save = False
        if should_rewrite:
            self._save_preset_config()

    def _save_preset_config(self) -> None:
        if self._suspend_save:
            return
        config = configparser.ConfigParser()
        for index in range(self.PRESET_ROWS):
            section = f"preset_{index + 1}"
            config[section] = {
                "hex": "true" if self.preset_hex_vars[index].get() else "false",
                "crlf": "true" if self.preset_line_vars[index].get() else "false",
                "text": self.preset_text_vars[index].get(),
            }
        config["layout"] = {
            "main_sash_y": str(self._saved_sash_y or self._last_sash_y or 0),
            "main_sash_ratio": f"{(self._saved_sash_ratio or 0.78):.4f}",
        }
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config_path.open("w", encoding="utf-8") as handle:
            config.write(handle)
