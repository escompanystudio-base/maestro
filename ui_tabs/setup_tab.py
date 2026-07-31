# -*- coding: utf-8 -*-
"""Araclar > setup tab sekmesi (gui.OrkestraApp._build_setup_tab tasindi)."""

from __future__ import annotations

from typing import Any

from gui import (
    ACCENT,
    BG,
    BORDER,
    BORDER_SOFT,
    EDITOR_BG,
    HOVER,
    SUB,
    SURFACE_2,
    SURFACE_3,
    TEXT_2,
    ctk,
)


def build(app: Any) -> None:
    app.tab_setup.rowconfigure(3, weight=1)
    form = ctk.CTkFrame(app.tab_setup, fg_color=SURFACE_2, border_width=1, border_color=BORDER_SOFT, corner_radius=10)
    form.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 8))
    form.columnconfigure(1, weight=1)
    ctk.CTkLabel(form, text="Proje klasoru", text_color=TEXT_2).grid(row=0, column=0, sticky="w", padx=12, pady=(12, 6))
    app.setup_dir_entry = ctk.CTkEntry(form, fg_color=EDITOR_BG, text_color=TEXT_2, border_color=BORDER_SOFT)
    app.setup_dir_entry.grid(row=0, column=1, sticky="ew", padx=8, pady=(12, 6))
    app.setup_dir_entry.insert(0, str(app.project_dir))
    ctk.CTkButton(form, text="Sec", command=app.on_choose_project_dir, fg_color="transparent", border_width=1, border_color=SUB, text_color=SUB, hover_color=HOVER, width=70).grid(row=0, column=2, padx=(0, 12), pady=(12, 6))
    ctk.CTkLabel(form, text="Teknoloji", text_color=TEXT_2).grid(row=1, column=0, sticky="w", padx=12, pady=(6, 12))
    app.setup_stack = ctk.CTkOptionMenu(form, values=["HTML", "React", "Python", "Flask", "FastAPI"], fg_color=SURFACE_3, button_color=BORDER, button_hover_color=HOVER, text_color=TEXT_2)
    app.setup_stack.grid(row=1, column=1, sticky="w", padx=8, pady=(6, 12))
    ctk.CTkButton(form, text="Kur", command=app.on_setup_project, fg_color=ACCENT, text_color=BG, hover_color="#16a34a", width=90).grid(row=1, column=2, padx=(0, 12), pady=(6, 12))
    app.setup_log = ctk.CTkTextbox(app.tab_setup, font=ctk.CTkFont(family="Consolas", size=12), wrap="word", fg_color=EDITOR_BG, text_color=TEXT_2, border_width=1, border_color=BORDER_SOFT)
    app.setup_log.grid(row=3, column=0, sticky="nsew", padx=12, pady=(0, 12))
    app.setup_log.configure(state="disabled")
