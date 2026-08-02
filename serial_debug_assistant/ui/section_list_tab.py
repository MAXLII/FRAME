from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import ttk

from serial_debug_assistant.section_list_protocol import SectionListDirectoryEntry, SectionListNode
from serial_debug_assistant.section_map import SectionMap
from serial_debug_assistant.ui.file_dialogs import ask_open_file
from serial_debug_assistant.ui.theme import (
    ACCENT,
    ACCENT_ACTIVE,
    ACCENT_SOFT,
    BORDER_MUTED,
    DANGER,
    FONT_FAMILY,
    FONT_SIZE,
    SURFACE,
    SURFACE_ALT,
    TEXT,
    TEXT_MUTED,
    TEXT_SUBTLE,
)


class SectionListTab(ttk.Frame):
    def __init__(self, master, *, on_refresh_directory, on_fetch_list) -> None:
        super().__init__(master, style="SectionList.TFrame", padding=18)
        self.on_refresh_directory = on_refresh_directory
        self.on_fetch_list = on_fetch_list
        self.target_addr_var = tk.StringVar(value="2")
        self.dynamic_addr_var = tk.StringVar(value="0")
        self.map_path_var = tk.StringVar()
        self.status_var = tk.StringVar(value="连接设备后先刷新链表列表")
        self.detail_title_var = tk.StringVar(value="请选择一条链表")
        self.detail_meta_var = tk.StringVar(value="从左侧选择链表，然后点击“获取所选链表”")
        self._map: SectionMap | None = None
        self._directory: list[SectionListDirectoryEntry] = []
        self._node_cache: dict[int, list[SectionListNode]] = {}
        self._refresh_buffers: dict[int, list[SectionListNode]] = {}
        self._active_entry: SectionListDirectoryEntry | None = None
        self._rendered_list_id: int | None = None
        self._active_node_cell: tuple[str, str] | None = None
        self._configure_styles()
        self._build()

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.configure("SectionList.TFrame", background=SURFACE)
        style.configure("SectionList.Panel.TFrame", background=SURFACE_ALT, relief="flat")
        style.configure("SectionList.Card.TFrame", background=SURFACE, relief="solid", borderwidth=1)
        style.configure("SectionList.Title.TLabel", background=SURFACE, foreground=TEXT, font=(FONT_FAMILY + " Semibold", 18))
        style.configure("SectionList.Subtitle.TLabel", background=SURFACE, foreground=TEXT_MUTED, font=(FONT_FAMILY, 9))
        style.configure("SectionList.PanelTitle.TLabel", background=SURFACE_ALT, foreground=TEXT, font=(FONT_FAMILY + " Semibold", 11))
        style.configure("SectionList.PanelText.TLabel", background=SURFACE_ALT, foreground=TEXT_MUTED, font=(FONT_FAMILY, 9))
        style.configure("SectionList.Status.TLabel", background=SURFACE_ALT, foreground=TEXT_SUBTLE, font=(FONT_FAMILY, 9))
        style.configure("SectionList.Error.TLabel", background=SURFACE_ALT, foreground=DANGER, font=(FONT_FAMILY, 9))
        style.configure("SectionList.Accent.TButton", background=ACCENT, foreground="#ffffff", bordercolor=ACCENT, padding=(14, 7))
        style.map("SectionList.Accent.TButton", background=[("active", ACCENT_ACTIVE), ("pressed", ACCENT_ACTIVE), ("disabled", "#8fb8f2")])
        style.configure("SectionList.Treeview", background=SURFACE, fieldbackground=SURFACE, foreground=TEXT, bordercolor=BORDER_MUTED, rowheight=38)
        style.configure("SectionList.Treeview.Heading", background="#edf4fb", foreground=TEXT_SUBTLE, font=(FONT_FAMILY + " Semibold", FONT_SIZE), relief="flat")
        style.map("SectionList.Treeview", background=[("selected", ACCENT_SOFT)], foreground=[("selected", TEXT)])
        style.configure("SectionList.Node.Treeview", background=SURFACE, fieldbackground=SURFACE, foreground=TEXT, bordercolor=BORDER_MUTED, rowheight=32)
        style.configure("SectionList.Node.Treeview.Heading", background="#edf4fb", foreground=TEXT_SUBTLE, font=(FONT_FAMILY + " Semibold", FONT_SIZE), relief="flat")

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        header = ttk.Frame(self, style="SectionList.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="链表顺序", style="SectionList.Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="读取设备运行时链表，并通过 MAP 文件将注册对象地址解析为符号名称",
            style="SectionList.Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))

        config = ttk.Frame(self, style="SectionList.Panel.TFrame", padding=(16, 13))
        config.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        config.columnconfigure(6, weight=1)
        ttk.Label(config, text="设备", style="SectionList.PanelTitle.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 12))
        ttk.Label(config, text="Target", style="SectionList.PanelText.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Entry(config, textvariable=self.target_addr_var, width=6).grid(row=0, column=2, padx=(6, 12))
        ttk.Label(config, text="Dyn", style="SectionList.PanelText.TLabel").grid(row=0, column=3, sticky="w")
        ttk.Entry(config, textvariable=self.dynamic_addr_var, width=6).grid(row=0, column=4, padx=(6, 20))
        ttk.Separator(config, orient="vertical").grid(row=0, column=5, sticky="ns", padx=(0, 20))
        ttk.Entry(config, textvariable=self.map_path_var).grid(row=0, column=6, sticky="ew", padx=(0, 8))
        ttk.Button(config, text="选择 MAP", command=self._browse_map).grid(row=0, column=7, padx=(0, 8))
        ttk.Button(
            config,
            text="刷新链表列表",
            command=self.on_refresh_directory,
            style="SectionList.Accent.TButton",
        ).grid(row=0, column=8)

        self.status_label = ttk.Label(self, textvariable=self.status_var, style="SectionList.Status.TLabel", padding=(12, 7))
        self.status_label.grid(row=2, column=0, sticky="ew", pady=(0, 10))

        content = ttk.Frame(self, style="SectionList.TFrame")
        content.grid(row=3, column=0, sticky="nsew")
        content.columnconfigure(1, weight=1)
        content.rowconfigure(0, weight=1)

        sidebar = ttk.Frame(content, style="SectionList.Panel.TFrame", padding=12, width=260)
        sidebar.columnconfigure(0, weight=1)
        sidebar.rowconfigure(2, weight=1)
        ttk.Label(sidebar, text="可用链表", style="SectionList.PanelTitle.TLabel").grid(row=0, column=0, sticky="w")
        self.directory_count_label = ttk.Label(sidebar, text="尚未读取", style="SectionList.PanelText.TLabel")
        self.directory_count_label.grid(row=1, column=0, sticky="w", pady=(2, 10))
        self.directory_tree = ttk.Treeview(
            sidebar,
            columns=("name", "count", "cache"),
            show="headings",
            selectmode="browse",
            style="SectionList.Treeview",
            height=10,
        )
        self.directory_tree.heading("name", text="链表")
        self.directory_tree.heading("count", text="节点")
        self.directory_tree.heading("cache", text="状态")
        self.directory_tree.column("name", width=120, minwidth=90, anchor="w")
        self.directory_tree.column("count", width=48, minwidth=44, anchor="center", stretch=False)
        self.directory_tree.column("cache", width=58, minwidth=52, anchor="center", stretch=False)
        self.directory_tree.grid(row=2, column=0, sticky="nsew")
        self.directory_tree.bind("<<TreeviewSelect>>", self._on_directory_selected)
        self.fetch_button = ttk.Button(
            sidebar,
            text="刷新所选链表",
            command=self.on_fetch_list,
            style="SectionList.Accent.TButton",
            state="disabled",
        )
        self.fetch_button.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        sidebar.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        sidebar.grid_propagate(False)

        detail = ttk.Frame(content, style="SectionList.Card.TFrame", padding=16)
        detail.columnconfigure(0, weight=1)
        detail.rowconfigure(2, weight=1)
        ttk.Label(detail, textvariable=self.detail_title_var, style="PanelHeader.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(detail, textvariable=self.detail_meta_var, style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(3, 12))
        node_frame = ttk.Frame(detail, style="SectionList.TFrame")
        node_frame.grid(row=2, column=0, sticky="nsew")
        node_frame.columnconfigure(0, weight=1)
        node_frame.rowconfigure(0, weight=1)
        self.node_tree = ttk.Treeview(
            node_frame,
            columns=("index", "object", "address"),
            show="headings",
            style="SectionList.Node.Treeview",
        )
        self.node_tree.heading("index", text="顺序")
        self.node_tree.heading("object", text="对象名称")
        self.node_tree.heading("address", text="地址")
        self.node_tree.column("index", width=72, minwidth=60, anchor="center", stretch=False)
        self.node_tree.column("object", width=520, minwidth=220, anchor="center")
        self.node_tree.column("address", width=150, minwidth=130, anchor="center", stretch=False)
        node_scroll = ttk.Scrollbar(node_frame, orient="vertical", command=self.node_tree.yview)
        self.node_tree.configure(yscrollcommand=node_scroll.set)
        self.node_tree.grid(row=0, column=0, sticky="nsew")
        node_scroll.grid(row=0, column=1, sticky="ns")
        self.node_tree.bind("<Button-1>", self._remember_node_cell, add="+")
        self.node_tree.bind("<Control-c>", self._copy_active_node_cell)
        self.node_tree.bind("<Control-C>", self._copy_active_node_cell)
        self.node_tree.bind("<Button-3>", self._show_node_copy_menu)
        self.node_copy_menu = tk.Menu(self, tearoff=False)
        self.node_copy_menu.add_command(label="复制单元格", command=self._copy_active_node_cell)
        detail.grid(row=0, column=1, sticky="nsew")
        self._render_nodes(force=True)

    def _remember_node_cell(self, event) -> None:
        item_id = self.node_tree.identify_row(event.y)
        column_id = self.node_tree.identify_column(event.x)
        if item_id and column_id in ("#1", "#2", "#3"):
            self._active_node_cell = (item_id, column_id)

    def _copy_active_node_cell(self, _event=None) -> str:
        if self._active_node_cell is None:
            self.set_status("请先点击要复制的单元格", True)
            return "break"
        item_id, column_id = self._active_node_cell
        if not self.node_tree.exists(item_id):
            self._active_node_cell = None
            self.set_status("请先点击要复制的单元格", True)
            return "break"
        values = self.node_tree.item(item_id, "values")
        column_index = int(column_id[1:]) - 1
        if not 0 <= column_index < len(values):
            self.set_status("当前单元格不可复制", True)
            return "break"
        value = str(values[column_index])
        self.clipboard_clear()
        self.clipboard_append(value)
        self.update_idletasks()
        self.set_status(f"已复制：{value}")
        return "break"

    def _show_node_copy_menu(self, event) -> str:
        item_id = self.node_tree.identify_row(event.y)
        column_id = self.node_tree.identify_column(event.x)
        if not item_id or column_id not in ("#1", "#2", "#3"):
            return "break"
        self._active_node_cell = (item_id, column_id)
        self.node_tree.selection_set(item_id)
        self.node_tree.focus(item_id)
        try:
            self.node_copy_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.node_copy_menu.grab_release()
        return "break"

    def _browse_map(self) -> None:
        selected = ask_open_file(
            key="section-list-map",
            title="选择 Keil MAP 文件",
            initialdir=Path(self.map_path_var.get()).parent if self.map_path_var.get() else None,
            filetypes=[("MAP files", "*.map"), ("All files", "*.*")],
        )
        if not selected:
            return
        self.map_path_var.set(selected)
        self.load_map()

    def load_map(self) -> bool:
        try:
            self._map = SectionMap.load(self.map_path_var.get())
        except OSError as exc:
            self.set_status(f"MAP 文件读取失败: {exc}", True)
            return False
        self.set_status(f"已加载 MAP：{len(self._map.symbols)} 个符号")
        self._render_nodes()
        return True

    def get_target(self) -> tuple[int, int]:
        target = int(self.target_addr_var.get(), 0)
        dynamic_target = int(self.dynamic_addr_var.get(), 0)
        if not 0 <= target <= 0xFF or not 0 <= dynamic_target <= 0xFF:
            raise ValueError("Target 和 Dyn 必须在 0..255 范围内")
        return target, dynamic_target

    def get_selected_list_id(self) -> int:
        selected = self.directory_tree.selection()
        if not selected:
            raise ValueError("请先选择一条链表")
        return int(selected[0])

    def set_directory(self, directory: list[SectionListDirectoryEntry]) -> None:
        previous = self.directory_tree.selection()
        previous_id = previous[0] if previous else ""
        self._directory = list(directory)
        valid_ids = {entry.list_id for entry in directory}
        self._node_cache = {
            list_id: nodes for list_id, nodes in self._node_cache.items() if list_id in valid_ids
        }
        self._refresh_buffers = {
            list_id: nodes for list_id, nodes in self._refresh_buffers.items() if list_id in valid_ids
        }
        children = self.directory_tree.get_children()
        if children:
            self.directory_tree.delete(*children)
        for entry in directory:
            cache_text = "已缓存" if entry.list_id in self._node_cache else "未读取"
            self.directory_tree.insert(
                "", "end", iid=str(entry.list_id), values=(entry.name, entry.node_count, cache_text)
            )
        cached_count = len(self._node_cache)
        self.directory_count_label.configure(text=f"{len(directory)} 条链表 · {cached_count} 条已缓存")
        selection = previous_id if previous_id and self.directory_tree.exists(previous_id) else ""
        if not selection and directory:
            selection = str(directory[0].list_id)
        if selection:
            self.directory_tree.selection_set(selection)
            self.directory_tree.focus(selection)
            self.directory_tree.see(selection)
            self._on_directory_selected()
        else:
            self.fetch_button.configure(state="disabled")
            self._active_entry = None
            self.detail_title_var.set("没有可用链表")
            self.detail_meta_var.set("设备未注册可调试链表")
            self._render_nodes()

    def set_nodes(
        self,
        entry: SectionListDirectoryEntry,
        nodes: list[SectionListNode],
        complete: bool,
    ) -> None:
        received_nodes = list(nodes)
        if complete:
            self._node_cache[entry.list_id] = received_nodes
            self._refresh_buffers.pop(entry.list_id, None)
            cache_text = "已缓存"
        else:
            self._refresh_buffers[entry.list_id] = received_nodes
            cache_text = f"{len(received_nodes)}/{entry.node_count}"
        self._directory = [entry if item.list_id == entry.list_id else item for item in self._directory]
        if self.directory_tree.exists(str(entry.list_id)):
            self.directory_tree.set(str(entry.list_id), "count", entry.node_count)
            self.directory_tree.set(str(entry.list_id), "cache", cache_text)
        self.directory_count_label.configure(
            text=f"{len(self._directory)} 条链表 · {len(self._node_cache)} 条已缓存"
        )
        selected = self.directory_tree.selection()
        if selected and int(selected[0]) == entry.list_id:
            self._active_entry = entry
            self._render_nodes()

    def set_status(self, message: str, error: bool = False) -> None:
        self.status_var.set(message)
        self.status_label.configure(style="SectionList.Error.TLabel" if error else "SectionList.Status.TLabel")

    def _on_directory_selected(self, _event=None) -> None:
        selected = self.directory_tree.selection()
        self.fetch_button.configure(state="normal" if selected else "disabled")
        if not selected:
            return
        list_id = int(selected[0])
        entry = next((item for item in self._directory if item.list_id == list_id), None)
        if entry is None:
            return
        self._active_entry = entry
        self._render_nodes()

    def _render_nodes(self, *, force: bool = False) -> None:
        entry = self._active_entry
        if entry is None:
            children = self.node_tree.get_children()
            if children:
                self.node_tree.delete(*children)
            self._rendered_list_id = None
            self._active_node_cell = None
            self.detail_title_var.set("请选择一条链表")
            self.detail_meta_var.set("左侧显示设备链表目录，右侧显示所选链表的节点列表")
            return
        self.detail_title_var.set(entry.name)
        refreshing = entry.list_id in self._refresh_buffers
        if refreshing:
            nodes = self._refresh_buffers[entry.list_id]
        elif entry.list_id in self._node_cache:
            nodes = self._node_cache[entry.list_id]
        else:
            children = self.node_tree.get_children()
            if children:
                self.node_tree.delete(*children)
            self._rendered_list_id = entry.list_id
            self._active_node_cell = None
            self.detail_meta_var.set(f"{entry.node_count} 个节点 · 尚未读取，点击“刷新所选链表”")
            return
        children = self.node_tree.get_children()
        can_append = (
            not force
            and self._rendered_list_id == entry.list_id
            and len(children) <= len(nodes)
        )
        if not can_append:
            if children:
                self.node_tree.delete(*children)
            children = ()
            self._active_node_cell = None
        self._rendered_list_id = entry.list_id
        resolved_count = 0
        for node in nodes[: len(children)]:
            address = node.address or 0
            if self._map is not None and self._map.resolve(address) is not None:
                resolved_count += 1
        for node in nodes[len(children) :]:
            address = node.address or 0
            symbol = self._map.resolve(address) if self._map is not None else None
            if symbol is not None:
                resolved_count += 1
            name = symbol.name if symbol is not None else "未解析对象"
            self.node_tree.insert(
                "",
                "end",
                iid=f"{entry.list_id}:{node.node_index}",
                values=(node.node_index, name, f"0x{address:08X}"),
            )
        map_text = f"MAP 已解析 {resolved_count} / {len(nodes)}" if self._map is not None else "未加载 MAP，仅显示地址"
        if refreshing:
            self.detail_meta_var.set(f"正在刷新 {len(nodes)} / {entry.node_count} · {map_text}")
        else:
            self.detail_meta_var.set(f"{len(nodes)} 个节点 · {map_text} · 当前数据已缓存")
