# -*- coding: utf-8 -*-
"""Araclar > file map tab sekmesi (gui.OrkestraApp._build_file_map_tab tasindi)."""

from __future__ import annotations

from typing import Any

from gui import (
    ACCENT,
    ACCENT_BLUE,
    HOVER,
    PURPLE,
    SUB,
    TEXT_2,
    WARN,
    ctk,
    ttk,
)


def build(app: Any) -> None:
    app.tab_filemap.rowconfigure(1, weight=1)
    top = ctk.CTkFrame(app.tab_filemap, fg_color="transparent")
    top.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 6))
    top.columnconfigure(0, weight=1)
    app.file_map_info = ctk.CTkLabel(top, text="Dosya haritasi hazirlaniyor.", text_color=SUB, anchor="w")
    app.file_map_info.grid(row=0, column=0, sticky="ew")
    ctk.CTkButton(top, text="Baseline", command=app.on_reset_file_map_baseline, fg_color="transparent", border_width=1, border_color=ACCENT_BLUE, text_color=ACCENT_BLUE, hover_color=HOVER, width=94).grid(row=0, column=1, padx=(8, 0))
    ctk.CTkButton(top, text="Yenile", command=lambda: app._refresh_file_map(schedule=False), fg_color="transparent", border_width=1, border_color=SUB, text_color=SUB, hover_color=HOVER, width=76).grid(row=0, column=2, padx=(8, 0))
    app.file_map_tree = ttk.Treeview(app.tab_filemap, columns=("status", "size", "mtime"), show="tree headings", selectmode="browse")
    app.file_map_tree.heading("#0", text="Dosya")
    app.file_map_tree.column("#0", width=260, stretch=True)
    for key, title, width in (("status", "Durum", 90), ("size", "Boyut", 90), ("mtime", "Degisim", 130)):
        app.file_map_tree.heading(key, text=title)
        app.file_map_tree.column(key, width=width, minwidth=width, stretch=False)
    app.file_map_tree.tag_configure("new", foreground=ACCENT)
    app.file_map_tree.tag_configure("changed", foreground=WARN)
    app.file_map_tree.tag_configure("large", foreground=PURPLE)
    app.file_map_tree.tag_configure("normal", foreground=TEXT_2)
    app.file_map_tree.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
    app.file_map_tree.bind("<<TreeviewSelect>>", app.on_file_map_select)
