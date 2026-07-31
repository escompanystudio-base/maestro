# -*- coding: utf-8 -*-
"""Araclar > files tab sekmesi (gui.OrkestraApp._build_files_tab tasindi)."""

from __future__ import annotations

from typing import Any

from gui import (
    BORDER,
    BORDER_SOFT,
    EDITOR_BG,
    ERROR_FILE,
    HOVER,
    SELECTED,
    SUB,
    SURFACE_2,
    SURFACE_3,
    TEXT,
    TEXT_2,
    ctk,
)


def build(app: Any) -> None:
    app.file_textboxes: dict[str, ctk.CTkTextbox] = {}
    app.files_tabs = ctk.CTkTabview(
        app.tab_files,
        corner_radius=8,
        fg_color=SURFACE_2,
        segmented_button_fg_color=SURFACE_3,
        segmented_button_selected_color=SELECTED,
        segmented_button_selected_hover_color="#DCE7F2",
        segmented_button_unselected_color=SURFACE_3,
        segmented_button_unselected_hover_color=HOVER,
        text_color=TEXT,
    )
    app.files_tabs.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
    app.tab_files.rowconfigure(0, weight=1)

    # Artifact review: dosyalar ham ad yerine is akisindaki rolleriyle sunulur.
    for label, filename in (
        ("İstek", "istek.md"),
        ("Plan", "plan.md"),
        ("Tasarım", "tasarim.md"),
        ("Kodlama Raporu", "rapor.md"),
        ("Kontrol", "kontrol.md"),
        ("Hata", ERROR_FILE),
    ):
        tab = app.files_tabs.add(label)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        box = ctk.CTkTextbox(tab, font=ctk.CTkFont(family="Consolas", size=12), wrap="word", fg_color=EDITOR_BG, text_color=TEXT_2, border_width=1, border_color=BORDER_SOFT)
        box.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        box.configure(state="disabled")
        app.file_textboxes[filename] = box

    code_tab = app.files_tabs.add("Kod")
    code_tab.columnconfigure(0, weight=1)
    code_tab.rowconfigure(1, weight=1)
    top = ctk.CTkFrame(code_tab, fg_color="transparent")
    top.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 0))
    top.columnconfigure(0, weight=1)
    app.code_select = ctk.CTkOptionMenu(top, values=["Kod dosyasi yok"], command=app._on_code_file_selected, fg_color=SURFACE_3, button_color=BORDER, button_hover_color=HOVER, text_color=TEXT_2)
    app.code_select.grid(row=0, column=0, sticky="ew")
    app.b_refresh_files = ctk.CTkButton(top, text="Yenile", command=app._force_refresh_files, width=82, fg_color="transparent", hover_color=HOVER, border_width=1, border_color=SUB, text_color=SUB)
    app.b_refresh_files.grid(row=0, column=1, sticky="e", padx=(8, 0))
    app.code_text = ctk.CTkTextbox(code_tab, font=ctk.CTkFont(family="Consolas", size=12), wrap="none", fg_color=EDITOR_BG, text_color=TEXT_2, border_width=1, border_color=BORDER_SOFT)
    app.code_text.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
    app.code_text.configure(state="disabled")
    app.selected_code_file: str | None = None
