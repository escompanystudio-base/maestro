# -*- coding: utf-8 -*-
"""Araclar > metrics tab sekmesi (gui.OrkestraApp._build_metrics_tab tasindi)."""

from __future__ import annotations

from typing import Any

from gui import (
    HOVER,
    SUB,
    ctk,
    ttk,
)


def build(app: Any) -> None:
    app.tab_metrics.rowconfigure(1, weight=1)
    top = ctk.CTkFrame(app.tab_metrics, fg_color="transparent")
    top.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 6))
    top.columnconfigure(0, weight=1)
    app.metrics_summary = ctk.CTkLabel(top, text="Performans verisi bekleniyor.", text_color=SUB, anchor="w")
    app.metrics_summary.grid(row=0, column=0, sticky="ew")
    ctk.CTkButton(top, text="Yenile", command=lambda: app._refresh_metrics(schedule=False), fg_color="transparent", border_width=1, border_color=SUB, text_color=SUB, hover_color=HOVER, width=84).grid(row=0, column=1)
    app.metrics_tree = ttk.Treeview(app.tab_metrics, columns=("agent", "runs", "time", "errors", "fallbacks", "files"), show="headings", selectmode="browse")
    for key, title, width in (
        ("agent", "Ajan", 80),
        ("runs", "Adim", 70),
        ("time", "Sure", 90),
        ("errors", "Hata", 70),
        ("fallbacks", "Fallback", 80),
        ("files", "Son Ciktilar", 260),
    ):
        app.metrics_tree.heading(key, text=title)
        app.metrics_tree.column(key, width=width, minwidth=width, stretch=(key == "files"))
    app.metrics_tree.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
