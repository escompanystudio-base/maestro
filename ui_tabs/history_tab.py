# -*- coding: utf-8 -*-
"""Araclar > history tab sekmesi (gui.OrkestraApp._build_history_tab tasindi)."""

from __future__ import annotations

from typing import Any

from gui import (
    ACCENT,
    ACCENT_BLUE,
    BG,
    BORDER_SOFT,
    EDITOR_BG,
    HOVER,
    SUB,
    TEXT_2,
    ctk,
    ttk,
)


def build(app: Any) -> None:
    app.tab_history.rowconfigure(1, weight=1)
    top = ctk.CTkFrame(app.tab_history, fg_color="transparent")
    top.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 6))
    top.columnconfigure(0, weight=1)
    app.history_info = ctk.CTkLabel(top, text="Snapshot gecmisi bekleniyor.", text_color=SUB, anchor="w")
    app.history_info.grid(row=0, column=0, sticky="ew")
    ctk.CTkButton(top, text="Geri Don", command=app.on_restore_snapshot, fg_color=ACCENT_BLUE, text_color=BG, hover_color="#0ea5e9", width=90).grid(row=0, column=1, padx=(8, 0))
    ctk.CTkButton(top, text="Dosya Don", command=app.on_restore_snapshot_file, fg_color="transparent", border_width=1, border_color=ACCENT, text_color=ACCENT, hover_color=HOVER, width=96).grid(row=0, column=2, padx=(8, 0))
    ctk.CTkButton(top, text="Diff", command=app.on_snapshot_diff, fg_color="transparent", border_width=1, border_color=SUB, text_color=SUB, hover_color=HOVER, width=72).grid(row=0, column=3, padx=(8, 0))
    app.history_tree = ttk.Treeview(app.tab_history, columns=("time", "step", "agent", "files", "size"), show="headings", selectmode="browse")
    for key, title, width in (("time", "Tarih", 150), ("step", "Adim", 200), ("agent", "Ajan", 80), ("files", "Dosya", 70), ("size", "Boyut", 90)):
        app.history_tree.heading(key, text=title)
        app.history_tree.column(key, width=width, minwidth=width, stretch=(key == "step"))
    app.history_tree.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 8))

    # Calistirma gecmisi: her run'in ozeti (runs.jsonl) — "bu iste ne oldu?"
    ctk.CTkLabel(app.tab_history, text="Çalıştırma Geçmişi", text_color=SUB, anchor="w").grid(
        row=2, column=0, sticky="ew", padx=12
    )
    app.runs_text = ctk.CTkTextbox(
        app.tab_history, height=140, font=ctk.CTkFont(family="Consolas", size=11),
        wrap="none", fg_color=EDITOR_BG, text_color=TEXT_2,
        border_width=1, border_color=BORDER_SOFT,
    )
    app.runs_text.grid(row=3, column=0, sticky="ew", padx=12, pady=(2, 8))
    app.runs_text.configure(state="disabled")

    # Ajan karar kayitlari: kim, neye bakti, neyi degistirdi, neden (decisions.jsonl).
    ctk.CTkLabel(app.tab_history, text="Ajan Karar Kayıtları", text_color=SUB, anchor="w").grid(
        row=4, column=0, sticky="ew", padx=12
    )
    app.decisions_text = ctk.CTkTextbox(
        app.tab_history, height=120, font=ctk.CTkFont(family="Consolas", size=11),
        wrap="word", fg_color=EDITOR_BG, text_color=TEXT_2,
        border_width=1, border_color=BORDER_SOFT,
    )
    app.decisions_text.grid(row=5, column=0, sticky="ew", padx=12, pady=(2, 12))
    app.decisions_text.configure(state="disabled")
