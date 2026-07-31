#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Maestro - Sabit veri tanimlari (Faz 2a).

gui.py icinde sislenmis olan buyuk sabit sozlukler buraya tasindi:
- PROJECT_TEMPLATES : "Yeni proje" ekranindaki hazir istek sablonlari.
- BUILTIN_WORKFLOWS  : uygulamayla gelen hazir is akislari.

Boylece gui.py yalnizca arayuz/mantik ile ilgilenir; veri ayri durur
(Single Responsibility - tek sorumluluk).
"""

from __future__ import annotations

from typing import Any

PROJECT_TEMPLATES: dict[str, str] = {
    "SaaS dashboard": (
        "SaaS dashboard gelistir.\n"
        "- Hedef: ekiplerin metrikleri ve is akislarini takip edecegi modern web paneli.\n"
        "- Beklenenler: auth taslagi, dashboard kartlari, tablo/listeler, filtreler, ayarlar sayfasi.\n"
        "- Stil: sade, profesyonel, koyu/acik temaya uygun.\n"
        "- Veri: ilk surum local/mock veriyle calissin, sonra API/veritabani baglanabilir olsun."
    ),
    "Landing page": (
        "Landing page tasarla ve kodla.\n"
        "- Hedef: urun/hizmet tanitimi ve donusum odakli tek sayfa.\n"
        "- Beklenenler: hero, faydalar, ozellikler, sosyal kanit, fiyat/CTA, SSS.\n"
        "- Stil: marka hissi guclu, responsive, hizli acilan arayuz."
    ),
    "Admin panel": (
        "Admin panel gelistir.\n"
        "- Hedef: yoneticilerin kullanici, icerik ve ayarlari yonetecegi operasyon paneli.\n"
        "- Beklenenler: yan menu, listeleme, arama/filtre, detay ekranlari, form akislari.\n"
        "- Veri: local/mock veri ile basla, API katmani icin hazir yapida olsun."
    ),
    "Mobil app fikri": (
        "Mobil uygulama fikrini urun planina ve prototipe donustur.\n"
        "- Hedef: net kullanici problemi, ana ekranlar ve MVP akisi.\n"
        "- Beklenenler: onboarding, ana ekran, detay, profil/ayarlar, veri saklama karari.\n"
        "- Stil: mobil kullanima uygun sade ve hizli akış."
    ),
    "Oyun": (
        "Oyun gelistir.\n"
        "- Hedef: oynanabilir MVP.\n"
        "- Beklenenler: konsept, temel mekanikler, skor/ilerleme, asset plani, test ve dengeleme.\n"
        "- Platform: tarayicida calisan HTML/JS oyun tercih edilir."
    ),
    "E-ticaret": (
        "E-ticaret uygulamasi gelistir.\n"
        "- Beklenenler: urun listeleme, filtreleme, urun detay, sepet, checkout taslagi, admin urun yonetimi.\n"
        "- Veri: ilk surum mock/local veriyle calissin."
    ),
    "CRM": (
        "CRM uygulamasi gelistir.\n"
        "- Beklenenler: musteri listesi, kisi/firma detaylari, pipeline, gorevler, notlar, arama/filtre.\n"
        "- Stil: yogun veriyle calismaya uygun, sade ve taranabilir arayuz."
    ),
    "Yapay zeka araci": (
        "Yapay zeka araci gelistir.\n"
        "- Beklenenler: kullanici girdisi, isleme akisi, sonuc paneli, gecmis kayitlari, ayarlar.\n"
        "- Veri: local calisan MVP; API anahtari gerektiren kisimlar guvenli env/config mantigiyla tasarlansin."
    ),
}

BUILTIN_WORKFLOWS: dict[str, dict[str, Any]] = {
    "web app": {
        "summary": "Web uygulamasi icin analiz, UI, kodlama, test ve duzeltme akisi.",
        "project_type": "web_app",
        "stages": [
            {"name": "Gereksinim Analizi", "agent": "codex", "prompt": "istek.md ve sohbet.md dosyalarini oku; MVP kapsamini, sayfalari ve teknik kararlari plan.md dosyasina yaz.", "reads": ["istek.md", "sohbet.md"], "writes": ["plan.md"], "checkpoint": True, "timeout": 1200},
            {"name": "UI UX Tasarimi", "agent": "gemini", "prompt": "plan.md dosyasina gore sayfa yapisini, bilesenleri, durumlari ve responsive tasarim kararlarini tasarim.md dosyasina yaz.", "reads": ["plan.md"], "writes": ["tasarim.md"], "checkpoint": True, "timeout": 1200, "fallback_agent": "claude"},
            {"name": "Kodlama", "agent": "claude", "prompt": "istek.md, plan.md ve tasarim.md dosyalarini oku; calisan web uygulamasini proje klasorune kodla.", "reads": ["istek.md", "plan.md", "tasarim.md"], "writes": ["rapor.md"], "checkpoint": True, "timeout": 2400, "fallback_agent": "codex"},
            {"name": "Kod Kontrolu", "agent": "codex", "prompt": "Uretilen kodu calistir, hata ve eksikleri kontrol.md dosyasina yaz.", "reads": ["rapor.md"], "writes": ["kontrol.md"], "checkpoint": True, "timeout": 1200},
            {"name": "Duzeltme", "agent": "claude", "prompt": "kontrol.md dosyasindaki eksikleri uygula ve rapor.md dosyasini guncelle.", "reads": ["kontrol.md"], "writes": ["rapor.md"], "checkpoint": True, "timeout": 1800, "fallback_agent": "codex"},
        ],
    },
    "oyun": {
        "summary": "Tarayicida calisan oyun MVP akisi.",
        "project_type": "game",
        "stages": [
            {"name": "Konsept ve Mekanik", "agent": "codex", "prompt": "istek.md dosyasindan oyun turunu, hedefi, kontrolleri ve core loop'u plan.md dosyasina yaz.", "reads": ["istek.md"], "writes": ["plan.md"], "checkpoint": True, "timeout": 1200},
            {"name": "Asset ve Sahne Plani", "agent": "gemini", "prompt": "plan.md dosyasina gore oyun ekranlari, asset ihtiyaci ve denge kararlarini tasarim.md dosyasina yaz.", "reads": ["plan.md"], "writes": ["tasarim.md"], "checkpoint": True, "timeout": 1200, "fallback_agent": "claude"},
            {"name": "Oyun Kodlama", "agent": "claude", "prompt": "HTML/CSS/JS ile oynanabilir oyun MVP'sini kodla. Skor, restart ve temel kontroller calissin.", "reads": ["plan.md", "tasarim.md"], "writes": ["rapor.md"], "checkpoint": True, "timeout": 2400, "fallback_agent": "codex"},
            {"name": "Test ve Denge", "agent": "codex", "prompt": "Oyunu calistir, buglari ve denge sorunlarini kontrol.md dosyasina yaz.", "reads": ["rapor.md"], "writes": ["kontrol.md"], "checkpoint": True, "timeout": 1200},
            {"name": "Final Duzeltme", "agent": "claude", "prompt": "kontrol.md dosyasina gore oyunu duzelt ve rapor.md dosyasina ozet yaz.", "reads": ["kontrol.md"], "writes": ["rapor.md"], "checkpoint": True, "timeout": 1800, "fallback_agent": "codex"},
        ],
    },
    "SaaS": {
        "summary": "SaaS dashboard icin urun, arayuz, kodlama ve kontrol akisi.",
        "project_type": "saas",
        "stages": [
            {"name": "Urun Kapsami", "agent": "codex", "prompt": "SaaS hedefini, rolleri, metrikleri ve veri modelini plan.md dosyasina yaz.", "reads": ["istek.md", "sohbet.md"], "writes": ["plan.md"], "checkpoint": True, "timeout": 1200},
            {"name": "Dashboard UX", "agent": "gemini", "prompt": "Dashboard layout, navigasyon, kartlar, tablolar ve ayarlar ekranlarini tasarim.md dosyasina yaz.", "reads": ["plan.md"], "writes": ["tasarim.md"], "checkpoint": True, "timeout": 1200, "fallback_agent": "claude"},
            {"name": "SaaS Kodlama", "agent": "claude", "prompt": "Mock veriyle calisan SaaS dashboard MVP'sini kodla.", "reads": ["plan.md", "tasarim.md"], "writes": ["rapor.md"], "checkpoint": True, "timeout": 2400, "fallback_agent": "codex"},
            {"name": "Kalite Kontrol", "agent": "codex", "prompt": "Kod, UX ve calisma hatalarini kontrol.md dosyasina yaz.", "reads": ["rapor.md"], "writes": ["kontrol.md"], "checkpoint": True, "timeout": 1200},
            {"name": "Duzeltmeler", "agent": "claude", "prompt": "kontrol.md dosyasindaki problemleri gider.", "reads": ["kontrol.md"], "writes": ["rapor.md"], "checkpoint": True, "timeout": 1800, "fallback_agent": "codex"},
        ],
    },
    "CRM": {
        "summary": "CRM uygulamasi icin gereksinim, veri, UI, kodlama ve kontrol akisi.",
        "project_type": "crm",
        "stages": [
            {"name": "CRM Gereksinim", "agent": "codex", "prompt": "Musteri, firma, pipeline, gorev ve not akisini plan.md dosyasina yaz.", "reads": ["istek.md"], "writes": ["plan.md"], "checkpoint": True, "timeout": 1200},
            {"name": "CRM Arayuz", "agent": "gemini", "prompt": "Liste, detay, filtre, pipeline ve form ekranlarini tasarim.md dosyasina yaz.", "reads": ["plan.md"], "writes": ["tasarim.md"], "checkpoint": True, "timeout": 1200, "fallback_agent": "claude"},
            {"name": "CRM Kodlama", "agent": "claude", "prompt": "Mock veriyle calisan CRM MVP'sini kodla.", "reads": ["plan.md", "tasarim.md"], "writes": ["rapor.md"], "checkpoint": True, "timeout": 2400, "fallback_agent": "codex"},
            {"name": "CRM Kontrol", "agent": "codex", "prompt": "CRM akisini ve kod hatalarini kontrol.md dosyasina yaz.", "reads": ["rapor.md"], "writes": ["kontrol.md"], "checkpoint": True, "timeout": 1200},
        ],
    },
    "admin panel": {
        "summary": "Admin panel icin operasyon ekranlari ve kodlama akisi.",
        "project_type": "admin_panel",
        "stages": [
            {"name": "Admin Kapsam", "agent": "codex", "prompt": "Admin panel modullerini, yetki ihtiyacini ve veri akisini plan.md dosyasina yaz.", "reads": ["istek.md"], "writes": ["plan.md"], "checkpoint": True, "timeout": 1200},
            {"name": "Admin UI", "agent": "gemini", "prompt": "Yan menu, listeler, filtreler, detay ve ayar ekranlarini tasarim.md dosyasina yaz.", "reads": ["plan.md"], "writes": ["tasarim.md"], "checkpoint": True, "timeout": 1200, "fallback_agent": "claude"},
            {"name": "Admin Kodlama", "agent": "claude", "prompt": "Mock veriyle calisan admin panel MVP'sini kodla.", "reads": ["plan.md", "tasarim.md"], "writes": ["rapor.md"], "checkpoint": True, "timeout": 2400, "fallback_agent": "codex"},
            {"name": "Admin Kontrol", "agent": "codex", "prompt": "Admin panel hata ve eksiklerini kontrol.md dosyasina yaz.", "reads": ["rapor.md"], "writes": ["kontrol.md"], "checkpoint": True, "timeout": 1200},
        ],
    },
}
