# -*- coding: utf-8 -*-
"""Araclar > terminal tab sekmesi (gui.OrkestraApp._build_terminal_tab tasindi)."""

from __future__ import annotations

from typing import Any

from gui import (
    ACCENT,
    BG,
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
    app.tab_terminal.rowconfigure(2, weight=1)
    preset = ctk.CTkFrame(app.tab_terminal, fg_color="transparent")
    preset.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
    for cmd in ("npm install", "npm run dev", "npm run build", "python app.py", "python main.py"):
        ctk.CTkButton(preset, text=cmd, command=lambda c=cmd: app._set_terminal_command(c), fg_color="transparent", border_width=1, border_color=SUB, text_color=SUB, hover_color=HOVER, width=112).pack(side="left", padx=(0, 6))
    row = ctk.CTkFrame(app.tab_terminal, fg_color="transparent")
    row.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 6))
    row.columnconfigure(0, weight=1)
    app.terminal_entry = ctk.CTkEntry(row, placeholder_text="Komut yaz: npm run dev / python app.py / dir ...", fg_color=SURFACE_3, text_color=TEXT_2, border_color=BORDER_SOFT)
    app.terminal_entry.grid(row=0, column=0, sticky="ew")
    ctk.CTkButton(row, text="Calistir", command=app.on_run_terminal_command, fg_color=ACCENT, text_color=BG, hover_color="#16a34a", width=90).grid(row=0, column=1, padx=(8, 0))
    ctk.CTkButton(row, text="Durdur", command=app.on_stop_terminal_command, fg_color="transparent", border_width=1, border_color=ERR, text_color=ERR, hover_color=HOVER, width=84).grid(row=0, column=2, padx=(8, 0))
    app.terminal_output = ctk.CTkTextbox(app.tab_terminal, font=ctk.CTkFont(family="Consolas", size=12), wrap="word", fg_color=EDITOR_BG, text_color=TEXT_2, border_width=1, border_color=BORDER_SOFT)
    app.terminal_output.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))
    app.terminal_output.configure(state="disabled")
