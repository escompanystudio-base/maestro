#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sahte ajan - testlerde gercek codex/gemini/claude yerine calisir.

Komut satiri argumanlarinin (ajana giden prompt'un) icinde su belirtecleri arar:
  WRITE:dosya1,dosya2  -> bu dosyalari calisma klasorunde olusturur
  FAILNOW              -> hata koduyla (1) cikar (ajan basarisizligi)
  LIMITFAIL            -> "usage limit" mesaji basip 1 ile cikar (fallback tetikler)
  HANG                 -> uzun sure bekler (timeout testi icin)

Ayrica encoding dayanikliligini test etmek icin stdout'a Turkce + emoji basar.
"""

import re
import sys
import time
from pathlib import Path

# Cikti UTF-8 olsun ki Turkce/emoji yazarken cocuk surec cokmesin.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def main() -> int:
    argv = " ".join(sys.argv[1:])
    print("Sahte ajan calisti: cgisou ışğ 🎻 (encoding testi satiri)")

    # with_fallback_agent() prompt'a "normalde ... devral" notu ekler -> fallback kosusu boyle anlasilir.
    is_fallback = "normalde" in argv and "devral" in argv

    # Limit hatasi simulasyonu: ilk (asil) kosuda fail et, fallback kosusunda gorevi tamamla.
    if "LIMITFAIL" in argv and not is_fallback:
        print("Error: usage limit reached for this model", file=sys.stderr)
        return 1

    # WRITE:dosya belirteclerini bul ve dosyalari uret (ajanlar arasi dosya paslasmasi).
    for token in re.findall(r"WRITE:([^\s]+)", argv):
        for rel in token.split(","):
            rel = rel.strip().rstrip(".,;")
            if not rel:
                continue
            path = Path(rel)
            if path.parent and str(path.parent) not in ("", "."):
                path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# Sahte ajan ciktisi: {rel}\nicerik satiri\n", encoding="utf-8")
            print(f"Uretildi: {rel}")

    if "HANG" in argv:
        time.sleep(60)  # timeout testinde surec agaci oldurulecek
        return 0

    if "FAILNOW" in argv:
        print("Hata simulasyonu (FAILNOW)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
