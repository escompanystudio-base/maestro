# ============================================================
#  IS AKISI TANIMI
# ============================================================
#  Uygulamada "Is Istegi" alanina yazdigin metin project/istek.md
#  dosyasina kaydedilir. Ajanlar sabit demo proje yapmak yerine bu
#  dosyayi ve sohbet.md devir notlarini okuyarak ilerler.
#
#  Ajan secenekleri: "codex", "gemini", "claude"
#
#  Bir adimdaki anahtarlar:
#    name       -> ekranda gorunecek adim adi
#    agent      -> hangi ajan calissin
#    prompt     -> ajana verilecek gorev
#    reads      -> bu adim baslamadan once VAR olmasi gereken dosyalar
#    writes     -> bu adim bitince OLUSMASI beklenen dosyalar
#    checkpoint -> True ise adim bitince sana "devam edeyim mi" diye sorar
#    timeout    -> saniye cinsinden sure siniri
#    fallback_agent -> ajan auth/urun hatasi verirse devralacak ajan
# ============================================================

PROJECT_DIR = "./project"

DEFAULT_TIMEOUT = 1800  # 30 dakika

STAGES = [
    {
        "name": "Planlama",
        "agent": "codex",
        "prompt": (
            "istek.md ve sohbet.md dosyalarini oku. Kullanicinin gercek istegini "
            "anla; sabit demo proje uretme. Uygulama/urun icin uygulanabilir bir "
            "plan cikar: amac, kapsam, ozellikler, sayfalar/ekranlar, veri modeli, "
            "teknoloji secimi, dosya yapisi ve kabul kriterleri. Sonucu plan.md "
            "dosyasina yaz. Kod yazma."
        ),
        "reads": ["istek.md"],
        "writes": ["plan.md"],
        "checkpoint": True,
    },
    {
        "name": "Arayuz Tasarimi",
        "agent": "gemini",
        "prompt": (
            "istek.md, sohbet.md ve plan.md dosyalarini oku. Plana gore arayuz "
            "tasarimini, ekran akislarini, bilesenleri, renk/duzen kararlarini ve "
            "kullanici deneyimi notlarini hazirla. Varsa uygulanabilir HTML/CSS "
            "iskeleti veya component notlarini da ekle. Sonucu tasarim.md dosyasina yaz."
        ),
        "reads": ["istek.md", "plan.md"],
        "writes": ["tasarim.md"],
        "fallback_agent": "claude",
        "checkpoint": True,
    },
    {
        "name": "Kodlama",
        "agent": "claude",
        "prompt": (
            "istek.md, sohbet.md, plan.md ve tasarim.md dosyalarini oku. Bu brief, "
            "plan ve tasarima gore calisir uygulama kodunu project klasorunde olustur "
            "veya mevcut kodu duzenle. Gereken dosya yapisini kur. Bitirince nasil "
            "calistirilacagini ve neleri yaptigini rapor.md dosyasina yaz."
        ),
        "reads": ["istek.md", "plan.md", "tasarim.md"],
        "writes": ["rapor.md"],
        "checkpoint": True,
    },
    {
        "name": "Kod Kontrolu",
        "agent": "gemini",
        "prompt": (
            "istek.md, sohbet.md, rapor.md ve projedeki kod dosyalarini oku. Kodu "
            "incele: kullanici istegini karsiliyor mu, hata/eksik ozellik/iyilestirme "
            "var mi, calistirma talimati yeterli mi? Bulgularini kontrol.md dosyasina "
            "madde madde yaz. Kodu degistirme."
        ),
        "reads": ["istek.md", "rapor.md"],
        "writes": ["kontrol.md"],
        "fallback_agent": "claude",
        "checkpoint": True,
    },
    {
        "name": "Duzeltmeler",
        "agent": "claude",
        "prompt": (
            "istek.md, sohbet.md ve kontrol.md dosyalarini oku. Kontrolde belirtilen "
            "hata ve eksikleri koda uygula. Gerekirse rapor.md dosyasini guncelleyip "
            "son durumu ve calistirma adimlarini ekle."
        ),
        "reads": ["istek.md", "kontrol.md"],
        "checkpoint": False,
    },
]
