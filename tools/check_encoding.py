#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mojibake / bozuk UTF-8 bekcisi (CI adimi).

md/py/bat/toml/sh dosyalarini tarar; tipik mojibake dizileri veya UTF-8
olarak okunamayan dosya bulursa 1 ile cikar.

Not: Bu dosya bilerek saf ASCII'dir ve desen \\u kacislariyla yazilmistir;
boylece bekci kendi kaynagini yakalayamaz.
"""

from __future__ import annotations

import pathlib
import re
import sys

# Windows konsolu cp1254 olabilir; bulgu satirlari yazilirken cokmesin.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Desen chr() ile kurulur ki bu kaynak dosya saf ASCII kalsin (kendini yakalamasin):
# 0xC3 'A-tilde' ve 0xC4/0xC5 dizileri = UTF-8'in cp125x ile yanlis acilma izleri;
# 0xFFFD = replacement char.
PATTERN = re.compile(
    "(" + chr(0xC3) + ".|" + chr(0xC4) + chr(0xB1) + "|" + chr(0xC5) + ".|" + chr(0xFFFD) + ")"
)
SUFFIXES = {".md", ".py", ".bat", ".toml", ".sh"}
SKIP_PARTS = ("node_modules", ".git", "graphify-out", "__pycache__", ".orkestra", "project", ".venv")


def main() -> int:
    root = pathlib.Path(__file__).resolve().parent.parent
    hits = 0
    for path in root.rglob("*"):
        if path.suffix.lower() not in SUFFIXES:
            continue
        if any(part in str(path) for part in SKIP_PARTS):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            print(f"UTF-8 DEGIL: {path.relative_to(root)}")
            hits += 1
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            match = PATTERN.search(line)
            if match:
                snippet = line[max(0, match.start() - 20):match.end() + 20]
                print(f"MOJIBAKE {path.relative_to(root)}:{lineno}: ...{snippet}...")
                hits += 1
    if hits:
        print(f"\nToplam {hits} bulgu. Dosyalar UTF-8 ve mojibake'siz olmali.")
        return 1
    print("Encoding temiz: tum dosyalar UTF-8, mojibake yok.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
