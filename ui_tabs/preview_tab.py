# -*- coding: utf-8 -*-
"""Araclar > preview tab sekmesi (gui.OrkestraApp._build_preview_tab tasindi)."""

from __future__ import annotations

from typing import Any

from gui import (
    ACCENT_BLUE,
    BG,
    BORDER,
    BORDER_SOFT,
    EDITOR_BG,
    ERR,
    HOVER,
    SUB,
    SURFACE_3,
    TEXT_2,
    ctk,
)


def build(app: Any) -> None:
    app.tab_preview.rowconfigure(1, weight=1)
    preview_top = ctk.CTkFrame(app.tab_preview, fg_color="transparent")
    preview_top.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 6))
    preview_top.columnconfigure(0, weight=1)
    app.preview_info = ctk.CTkLabel(preview_top, text="Onizleme hedefi araniyor...", text_color=SUB, anchor="w", justify="left")
    app.preview_info.grid(row=0, column=0, sticky="ew")
    app.preview_viewport = ctk.CTkOptionMenu(preview_top, values=["Desktop", "Tablet", "Mobil"], fg_color=SURFACE_3, button_color=BORDER, button_hover_color=HOVER, text_color=TEXT_2, width=110)
    app.preview_viewport.grid(row=0, column=1, sticky="e", padx=(8, 0))
    app.b_open_preview = ctk.CTkButton(preview_top, text="Onizleme Ac", command=app.on_open_live_preview, fg_color=ACCENT_BLUE, text_color=BG, hover_color="#0ea5e9", width=120, corner_radius=7)
    app.b_open_preview.grid(row=0, column=2, sticky="e", padx=(8, 0))
    app.b_stop_preview = ctk.CTkButton(preview_top, text="Durdur", command=app.on_stop_live_preview, fg_color="transparent", hover_color=HOVER, border_width=1, border_color=ERR, text_color=ERR, width=90, corner_radius=7)
    app.b_stop_preview.grid(row=0, column=3, sticky="e", padx=(8, 0))

    app.preview_log = ctk.CTkTextbox(app.tab_preview, font=ctk.CTkFont(family="Consolas", size=12), wrap="word", fg_color=EDITOR_BG, text_color=TEXT_2, border_width=1, border_color=BORDER_SOFT)
    app.preview_log.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
    app.preview_log.configure(state="disabled")
