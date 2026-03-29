from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class DebugLogTab(ttk.Frame):
    def __init__(self, master, *, log_path: str) -> None:
        super().__init__(master, style="Panel.TFrame", padding=12)
        self.log_path = log_path
        self._build()

    def _build(self) -> None:
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        top = ttk.Frame(self, style="Panel.TFrame")
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="日志文件:", style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(top, text=self.log_path).grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Button(top, text="清空显示", command=self.clear).grid(row=0, column=2, padx=(8, 0))

        container = ttk.Frame(self, style="Panel.TFrame")
        container.grid(row=1, column=0, sticky="nsew")
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        self.text = tk.Text(
            container,
            wrap="char",
            relief="flat",
            borderwidth=0,
            font=("Consolas", 10),
            bg="#ffffff",
            fg="#111827",
            insertbackground="#2563eb",
            padx=12,
            pady=12,
        )
        self.text.grid(row=0, column=0, sticky="nsew")

        scroll = ttk.Scrollbar(container, orient="vertical", command=self.text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.text.configure(yscrollcommand=scroll.set)

    def append(self, line: str) -> None:
        self.text.insert("end", line + "\n")
        self.text.see("end")

    def clear(self) -> None:
        self.text.delete("1.0", "end")
