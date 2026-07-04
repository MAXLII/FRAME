from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from serial_debug_assistant.jlink_debug import DebugVariable, JLinkSettings, infer_jlink_device
from serial_debug_assistant.ui.file_dialogs import ask_open_file, preferred_dir
from serial_debug_assistant.ui.theme import ACCENT_SOFT, SURFACE_ALT, TEXT, TEXT_MUTED


class JLinkDebugTab(ttk.Frame):
    def __init__(
        self,
        master,
        *,
        on_load_symbols,
        on_refresh_values,
        on_read_selected,
        on_write_selected,
        on_test_connection,
        on_expand_variable,
        on_expand_node,
        export_dir: Path,
        target_history_path: Path,
        file_history_path: Path,
    ) -> None:
        super().__init__(master, style="Panel.TFrame", padding=16)
        self.on_load_symbols = on_load_symbols
        self.on_refresh_values = on_refresh_values
        self.on_read_selected = on_read_selected
        self.on_write_selected = on_write_selected
        self.on_test_connection = on_test_connection
        self.on_expand_variable = on_expand_variable
        self.on_expand_node = on_expand_node
        self.export_dir = export_dir
        self.target_history_path = target_history_path
        self.file_history_path = file_history_path

        self.elf_path_var = tk.StringVar()
        self.map_path_var = tk.StringVar()
        self.device_var = tk.StringVar()
        self.interface_var = tk.StringVar(value="SWD")
        self.speed_var = tk.StringVar(value="4000")
        self.search_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Select ELF/MAP and load variables.")
        self.count_var = tk.StringVar(value="0 variables")

        self._variables: list[DebugVariable] = []
        self._device_history = self._load_device_history()
        if self._device_history:
            self.device_var.set(self._device_history[0])
        self._variable_keys: dict[str, DebugVariable] = {}
        self._node_expressions: dict[str, str] = {}
        self._node_variables: dict[str, list[DebugVariable]] = {}
        self._focused_cell: tuple[str, str] | None = None
        self._edit_entry: ttk.Entry | None = None
        self._edit_value_var = tk.StringVar()
        self._expanded_dynamic: set[tuple[int, str]] = set()
        self._expanded_nodes: set[str] = set()
        self._load_file_history()
        self._build()

    def _build(self) -> None:
        self.columnconfigure(0, weight=0, minsize=300)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)

        config = ttk.LabelFrame(self, text="配置", style="Section.TLabelframe", padding=(14, 12))
        config.grid(row=0, column=0, rowspan=3, sticky="nsw", padx=(0, 12))
        config.columnconfigure(0, weight=1)
        config.columnconfigure(1, weight=0)

        ttk.Label(config, text="Target / Device").grid(row=0, column=0, columnspan=2, sticky="w")
        self.device_combo = ttk.Combobox(config, textvariable=self.device_var, values=self._device_history, width=28)
        self.device_combo.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 12))
        self.device_combo.bind("<Button-1>", self._show_device_history)
        self.device_combo.bind("<<ComboboxSelected>>", self._on_device_history_selected)
        self.device_combo.bind("<Return>", self._on_device_entry_committed)
        self.device_combo.bind("<FocusOut>", self._on_device_entry_committed)

        ttk.Label(config, text="Interface").grid(row=2, column=0, columnspan=2, sticky="w")
        ttk.Combobox(config, textvariable=self.interface_var, values=("SWD", "JTAG"), state="readonly", width=12).grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(4, 12)
        )

        ttk.Label(config, text="Speed kHz").grid(row=4, column=0, columnspan=2, sticky="w")
        ttk.Entry(config, textvariable=self.speed_var, width=12).grid(row=5, column=0, columnspan=2, sticky="ew", pady=(4, 14))

        self.connect_button = ttk.Button(config, text="Connect", command=self.on_test_connection, style="Accent.TButton")
        self.connect_button.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(0, 14))

        ttk.Separator(config, orient="horizontal").grid(row=7, column=0, columnspan=2, sticky="ew", pady=(2, 14))

        ttk.Label(config, text="ELF / AXF").grid(row=8, column=0, columnspan=2, sticky="w")
        ttk.Entry(config, textvariable=self.elf_path_var, width=26).grid(row=9, column=0, sticky="ew", pady=(4, 10), padx=(0, 8))
        ttk.Button(config, text="ELF", command=self._browse_elf, width=7).grid(row=9, column=1, sticky="ew", pady=(4, 10))

        ttk.Label(config, text="MAP").grid(row=10, column=0, columnspan=2, sticky="w")
        ttk.Entry(config, textvariable=self.map_path_var, width=26).grid(row=11, column=0, sticky="ew", pady=(4, 14), padx=(0, 8))
        ttk.Button(config, text="MAP", command=self._browse_map, width=7).grid(row=11, column=1, sticky="ew", pady=(4, 14))

        self.load_button = ttk.Button(config, text="Load", command=self.on_load_symbols, style="Accent.TButton")
        self.load_button.grid(row=12, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.refresh_button = ttk.Button(config, text="Refresh", command=self.on_refresh_values)
        self.refresh_button.grid(row=13, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        variables_bar = ttk.Frame(self, style="Toolbar.TFrame", padding=(14, 10))
        variables_bar.grid(row=0, column=1, sticky="ew")
        variables_bar.columnconfigure(1, weight=1)
        ttk.Label(variables_bar, text="J-Link Variables", style="PanelHeader.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 18))
        ttk.Label(variables_bar, text="Search").grid(row=0, column=1, sticky="e", padx=(0, 6))
        search = ttk.Entry(variables_bar, textvariable=self.search_var, width=28)
        search.grid(row=0, column=2, sticky="ew", padx=(0, 10))
        ttk.Label(variables_bar, textvariable=self.count_var, style="Muted.TLabel").grid(row=0, column=3, sticky="e")
        self.search_var.trace_add("write", lambda *_args: self._refresh_rows())
        table_frame = ttk.Frame(self, style="Panel.TFrame", padding=1)
        table_frame.grid(row=1, column=1, sticky="nsew", pady=(10, 0))
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        columns = ("value", "type", "address", "raw", "status")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Expression", anchor="w")
        self.tree.column("#0", width=340, anchor="w", stretch=True)
        headings = {
            "value": "Value",
            "type": "Type",
            "address": "Address",
            "raw": "Raw",
            "status": "Status",
        }
        widths = {"value": 170, "type": 140, "address": 110, "raw": 210, "status": 90}
        for column in columns:
            self.tree.heading(column, text=headings[column], anchor="center")
            self.tree.column(column, width=widths[column], anchor="center")
        self.tree.column("value", anchor="center")
        self.tree.column("raw", anchor="w")
        yscroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        self.tree.tag_configure("ok_even", background="#ffffff", foreground=TEXT)
        self.tree.tag_configure("ok_odd", background="#f4f8fc", foreground=TEXT)
        self.tree.tag_configure("pending", background=SURFACE_ALT, foreground=TEXT_MUTED)
        self.tree.tag_configure("failed", background="#fde8e8", foreground="#c23b3b")
        self.tree.bind("<Button-1>", self._on_tree_click, add=True)
        self.tree.bind("<Button-3>", self._on_tree_context_menu)
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        self.tree.bind("<Control-c>", self._copy_focused_cell)
        self.tree.bind("<Control-C>", self._copy_focused_cell)
        self.tree.bind("<<TreeviewOpen>>", self._on_tree_open)
        style = ttk.Style(self)
        style.map("Treeview", background=[("selected", ACCENT_SOFT)], foreground=[("selected", TEXT)])

        self.copy_menu = tk.Menu(self, tearoff=False)
        self.copy_menu.add_command(label="Copy Cell", command=self._copy_focused_cell)
        self.copy_menu.add_command(label="Copy Row", command=self._copy_focused_row)
        self.copy_menu.add_separator()
        self.copy_menu.add_command(label="Copy Expression", command=lambda: self._copy_focused_column("#0"))
        self.copy_menu.add_command(label="Copy Value", command=lambda: self._copy_focused_column("value"))

        status = ttk.Frame(self, style="Panel.TFrame")
        status.grid(row=2, column=1, sticky="ew", pady=(10, 0))
        status.columnconfigure(0, weight=1)
        ttk.Label(status, textvariable=self.status_var, style="Muted.TLabel").grid(row=0, column=0, sticky="w")

    def _browse_elf(self) -> None:
        path = ask_open_file(
            key="jlink_symbol",
            title="Select ELF File",
            initialdir=preferred_dir(self.elf_path_var.get(), self.map_path_var.get(), fallback=self.export_dir),
            filetypes=[("ELF Files", "*.elf *.axf"), ("All Files", "*.*")],
        )
        if path:
            self.elf_path_var.set(path)
            self.save_file_history()
            self.auto_detect_device()

    def _browse_map(self) -> None:
        path = ask_open_file(
            key="jlink_symbol",
            title="Select MAP File",
            initialdir=preferred_dir(self.map_path_var.get(), self.elf_path_var.get(), fallback=self.export_dir),
            filetypes=[("MAP Files", "*.map"), ("All Files", "*.*")],
        )
        if path:
            self.map_path_var.set(path)
            self.save_file_history()
            self.auto_detect_device()

    def get_symbol_paths(self) -> tuple[Path | None, Path | None]:
        elf_text = self.elf_path_var.get().strip()
        map_text = self.map_path_var.get().strip()
        return (Path(elf_text) if elf_text else None, Path(map_text) if map_text else None)

    def auto_detect_device(self, *, force: bool = False) -> bool:
        if not force and self.device_var.get().strip():
            return False
        elf_path, map_path = self.get_symbol_paths()
        device = infer_jlink_device(elf_path=elf_path, map_path=map_path)
        if not device:
            return False
        self.device_var.set(device)
        self.remember_device(device)
        self.status_var.set(f"Detected J-Link Device: {device}")
        return True

    def get_jlink_settings(self) -> JLinkSettings:
        try:
            speed = int(self.speed_var.get().strip(), 0)
        except ValueError as exc:
            raise ValueError("Speed kHz must be an integer.") from exc
        return JLinkSettings(
            executable="",
            device=self.device_var.get().strip(),
            interface=self.interface_var.get(),
            speed_khz=speed,
        )

    def set_device(self, device: str) -> None:
        self.device_var.set(device.strip())
        self.remember_device(device)

    def remember_device(self, device: str | None = None) -> None:
        target = (device or self.device_var.get()).strip()
        if not target:
            return
        normalized = target.upper()
        history = [normalized]
        for item in self._device_history:
            item_text = item.strip().upper()
            if item_text and item_text != normalized:
                history.append(item_text)
        self._device_history = history[:20]
        self.device_combo.configure(values=self._device_history)
        self._save_device_history()

    def get_variables(self) -> list[DebugVariable]:
        return list(self._variables)

    def set_variables(self, variables: list[DebugVariable]) -> None:
        self._variables = list(variables)
        self._expanded_nodes.clear()
        self._expanded_dynamic.clear()
        self.count_var.set(f"{len(self._variables)} variables")
        self._refresh_rows()

    def replace_variables(self, variables: list[DebugVariable]) -> None:
        updates = {(variable.address, variable.name): variable for variable in variables}
        self._variables = [updates.get((variable.address, variable.name), variable) for variable in self._variables]
        self._refresh_rows()

    def update_visible_variables(self, variables: list[DebugVariable]) -> None:
        updates = {(variable.address, variable.name): variable for variable in variables}
        self._variables = [updates.get((variable.address, variable.name), variable) for variable in self._variables]
        for key, variable in list(self._variable_keys.items()):
            updated = updates.get((variable.address, variable.name))
            if updated is None:
                continue
            self._variable_keys[key] = updated
            row_tag = "failed" if updated.status != "OK" and "fail" in updated.status.lower() else ""
            self.tree.item(
                key,
                values=(updated.value, updated.type_name, f"0x{updated.address:08X}", updated.raw_hex, updated.status),
            )
            if row_tag:
                self.tree.item(key, tags=(row_tag,))

    def set_dynamic_children(self, parent_variable: DebugVariable, children: list[DebugVariable]) -> None:
        parent_key = self._row_key_for_variable(parent_variable)
        if not parent_key:
            return
        self.tree.delete(*self.tree.get_children(parent_key))
        sibling_counts: dict[str, int] = {}
        inserted_nodes: dict[tuple[str, ...], str] = {}
        base_expression = self._node_expressions.get(parent_key, parent_variable.name)
        parent_meta = _build_parent_metadata(children)
        for index, variable in enumerate(children):
            variable = _reuse_linked_pointer_templates(parent_variable, variable)
            parts = _expression_parts(variable.name)
            parent = parent_key
            path: tuple[str, ...] = ()
            for part in parts[:-1]:
                path = (*path, part)
                node = inserted_nodes.get(path)
                if node is None:
                    node = f"dynnode:{parent_key}:{'|'.join(path)}"
                    inserted_nodes[path] = node
                    self._node_expressions[node] = f"{base_expression}->{_parts_to_expression(path)}"
                    meta = parent_meta.get(path, _ParentMetadata())
                    self.tree.insert(
                        parent,
                        "end",
                        iid=node,
                        text=part,
                        values=("", meta.type_name, meta.address_text(), "", ""),
                        tags=(_next_row_tag(sibling_counts, parent),),
                        open=False,
                    )
                parent = node
            key = f"dyn:{parent_key}:{index}:{variable.address:08X}:{variable.name}"
            self._variable_keys[key] = variable
            self._node_expressions[key] = f"{base_expression}->{variable.name}"
            row_tag = _next_row_tag(sibling_counts, parent)
            if variable.status != "OK":
                row_tag = "failed" if "fail" in variable.status.lower() else "pending"
            item = self.tree.insert(
                parent,
                "end",
                iid=key,
                text=parts[-1] if parts else variable.name,
                values=(variable.value, variable.type_name, f"0x{variable.address:08X}", variable.raw_hex, variable.status),
                tags=(row_tag,),
            )
            if variable.child_templates:
                self.tree.insert(item, "end", iid=f"dummy:{key}", text="...", values=("", "", "", "", ""), tags=("pending",))
        self._expanded_dynamic.add((parent_variable.address, parent_variable.name))
        self.tree.item(parent_key, open=True)

    def clear_dynamic_children(self, parent_variable: DebugVariable) -> None:
        parent_key = self._row_key_for_variable(parent_variable)
        if not parent_key:
            return
        self.tree.delete(*self.tree.get_children(parent_key))
        self._expanded_dynamic.add((parent_variable.address, parent_variable.name))
        self.tree.item(parent_key, open=True)

    def get_selected_variable(self) -> DebugVariable | None:
        selected_key = self._selected_key()
        if not selected_key:
            return None
        return self._variable_keys.get(selected_key)

    def get_write_value(self) -> str:
        return self._edit_value_var.get().strip()

    def mark_write_committed(self) -> None:
        self._close_value_editor()

    def expression_for_node(self, node_id: str) -> str:
        return self._node_expressions.get(node_id, str(self.tree.item(node_id, "text")))

    def _row_key_for_variable(self, variable: DebugVariable) -> str | None:
        for key, item in self._variable_keys.items():
            if item.address == variable.address and item.name == variable.name:
                return key
        return None

    def set_status(self, message: str) -> None:
        self.status_var.set(message)

    def set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self._close_value_editor()
        self.load_button.configure(state=state)
        self.refresh_button.configure(state=state)
        self.connect_button.configure(state=state)
        self.device_combo.configure(state=state)

    def _show_device_history(self, event) -> None:
        if self._device_history:
            event.widget.after_idle(lambda: event.widget.event_generate("<Down>"))

    def _on_device_history_selected(self, _event=None) -> None:
        self.remember_device()

    def _on_device_entry_committed(self, _event=None) -> None:
        self.remember_device()

    def _load_device_history(self) -> list[str]:
        try:
            data = json.loads(self.target_history_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(data, list):
            return []
        history: list[str] = []
        for item in data:
            if not isinstance(item, str):
                continue
            target = item.strip().upper()
            if target and target not in history:
                history.append(target)
        return history[:20]

    def _save_device_history(self) -> None:
        try:
            self.target_history_path.parent.mkdir(parents=True, exist_ok=True)
            self.target_history_path.write_text(json.dumps(self._device_history, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            return

    def _load_file_history(self) -> None:
        try:
            data = json.loads(self.file_history_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, dict):
            return
        elf_path = str(data.get("elf_path", "")).strip()
        map_path = str(data.get("map_path", "")).strip()
        if elf_path:
            self.elf_path_var.set(elf_path)
        if map_path:
            self.map_path_var.set(map_path)

    def save_file_history(self) -> None:
        payload = {
            "elf_path": self.elf_path_var.get().strip(),
            "map_path": self.map_path_var.get().strip(),
        }
        try:
            self.file_history_path.parent.mkdir(parents=True, exist_ok=True)
            self.file_history_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            return

    def _refresh_rows(self) -> None:
        query = self.search_var.get().strip().lower()
        selected_key = self._selected_key()
        self.tree.delete(*self.tree.get_children())
        self._variable_keys.clear()
        self._node_expressions.clear()
        self._node_variables.clear()
        inserted_nodes: dict[tuple[str, ...], str] = {}
        sibling_counts: dict[str, int] = {}
        visible_variables = [
            variable
            for variable in self._variables
            if _variable_matches_search(variable, query)
        ]
        parent_meta = _build_parent_metadata(visible_variables)
        visible_count = 0
        for index, variable in enumerate(visible_variables):
            visible_count += 1
            status = variable.status
            parts = _expression_parts(variable.name)
            parent = ""
            path: tuple[str, ...] = ()
            for part in parts[:-1]:
                path = (*path, part)
                node = inserted_nodes.get(path)
                if node is None:
                    node = "node:" + "\x1f".join(path)
                    inserted_nodes[path] = node
                    self._node_expressions[node] = _parts_to_expression(path)
                    node_tag = _next_row_tag(sibling_counts, parent)
                    meta = parent_meta.get(path, _ParentMetadata())
                    self.tree.insert(
                        parent,
                        "end",
                        iid=node,
                        text=part,
                        values=("", meta.type_name, meta.address_text(), "", ""),
                        tags=(node_tag,),
                        open=False,
                    )
                if len(parts) == len(path) + 1:
                    self._node_variables.setdefault(node, []).append(variable)
                parent = node

            key = self._variable_key(variable, index)
            self._variable_keys[key] = variable
            self._node_expressions[key] = variable.name
            label = parts[-1] if parts else variable.name
            row_tag = _next_row_tag(sibling_counts, parent)
            if status != "OK":
                row_tag = "failed" if "fail" in status.lower() else "pending"
            item = self.tree.insert(
                parent,
                "end",
                iid=key,
                text=label,
                values=(variable.value, variable.type_name, f"0x{variable.address:08X}", variable.raw_hex, variable.status),
                tags=(row_tag,),
            )
            if variable.child_templates:
                self.tree.insert(item, "end", iid=f"dummy:{key}", text="...", values=("", "", "", "", ""), tags=("pending",))
            if key == selected_key:
                self.tree.selection_set(item)
        self.count_var.set(f"{visible_count}/{len(self._variables)} variables")

    def _selected_key(self) -> str | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return str(selection[0])

    def _on_tree_click(self, event) -> None:
        self._set_focused_cell_from_event(event)

    def _on_tree_context_menu(self, event) -> str:
        if self._set_focused_cell_from_event(event):
            self.copy_menu.tk_popup(event.x_root, event.y_root)
        return "break"

    def _on_tree_double_click(self, event) -> str:
        if not self._set_focused_cell_from_event(event):
            return "break"
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return "break"
        column_id = self.tree.identify_column(event.x)
        if column_id == "#1" and row_id in self._variable_keys:
            self._begin_value_edit(row_id)
            return "break"
        variable = self._variable_keys.get(row_id)
        if variable is not None:
            self.on_read_selected()
            return "break"
        variables = self._node_variables.get(row_id, [])
        if variables:
            self._expanded_nodes.add(row_id)
            self.tree.item(row_id, open=True)
            self.on_expand_node(row_id, variables)
        return "break"

    def _on_write_enter(self, _event=None) -> str:
        self.mark_write_committed()
        self.on_write_selected()
        return "break"

    def _begin_value_edit(self, row_id: str) -> None:
        self._close_value_editor()
        bbox = self.tree.bbox(row_id, "value")
        if not bbox:
            return
        x, y, width, height = bbox
        values = self.tree.item(row_id, "values")
        current_value = str(values[0]) if values else ""
        self._edit_value_var.set(current_value)
        editor = tk.Entry(
            self.tree,
            textvariable=self._edit_value_var,
            justify="center",
            foreground="#c23b3b",
            relief="solid",
            borderwidth=1,
        )
        editor.place(x=x, y=y, width=width, height=height)
        editor.focus_set()
        editor.selection_range(0, "end")
        editor.bind("<Return>", self._on_write_enter)
        editor.bind("<Escape>", lambda _event=None: self._close_value_editor())
        self._edit_entry = editor
        self.status_var.set("Not written - press Enter")

    def _close_value_editor(self) -> None:
        if self._edit_entry is None:
            return
        self._edit_entry.destroy()
        self._edit_entry = None

    def _on_tree_open(self, _event=None) -> None:
        row_id = self.tree.focus()
        variable = self._variable_keys.get(row_id)
        if variable is None:
            variables = self._node_variables.get(row_id, [])
            if variables and row_id not in self._expanded_nodes and any(item.status != "OK" for item in variables):
                self._expanded_nodes.add(row_id)
                self.on_expand_node(row_id, variables)
            return
        if not variable.child_templates:
            return
        dynamic_key = (variable.address, variable.name)
        if dynamic_key in self._expanded_dynamic:
            return
        self.on_expand_variable(variable)

    def _set_focused_cell_from_event(self, event) -> bool:
        row_id = self.tree.identify_row(event.y)
        column_id = self.tree.identify_column(event.x)
        if not row_id or not column_id:
            self._focused_cell = None
            return False
        self.tree.focus(row_id)
        self.tree.selection_set(row_id)
        self._focused_cell = (row_id, column_id)
        return True

    def _copy_focused_cell(self, _event=None) -> str:
        text = self._focused_cell_text()
        if text:
            self._copy_text(text)
        return "break"

    def _copy_focused_row(self) -> None:
        if self._focused_cell is None:
            return
        row_id, _column_id = self._focused_cell
        values = self.tree.item(row_id, "values")
        row_values = [self._expression_for_row(row_id), *[str(value) for value in values if str(value)]]
        self._copy_text("\t".join(row_values))

    def _copy_focused_column(self, column_id: str) -> None:
        if self._focused_cell is None:
            return
        row_id, _focused_column = self._focused_cell
        text = self._cell_text(row_id, column_id)
        if text:
            self._copy_text(text)

    def _focused_cell_text(self) -> str:
        if self._focused_cell is None:
            return ""
        row_id, column_id = self._focused_cell
        return self._cell_text(row_id, column_id)

    def _cell_text(self, row_id: str, column_id: str) -> str:
        if column_id == "#0":
            return self._expression_for_row(row_id)
        columns = ("value", "type", "address", "raw", "status")
        try:
            index = int(column_id.lstrip("#")) - 1
        except ValueError:
            index = columns.index(column_id) if column_id in columns else -1
        values = self.tree.item(row_id, "values")
        if 0 <= index < len(values):
            return str(values[index])
        return ""

    def _expression_for_row(self, row_id: str) -> str:
        return self._node_expressions.get(row_id, str(self.tree.item(row_id, "text")))

    def _copy_text(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_var.set(f"Copied: {text}")

    @staticmethod
    def _variable_key(variable: DebugVariable, index: int) -> str:
        return f"{index}:{variable.address:08X}:{variable.name}"


def _expression_parts(name: str) -> list[str]:
    parts: list[str] = []
    token: list[str] = []
    index = 0
    while index < len(name):
        char = name[index]
        if char == ".":
            if token:
                parts.append("".join(token))
                token.clear()
            index += 1
            continue
        if char == "[":
            if token:
                parts.append("".join(token))
                token.clear()
            end = name.find("]", index)
            if end < 0:
                token.append(char)
                index += 1
                continue
            parts.append(name[index : end + 1])
            index = end + 1
            continue
        token.append(char)
        index += 1
    if token:
        parts.append("".join(token))
    return parts or [name]


def _variable_matches_search(variable: DebugVariable, query: str) -> bool:
    if not query:
        return True
    parts = _expression_parts(variable.name)
    root_name = parts[0].lower() if parts else variable.name.lower()
    if query in root_name:
        return True
    if len(parts) == 1:
        return query in variable.section.lower() or query in variable.type_name.lower()
    for expression, type_name in variable.parent_types:
        if expression == parts[0] and query in type_name.lower():
            return True
    return False


@dataclass
class _ParentMetadata:
    address: int | None = None
    type_name: str = ""

    def address_text(self) -> str:
        return f"0x{self.address:08X}" if self.address is not None else ""


def _build_parent_metadata(variables: list[DebugVariable]) -> dict[tuple[str, ...], _ParentMetadata]:
    metadata: dict[tuple[str, ...], _ParentMetadata] = {}
    for variable in variables:
        parts = _expression_parts(variable.name)
        explicit_parent_types = dict(variable.parent_types)
        for index in range(1, len(parts)):
            path = tuple(parts[:index])
            expression = _parts_to_expression(path)
            meta = metadata.setdefault(path, _ParentMetadata())
            if meta.address is None or variable.address < meta.address:
                meta.address = variable.address
            inferred_type = explicit_parent_types.get(expression) or _infer_parent_type(parts, index, variable.type_name)
            if inferred_type and (not meta.type_name or meta.type_name == "array element"):
                meta.type_name = inferred_type
    return metadata


def _infer_parent_type(parts: list[str], index: int, leaf_type: str) -> str:
    current = parts[index - 1]
    next_part = parts[index] if index < len(parts) else ""
    if next_part.startswith("["):
        return f"{leaf_type}[]" if leaf_type else "array"
    if current.startswith("["):
        return "array element"
    return "struct"


def _parts_to_expression(parts: tuple[str, ...]) -> str:
    text = ""
    for part in parts:
        if part.startswith("["):
            text += part
        elif text:
            text += f".{part}"
        else:
            text = part
    return text


def _reuse_linked_pointer_templates(parent_variable: DebugVariable, variable: DebugVariable) -> DebugVariable:
    if variable.child_templates or not parent_variable.child_templates:
        return variable
    if _normalized_type_name(variable.type_name) != _normalized_type_name(parent_variable.type_name):
        return variable
    if "*" not in variable.type_name:
        return variable
    return replace(variable, child_templates=parent_variable.child_templates)


def _normalized_type_name(type_name: str) -> str:
    return " ".join(type_name.replace("const", "").replace("volatile", "").split()).strip()


def _next_row_tag(sibling_counts: dict[str, int], parent: str) -> str:
    count = sibling_counts.get(parent, 0)
    sibling_counts[parent] = count + 1
    return "ok_odd" if count % 2 == 0 else "ok_even"
