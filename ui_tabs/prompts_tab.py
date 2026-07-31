# -*- coding: utf-8 -*-
"""Araclar > prompts tab sekmesi (gui.OrkestraApp._build_prompts_tab tasindi)."""

from __future__ import annotations

from typing import Any

from gui import (
    ACCENT,
    ACCENT_BLUE,
    BG,
    BORDER,
    BORDER_SOFT,
    EDITOR_BG,
    ERR,
    HOVER,
    SURFACE_3,
    TEXT_2,
    ctk,
)


def build(app: Any) -> None:
    app.tab_prompts.rowconfigure(1, weight=1)
    top = ctk.CTkFrame(app.tab_prompts, fg_color="transparent")
    top.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 6))
    top.columnconfigure(0, weight=1)
    app.prompt_select = ctk.CTkOptionMenu(top, values=["agresif kodla"], command=app.on_prompt_selected, fg_color=SURFACE_3, button_color=BORDER, button_hover_color=HOVER, text_color=TEXT_2)
    app.prompt_select.grid(row=0, column=0, sticky="ew")
    ctk.CTkButton(top, text="Uygula", command=app.on_apply_prompt_profile, fg_color=ACCENT_BLUE, text_color=BG, hover_color="#0ea5e9", width=84).grid(row=0, column=1, padx=(8, 0))
    ctk.CTkButton(top, text="Kaydet", command=app.on_save_prompt_profile, fg_color=ACCENT, text_color=BG, hover_color="#16a34a", width=84).grid(row=0, column=2, padx=(8, 0))
    ctk.CTkButton(top, text="Sil", command=app.on_delete_prompt_profile, fg_color="transparent", border_width=1, border_color=ERR, text_color=ERR, hover_color=HOVER, width=68).grid(row=0, column=3, padx=(8, 0))
    app.prompt_text = ctk.CTkTextbox(app.tab_prompts, wrap="word", fg_color=EDITOR_BG, text_color=TEXT_2, border_width=1, border_color=BORDER_SOFT)
    app.prompt_text.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
    app._refresh_prompts()
