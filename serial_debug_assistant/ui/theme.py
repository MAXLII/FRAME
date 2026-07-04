from __future__ import annotations

from tkinter import ttk


FONT_FAMILY = "Segoe UI"
FONT_MONO = "Consolas"
FONT_SIZE = 10
FONT_SMALL = 9
FONT_TITLE = 18

APP_BG = "#edf3f8"
SURFACE = "#fbfdff"
SURFACE_ALT = "#f4f8fc"
SIDEBAR_BG = "#e3ebf4"
BORDER = "#bfd0e3"
BORDER_MUTED = "#d8e3ef"
TEXT = "#112033"
TEXT_MUTED = "#5b6b7f"
TEXT_SUBTLE = "#36506b"
ACCENT = "#1f6feb"
ACCENT_ACTIVE = "#1557b5"
ACCENT_SOFT = "#dce9f7"
SUCCESS = "#168a5b"
SUCCESS_SOFT = "#e4f7ee"
WARNING = "#9a6700"
WARNING_SOFT = "#fff1cc"
DANGER = "#c23b3b"
DANGER_SOFT = "#fde8e8"
PURPLE = "#7c3aed"
ORANGE = "#d97706"
CYAN = "#0891b2"
GREEN = "#16a34a"


def configure_app_styles(root) -> None:
    style = ttk.Style(root)
    style.theme_use("clam")

    root.configure(bg=APP_BG)

    style.configure("App.TFrame", background=APP_BG)
    style.configure("Panel.TFrame", background=SURFACE, relief="flat")
    style.configure("Sidebar.TFrame", background=SIDEBAR_BG, relief="flat")
    style.configure("Toolbar.TFrame", background=SURFACE_ALT, relief="flat")
    style.configure("Section.TLabelframe", background=SURFACE, borderwidth=1, relief="solid", bordercolor=BORDER)
    style.configure("Sidebar.Section.TLabelframe", background=SIDEBAR_BG, borderwidth=1, relief="solid", bordercolor=BORDER)
    style.configure(
        "Section.TLabelframe.Label",
        background=SURFACE,
        foreground=TEXT_SUBTLE,
        font=(FONT_FAMILY + " Semibold", FONT_SIZE),
    )
    style.configure(
        "Sidebar.Section.TLabelframe.Label",
        background=SIDEBAR_BG,
        foreground=TEXT_SUBTLE,
        font=(FONT_FAMILY + " Semibold", FONT_SIZE),
    )
    style.configure("TLabel", background=SURFACE, foreground=TEXT, font=(FONT_FAMILY, FONT_SIZE))
    style.configure("Status.TLabel", background=APP_BG, foreground=TEXT_MUTED, font=(FONT_FAMILY, FONT_SIZE))
    style.configure("ErrorStatus.TLabel", background=APP_BG, foreground=DANGER, font=(FONT_FAMILY, FONT_SIZE))
    style.configure("Header.TLabel", background=APP_BG, foreground=TEXT, font=(FONT_FAMILY + " Semibold", 11))
    style.configure("PanelHeader.TLabel", background=SURFACE, foreground=TEXT, font=(FONT_FAMILY + " Semibold", 11))
    style.configure("Muted.TLabel", background=SURFACE, foreground=TEXT_MUTED, font=(FONT_FAMILY, FONT_SMALL))
    style.configure("SidebarHeader.TLabel", background=SIDEBAR_BG, foreground=TEXT, font=(FONT_FAMILY + " Semibold", 11))
    style.configure("Sidebar.TLabel", background=SIDEBAR_BG, foreground=TEXT, font=(FONT_FAMILY, FONT_SIZE))
    style.configure(
        "TButton",
        font=(FONT_FAMILY, FONT_SIZE),
        padding=(10, 6),
        background="#f6f9fc",
        foreground=TEXT,
        borderwidth=1,
        relief="solid",
        bordercolor=BORDER,
    )
    style.map(
        "TButton",
        background=[("active", "#e8f0f8"), ("pressed", "#dde8f5")],
        bordercolor=[("focus", ACCENT)],
    )
    style.configure(
        "Accent.TButton",
        foreground="#ffffff",
        background=ACCENT,
        borderwidth=0,
        font=(FONT_FAMILY + " Semibold", FONT_SIZE),
        padding=(12, 8),
    )
    style.map("Accent.TButton", background=[("active", ACCENT_ACTIVE), ("disabled", "#8fb8f2")])
    style.configure(
        "Danger.TButton",
        foreground="#ffffff",
        background=DANGER,
        borderwidth=0,
        font=(FONT_FAMILY + " Semibold", FONT_SIZE),
        padding=(12, 8),
    )
    style.map("Danger.TButton", background=[("active", "#9f2f2f"), ("disabled", "#e7a8a8")])
    style.configure("TCheckbutton", background=SURFACE, foreground=TEXT, font=(FONT_FAMILY, FONT_SIZE))
    style.configure("Sidebar.TCheckbutton", background=SIDEBAR_BG, foreground=TEXT, font=(FONT_FAMILY, FONT_SIZE))
    style.configure("TRadiobutton", background=SURFACE, foreground=TEXT, font=(FONT_FAMILY, FONT_SIZE))
    style.configure(
        "TEntry",
        fieldbackground="#ffffff",
        foreground=TEXT,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        insertcolor=ACCENT,
        padding=5,
    )
    style.configure(
        "TCombobox",
        padding=5,
        fieldbackground=SURFACE_ALT,
        foreground=TEXT,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        arrowsize=14,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", SURFACE_ALT), ("focus", SURFACE_ALT)],
        selectbackground=[("readonly", ACCENT_SOFT)],
        selectforeground=[("readonly", TEXT)],
    )
    style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor="#dce6f1", bordercolor="#dce6f1", lightcolor=ACCENT, darkcolor=ACCENT)
    style.configure("Treeview", background="#ffffff", fieldbackground="#ffffff", foreground=TEXT, bordercolor=BORDER, rowheight=28)
    style.configure("Treeview.Heading", background="#edf4fb", foreground=TEXT_SUBTLE, relief="flat", font=(FONT_FAMILY + " Semibold", FONT_SIZE))
    style.map("Treeview.Heading", background=[("active", "#dfeaf6")])
    style.configure("TNotebook", background=SURFACE, borderwidth=0, tabmargins=(0, 0, 0, 0))
    style.configure(
        "TNotebook.Tab",
        background="#e7eef6",
        foreground="#4a5d73",
        padding=(14, 7),
        font=(FONT_FAMILY + " Semibold", FONT_SIZE),
        borderwidth=0,
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", SURFACE), ("active", "#dbe6f2")],
        foreground=[("selected", TEXT), ("active", TEXT)],
        padding=[("selected", (16, 11, 16, 9)), ("!selected", (14, 6, 14, 6))],
    )

    configure_feature_style_aliases(style)


