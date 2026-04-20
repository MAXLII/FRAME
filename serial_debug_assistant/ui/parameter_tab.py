from __future__ import annotations

from typing import Callable
import tkinter as tk
from tkinter import ttk

from serial_debug_assistant.i18n import I18nManager
from serial_debug_assistant.models import ParameterEntry
from serial_debug_assistant.protocol import TYPE_NAMES, format_value


WAVE_TAG = ("wave", "#e4f7ee", "#0f766e")


class ParameterReadWriteTab(ttk.Frame):
    def __init__(
        self,
        master,
        *,
        on_read_list: Callable[[], None],
        on_read_param: Callable[[str], None],
        on_write_param: Callable[[str], None],
        on_toggle_wave: Callable[[str, bool], None],
        i18n: I18nManager,
    ) -> None:
        super().__init__(master, style="Panel.TFrame", padding=12)
        self.i18n = i18n
        self._translatable_widgets: list[tuple[object, str, str]] = []
        self.on_read_list = on_read_list
        self.on_read_param = on_read_param
        self.on_write_param = on_write_param
        self.on_toggle_wave = on_toggle_wave

        self.module_addr_var = tk.StringVar(value="2")
        self.dynamic_addr_var = tk.StringVar(value="0")
        self.search_var = tk.StringVar()
        self.count_var = tk.StringVar(value="0/0")
        self.message_var = tk.StringVar(value=self.i18n.translate_text("参数页就绪"))
        self.parameters: dict[str, ParameterEntry] = {}
        self._busy_name: str | None = None
        self._invalid_name: str | None = None
        self._tree_style = "Param.Treeview"
        self._tree_selected_bg = "#dce9f7"
        self._tree_selected_fg = "#ffffff"

        self._build()
        self.search_var.trace_add("write", self._on_search_changed)

    def _build(self) -> None:
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        toolbar = ttk.LabelFrame(self, text=self.i18n.translate_text("参数筛选"), style="Section.TLabelframe", padding=12)
        self._remember_text(toolbar, "参数筛选")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        toolbar.columnconfigure(8, weight=1)

        read_list_button = ttk.Button(toolbar, text=self.i18n.translate_text("读取参数列表"), command=self.on_read_list, style="Accent.TButton")
        self._remember_text(read_list_button, "读取参数列表")
        read_list_button.grid(
            row=0,
            column=0,
            padx=(0, 12),
        )
        ttk.Label(toolbar, textvariable=self.count_var, style="Header.TLabel").grid(row=0, column=1, padx=(0, 20))
        module_label = ttk.Label(toolbar, text=self.i18n.translate_text("模块地址:"), style="Header.TLabel")
        self._remember_text(module_label, "模块地址:")
        module_label.grid(row=0, column=2)
        ttk.Entry(toolbar, textvariable=self.module_addr_var, width=8).grid(row=0, column=3, padx=(6, 12))
        dynamic_label = ttk.Label(toolbar, text=self.i18n.translate_text("动态地址:"), style="Header.TLabel")
        self._remember_text(dynamic_label, "动态地址:")
        dynamic_label.grid(row=0, column=4)
        ttk.Entry(toolbar, textvariable=self.dynamic_addr_var, width=8).grid(row=0, column=5, padx=(6, 24))
        search_label = ttk.Label(toolbar, text=self.i18n.translate_text("参数搜索"), style="Header.TLabel")
        self._remember_text(search_label, "参数搜索")
        search_label.grid(row=0, column=6)
        ttk.Entry(toolbar, textvariable=self.search_var, width=28).grid(row=0, column=7, padx=(8, 0))
        self.read_button = ttk.Button(toolbar, text=self.i18n.translate_text("读取"), width=8, command=self._invoke_selected_read, state="disabled")
        self._remember_text(self.read_button, "读取")
        self.read_button.grid(row=0, column=9, padx=(12, 6), sticky="e")
        self.action_button = ttk.Button(toolbar, text=self.i18n.translate_text("写入"), width=8, command=self._invoke_selected_action, state="disabled")
        self.action_button.grid(row=0, column=10, padx=(0, 6), sticky="e")

        table_frame = ttk.LabelFrame(self, text=self.i18n.translate_text("参数表"), style="Section.TLabelframe", padding=10)
        self._remember_text(table_frame, "参数表")
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        columns = ("name", "type", "data", "min", "max")
        style = ttk.Style(self)
        style.configure(self._tree_style, rowheight=28)
        style.map(
            self._tree_style,
            background=[("selected", self._tree_selected_bg)],
            foreground=[("selected", "#112033")],
        )
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse", height=20, style=self._tree_style)
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.tag_configure("dirty", foreground="#d14343")
        self.tree.tag_configure("busy", background="#fde8e8", foreground="#a83838")
        self.tree.tag_configure("invalid", background="#fff1cc", foreground="#9a6700")
        self.tree.tag_configure(WAVE_TAG[0], background=WAVE_TAG[1], foreground=WAVE_TAG[2])

        headings = {
            "name": "参数名称",
            "type": "类型",
            "data": "数据",
            "min": "最小值",
            "max": "最大值",
        }
        widths = {
            "name": 260,
            "type": 90,
            "data": 120,
            "min": 120,
            "max": 120,
        }
        for column in columns:
            self.tree.heading(column, text=self.i18n.translate_text(headings[column]))
            self.tree.column(column, width=widths[column], anchor="center")

        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self._on_tree_scroll)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self.after_idle(self._update_action_bar))
        self.tree.bind("<Configure>", lambda _event: self.after_idle(self._update_action_bar))
        self.tree.bind("<MouseWheel>", lambda _event: self.after_idle(self._update_action_bar))

    def get_target_address(self) -> tuple[int, int]:
        return int(self.module_addr_var.get() or "0"), int(self.dynamic_addr_var.get() or "0")

    def set_expected_count(self, received: int, total: int) -> None:
        self.count_var.set(f"{received}/{total}")

    def set_message(self, message: str) -> None:
        self.message_var.set(self.i18n.translate_text(message))

    def set_parameters(self, parameters: dict[str, ParameterEntry]) -> None:
        self.parameters = dict(sorted(parameters.items(), key=lambda item: item[0].lower()))
        self._refresh_rows()

    def add_or_update_parameter(self, entry: ParameterEntry) -> None:
        self.parameters[entry.name] = entry
        if not self._matches_filter(entry.name):
            if self.tree.exists(entry.name):
                self.tree.delete(entry.name)
            return

        values = self._entry_values(entry)
        tags = self._entry_tags(entry.name, entry.dirty)
        if self.tree.exists(entry.name):
            for column, value in zip(("name", "type", "data", "min", "max"), values):
                self.tree.set(entry.name, column, value)
            self.tree.item(entry.name, tags=tags)
        else:
            self.tree.insert("", "end", iid=entry.name, values=values, tags=tags)
        self.after_idle(self._update_action_bar)

    def update_parameter(self, entry: ParameterEntry) -> None:
        self.add_or_update_parameter(entry)

    def update_wave_state(self, name: str, enabled: bool) -> None:
        entry = self.parameters.get(name)
        if entry is not None:
            entry.auto_report = enabled
        if self.tree.exists(name):
            self.tree.item(name, tags=self._entry_tags(name, entry.dirty if entry else False))
        self.after_idle(self._update_action_bar)

    def clear_parameters(self) -> None:
        self.parameters.clear()
        self._busy_name = None
        self._invalid_name = None
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.set_expected_count(0, 0)
        self._update_action_bar()

    def get_selected_name(self) -> str | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return selection[0]

    def _entry_values(self, entry: ParameterEntry) -> tuple[str, ...]:
        data_text = "/" if entry.is_command else format_value(entry.data_raw, entry.type_id)
        min_text = "/" if entry.is_command else format_value(entry.min_raw, entry.type_id)
        max_text = "/" if entry.is_command else format_value(entry.max_raw, entry.type_id)
        return (entry.name, TYPE_NAMES.get(entry.type_id, str(entry.type_id)), data_text, min_text, max_text)

    def _matches_filter(self, name: str) -> bool:
        keyword = self.search_var.get().strip().lower()
        return not keyword or keyword in name.lower()

    def _refresh_rows(self, preserve_selection: str | None = None) -> None:
        selected_name = preserve_selection or self.get_selected_name()
        for item in self.tree.get_children():
            self.tree.delete(item)

        for name, entry in sorted(self.parameters.items(), key=lambda item: item[0].lower()):
            if not self._matches_filter(name):
                continue
            self.tree.insert(
                "",
                "end",
                iid=name,
                values=self._entry_values(entry),
                tags=self._entry_tags(name, entry.dirty),
            )

        if selected_name and self.tree.exists(selected_name):
            self.tree.selection_set(selected_name)
        self.after_idle(self._update_action_bar)

    def _on_search_changed(self, *_args) -> None:
        self._refresh_rows()

    def _on_tree_double_click(self, event) -> None:
        row_id = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if row_id and column == "#1":
            self._toggle_wave_for_parameter(row_id)
            return
        if row_id and column in {"#3", "#4", "#5"}:
            self._edit_value_cell(row_id, column)

    def _edit_value_cell(self, name: str, column_id: str) -> None:
        entry = self.parameters.get(name)
        if entry is None or entry.is_command:
            return

        column_name = {"#3": "data", "#4": "min", "#5": "max"}.get(column_id)
        if column_name is None:
            return

        bbox = self.tree.bbox(name, column_id)
        if not bbox:
            return

        x, y, width, height = bbox
        editor = ttk.Entry(self.tree)
        current_value = str(self.tree.set(name, column_name))
        if not current_value:
            raw_value = {
                "data": entry.data_raw,
                "min": entry.min_raw,
                "max": entry.max_raw,
            }[column_name]
            current_value = format_value(raw_value, entry.type_id)
        editor.insert(0, current_value)
        editor.place(x=x, y=y, width=width, height=height)
        editor.focus_set()
        editor.select_range(0, "end")

        finished = False

        def close_editor(*, save: bool) -> None:
            nonlocal finished
            if finished or not editor.winfo_exists():
                return
            finished = True
            new_value = editor.get().strip()
            editor.destroy()
            if not save or not new_value:
                return
            self.tree.set(name, column_name, new_value)
            cached = self.parameters[name]
            cached.dirty = True
            if self.tree.exists(name):
                self.tree.item(name, tags=self._entry_tags(name, True))

        editor.bind("<Return>", lambda _event: close_editor(save=True))
        editor.bind("<Escape>", lambda _event: close_editor(save=False))
        editor.bind("<FocusOut>", lambda _event: close_editor(save=True))

    def get_pending_display_values(self, name: str) -> tuple[str, str, str] | None:
        if not self.tree.exists(name):
            return None
        return (
            str(self.tree.set(name, "data")),
            str(self.tree.set(name, "min")),
            str(self.tree.set(name, "max")),
        )

    def mark_busy(self, name: str) -> None:
        self._busy_name = name
        if self._invalid_name == name:
            self._invalid_name = None
        if self.tree.exists(name):
            entry = self.parameters.get(name)
            self.tree.item(name, tags=self._entry_tags(name, entry.dirty if entry else False))
            self.tree.selection_set(name)
            self.tree.see(name)
        self._update_tree_selection_style()
        self.after_idle(self._update_action_bar)

    def clear_busy(self, name: str | None = None) -> None:
        if name is not None and self._busy_name != name:
            return
        busy_name = self._busy_name
        self._busy_name = None
        if busy_name and self.tree.exists(busy_name):
            entry = self.parameters.get(busy_name)
            self.tree.item(busy_name, tags=self._entry_tags(busy_name, entry.dirty if entry else False))
        self._update_tree_selection_style()
        self.after_idle(self._update_action_bar)

    def mark_invalid(self, name: str) -> None:
        self._invalid_name = name
        if self.tree.exists(name):
            entry = self.parameters.get(name)
            self.tree.item(name, tags=self._entry_tags(name, entry.dirty if entry else False))
            self.tree.selection_set(name)
            self.tree.see(name)
        self._update_tree_selection_style()
        self.after_idle(self._update_action_bar)

    def clear_invalid(self, name: str | None = None) -> None:
        if name is not None and self._invalid_name != name:
            return
        invalid_name = self._invalid_name
        self._invalid_name = None
        if invalid_name and self.tree.exists(invalid_name):
            entry = self.parameters.get(invalid_name)
            self.tree.item(invalid_name, tags=self._entry_tags(invalid_name, entry.dirty if entry else False))
        self._update_tree_selection_style()
        self.after_idle(self._update_action_bar)

    def _entry_tags(self, name: str, dirty: bool) -> tuple[str, ...]:
        tags: list[str] = []
        if dirty:
            tags.append("dirty")
        if self._is_wave_enabled(name):
            tags.append(WAVE_TAG[0])
        if self._invalid_name == name:
            tags.append("invalid")
        if self._busy_name == name:
            tags.append("busy")
        return tuple(tags)

    def _is_wave_enabled(self, name: str) -> bool:
        entry = self.parameters.get(name)
        return bool(entry and entry.auto_report and not entry.is_command)

    def _on_tree_scroll(self, *args) -> None:
        self.tree.yview(*args)
        self.after_idle(self._update_action_bar)

    def _update_action_bar(self) -> None:
        row_id = self.get_selected_name()
        if not row_id or not self.tree.exists(row_id):
            self._update_tree_selection_style()
            self.message_var.set(self.i18n.translate_text("当前选中参数: 无"))
            self.read_button.configure(state="disabled")
            self.action_button.configure(state="disabled", text=self.i18n.translate_text("写入"))
            return

        entry = self.parameters.get(row_id)
        if entry is None:
            self._update_tree_selection_style()
            self.message_var.set(self.i18n.translate_text("当前选中参数: 无"))
            return

        self._update_tree_selection_style()
        self.message_var.set(self.i18n.format_text("当前选中参数: {name}", name=row_id))
        self.read_button.configure(state="normal")
        self.action_button.configure(state="normal", text=self.i18n.translate_text("执行" if entry.is_command else "写入"))

    def refresh_texts(self) -> None:
        for widget, source_text, option in self._translatable_widgets:
            widget.configure(**{option: self.i18n.translate_text(source_text)})
        headings = {
            "name": "参数名称",
            "type": "类型",
            "data": "数据",
            "min": "最小值",
            "max": "最大值",
        }
        for column, text in headings.items():
            self.tree.heading(column, text=self.i18n.translate_text(text))
        self.message_var.set(self.i18n.translate_text(self.message_var.get()))
        self._update_action_bar()

    def _remember_text(self, widget: object, source_text: str, option: str = "text") -> None:
        self._translatable_widgets.append((widget, source_text, option))

    def _invoke_selected_read(self) -> None:
        row_id = self.get_selected_name()
        if row_id:
            self.on_read_param(row_id)

    def _invoke_selected_action(self) -> None:
        row_id = self.get_selected_name()
        if row_id:
            self.on_write_param(row_id)

    def _toggle_wave_for_parameter(self, name: str) -> None:
        entry = self.parameters.get(name)
        if entry is None or entry.is_command:
            return
        self.on_toggle_wave(name, not bool(entry.auto_report))

    def _update_tree_selection_style(self) -> None:
        selected = self.get_selected_name()
        selected_bg = self._tree_selected_bg
        selected_fg = self._tree_selected_fg
        if selected and selected == self._invalid_name:
            selected_bg = "#facc15"
            selected_fg = "#713f12"
        elif selected and selected == self._busy_name:
            selected_bg = "#f87171"
            selected_fg = "#7f1d1d"
        elif selected and self._is_wave_enabled(selected):
            selected_bg = "#16a34a"
            selected_fg = "#ffffff"
        style = ttk.Style(self)
        style.map(
            self._tree_style,
            background=[("selected", selected_bg)],
            foreground=[("selected", selected_fg)],
        )
