#!/usr/bin/env python3
"""
Maestro icin merkezi loglama yapilandirmasi.

Amaç: Uygulama genelinde, kullaniciya gosterilen mesajlardan AYRI olarak,
tani amacli (traceback dahil) dosya tabanli bir log tutmak. Boylece
beklenmeyen bir hata olustugunda kaynagini bulmak mumkun olur.

- Tek bir "maestro" adli logger agaci kullanilir (alt modüller:
  "maestro.orkestra", "maestro.gui", "maestro.menu").
- Dosya logu donguseldir (RotatingFileHandler): dosya buyuyunce eski
  loglar otomatik arsivlenir, disk dolmaz.
- setup_logging() cagrilmadan da get_logger() guvenle kullanilabilir;
  handler eklenmemisse loglar sessizce yok sayilir (uygulama kirilmaz).
"""

import logging
import logging.handlers
from pathlib import Path

_APP_LOGGER = "maestro"
_configured = False


def setup_logging(log_dir, *, level=logging.DEBUG, console=False):
    """
    Donguseldosya logunu kurar. Birden fazla kez cagrilsa bile handler'i
    yalnizca bir kez ekler (idempotent).

    log_dir : log dosyasinin yazilacagi klasor (yoksa olusturulur)
    level   : dosyaya yazilacak en dusuk seviye (varsayilan DEBUG)
    console : True ise UYARI ve ustu konsola da basilir
    """
    global _configured
    logger = logging.getLogger(_APP_LOGGER)
    logger.setLevel(level)
    logger.propagate = False  # kok logger'a tasma, cift kayit olmasin

    if _configured:
        return logger

    try:
        path = Path(log_dir)
        path.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            path / "maestro.log",
            maxBytes=1_000_000,   # ~1 MB
            backupCount=3,        # maestro.log.1 .. .3
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
        ))
        logger.addHandler(handler)
    except OSError:
        # Log dosyasi acilamazsa (izin/disk vs.) uygulama yine de calismali.
        logger.addHandler(logging.NullHandler())

    if console:
        ch = logging.StreamHandler()
        ch.setLevel(logging.WARNING)
        ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logger.addHandler(ch)

    _configured = True
    return logger


def get_logger(name=None):
    """Modüller icin alt logger dondurur, orn. get_logger('orkestra')."""
    if name:
        return logging.getLogger(f"{_APP_LOGGER}.{name}")
    return logging.getLogger(_APP_LOGGER)