def configure_feature_style_aliases(style: ttk.Style) -> None:
    for prefix in ("Perf", "Trace"):
        style.configure(f"{prefix}.TFrame", background=SURFACE)
        style.configure(f"{prefix}.Panel.TFrame", background=SURFACE)
        style.configure(f"{prefix}.Toolbar.TFrame", background=SURFACE_ALT)
        style.configure(f"{prefix}.TLabel", background=SURFACE, foreground=TEXT, font=(FONT_FAMILY, FONT_SIZE))
        style.configure(f"{prefix}.Muted.TLabel", background=SURFACE, foreground=TEXT_MUTED, font=(FONT_FAMILY, FONT_SMALL))
        style.configure(f"{prefix}.Panel.TLabel", background=SURFACE, foreground=TEXT, font=(FONT_FAMILY, FONT_SIZE))
        style.configure(f"{prefix}.PanelMuted.TLabel", background=SURFACE, foreground=TEXT_MUTED, font=(FONT_FAMILY, FONT_SMALL))
        style.configure(f"{prefix}.Title.TLabel", background=SURFACE, foreground=TEXT, font=(FONT_FAMILY + " Semibold", FONT_TITLE))
        style.configure(f"{prefix}.Header.TLabel", background=SURFACE, foreground=TEXT, font=(FONT_FAMILY + " Semibold", 11))
        style.configure(f"{prefix}.PanelTitle.TLabel", background=SURFACE, foreground=TEXT, font=(FONT_FAMILY + " Semibold", FONT_TITLE))
        style.configure(f"{prefix}.PanelHeader.TLabel", background=SURFACE, foreground=TEXT, font=(FONT_FAMILY + " Semibold", 11))
        style.configure(f"{prefix}.Value.TLabel", background=SURFACE, foreground=TEXT, font=(FONT_FAMILY + " Semibold", 19))
        style.configure(f"{prefix}.Cyan.TLabel", background=SURFACE, foreground=CYAN, font=(FONT_FAMILY + " Semibold", FONT_SIZE))
        style.configure(f"{prefix}.Status.TLabel", background=SURFACE_ALT, foreground=CYAN, font=(FONT_FAMILY + " Semibold", FONT_SIZE))
        style.configure(f"{prefix}.TButton", background="#f6f9fc", foreground=TEXT, bordercolor=BORDER, padding=(12, 7))
        style.map(f"{prefix}.TButton", background=[("active", "#e8f0f8"), ("pressed", "#dde8f5")])
        style.configure(f"{prefix}.Accent.TButton", background=ACCENT, foreground="#ffffff", bordercolor=ACCENT, padding=(12, 7))
        style.map(f"{prefix}.Accent.TButton", background=[("active", ACCENT_ACTIVE), ("pressed", ACCENT_ACTIVE)])
        style.configure(f"{prefix}.Stop.TButton", background=DANGER, foreground="#ffffff", bordercolor=DANGER, padding=(12, 7))
        style.map(f"{prefix}.Stop.TButton", background=[("active", "#9f2f2f"), ("pressed", "#9f2f2f")])
        style.configure(f"{prefix}.TEntry", fieldbackground="#ffffff", foreground=TEXT, insertcolor=ACCENT, bordercolor=BORDER)
        style.configure(f"{prefix}.Treeview", background="#ffffff", fieldbackground="#ffffff", foreground=TEXT, bordercolor=BORDER, rowheight=30)
        style.configure(f"{prefix}.Treeview.Heading", background="#edf4fb", foreground=TEXT_SUBTLE, font=(FONT_FAMILY + " Semibold", FONT_SIZE), bordercolor=BORDER)
        style.map(f"{prefix}.Treeview", background=[("selected", ACCENT_SOFT)], foreground=[("selected", TEXT)])
