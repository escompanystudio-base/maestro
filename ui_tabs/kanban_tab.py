# -*- coding: utf-8 -*-
"""Araclar > Is Kartlari sekmesi: adimlar Trello benzeri kolonlarda."""

from __future__ import annotations

from typing import Any

from gui import (
    ACCENT,
    ACCENT_BLUE,
    BORDER_SOFT,
    MUTED,
    WARN,
    ctk,
)


def build(app: Any) -> None:
    app.tab_kanban.rowconfigure(0, weight=1)
    for c in range(4):
        app.tab_kanban.columnconfigure(c, weight=1)
    app.kanban_cols: dict[str, Any] = {}
    for c, (key, baslik, renk) in enumerate(
        (
            ("bekliyor", "Bekliyor", MUTED),
            ("calisiyor", "Çalışıyor", ACCENT_BLUE),
            ("kontrol", "Kontrol gerek", WARN),
            ("tamam", "Tamamlandı", ACCENT),
        )
    ):
        col = ctk.CTkScrollableFrame(
            app.tab_kanban, fg_color="transparent",
            border_width=1, border_color=BORDER_SOFT, corner_radius=8,
        )
        col.grid(row=0, column=c, sticky="nsew", padx=4, pady=8)
        ctk.CTkLabel(col, text=baslik, text_color=renk, font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=6, pady=(4, 6))
        app.kanban_cols[key] = col
