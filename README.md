# AI Orkestra 🎻

Codex (ChatGPT) + Gemini + Claude Code'u **tek yerden, sırayla** çalıştıran
basit ve sağlam bir sistem. Üç ajan da aynı proje klasöründeki **dosyalar
üzerinden paslaşır** — yani biri `plan.md` yazar, öbürü onu okuyup üstüne
devam eder. Ekran kazıma / robot tıklama YOK, hepsi araçların resmi
otomatik (headless) komutlarıyla çalışır. Bu yüzden kırılgan değil.

## Neden kırılmaz?
- **Resmi komutlar:** `codex exec`, `agy -p` (Gemini icin Antigravity CLI), `claude -p`. Arayüz değişse
  bile bu komutlar çalışmaya devam eder.
- **Dosya üzerinden paslaşma:** ajanlar birbirine değil, ortak klasördeki
  dosyalara yazar. En sağlam yöntem budur.
- **Sohbet / handoff alanı:** `project/sohbet.md` ajanların birbirine bıraktığı
  kısa devir notlarını tutar. GUI içinde ayrı bir alanda canlı görünür.
- **Checkpoint'ler:** her adımdan sonra durup sana sorabilir. Yani bir adım
  yanlış giderse zincirleme bozulmaz, sen araya girersin.
- **Durum kaydı + resume:** bir adım patlarsa kaldığı yerden devam eder,
  baştan başlamaz. **Toparla** sihirbazı yarım işi 4 yoldan kurtarır
  (devam / dosyalara göre toparla / adımı tekrarla / fallback ajanla).
- **Doğrulama:** her adım bitince "üretmesi gereken dosya gerçekten oluştu mu"
  diye kontrol eder; kodlama adımlarından sonra otomatik sözdizimi smoke'u koşar.
- **Sağlık kontrolü:** Başlat'a basınca önce araçlar, yazma izni, workflow
  geçerliliği ve eksik girdiler denetlenir; sorun varsa akış hiç başlamaz.
- **Hata sınıflandırma:** adım patlarsa hata türü (limit / eksik araç / login /
  timeout / eksik çıktı / test / path-encoding) ve ne yapman gerektiği söylenir.
- **Limit algılama + fallback:** Codex/Gemini/Claude kota hatası verirse net
  uyarı gösterilir; tanımlıysa aynı adım fallback ajana devredilir.
- **Snapshot + run geçmişi:** her adım öncesi proje anlık görüntüsü alınır
  (geri dönülebilir); her çalıştırma `runs.jsonl`'a özetlenir. Workflow her
  değiştiğinde eski sürümü saklanır.

## Kurulum (tek seferlik)
Üç aracın da kurulu ve giriş yapılmış olması lazım:

```bash
# Claude Code
npm install -g @anthropic-ai/claude-code   # sonra: claude  (giris yap)

# Codex (ChatGPT)
npm install -g @openai/codex                # sonra: codex   (giris yap)

# Gemini icin Antigravity CLI
powershell -ExecutionPolicy Bypass -Command "irm https://antigravity.google/cli/install.ps1 | iex"
# sonra Antigravity hesabina giris yap; Maestro gemini adimlarini agy -p ile calistirir
```

> Önemli: bunlara **kendi aboneliklerinle** (Claude Pro, ChatGPT Pro, Google)
> giriş yaparsan ekstra API parası çıkmaz, her birinin kendi kullanım limiti
> harcanır. API anahtarı yerine `login` ile gir.

Python tarafı için (3.11+) bağımlılıkları kur:

```bash
pip install -e .            # customtkinter + pydantic (pyproject.toml'dan)
pip install -e .[dev]       # + pytest (testleri koşacaksan)
```

## 🖥️ Masaüstü Uygulama (en kolayı, butonlu pencere)

Çift tıklayıp açabileceğin pencereli uygulama. Adımları görürsün, butonlarla
çalıştırır, her checkpoint'te **Devam / Tekrarla / Durdur** butonlarıyla
müdahale edersin, çıktıyı canlı izlersin.

- **Windows:** `uygulama.bat` dosyasına çift tıkla.
- **Mac/Linux:** `./uygulama.sh` (ya da `python3 gui.py`).

Ana ekran sohbet gibidir: ortada ajanların konuşma/devir kartları akar, alttaki
mesaj kutusuna isteğini yazıp **Enter** (veya Gönder) ile akışı başlatırsın.
Üstteki **faz şeridi** nerede olduğunu gösterir:
`İstek → Sorular → Workflow onayı → Çalıştır → Kontrol → Teslim` — akış bitince
**Teslim paketi** butonu çıktıları tek zip'e paketler. Solda adım listesi
(tıklayınca adım detayı), altta **Toparla** (yarım işi kurtarma) dâhil kontrol
butonları vardır. Teknik log, dosyalar (Plan / Tasarım / Kodlama Raporu /
Kontrol), önizleme, performans, geçmiş (snapshot + çalıştırma kayıtları) gibi
gelişmiş paneller ayrı **Araçlar** penceresindedir.

> Not: Masaüstü uygulaması `customtkinter` kullanır (`pip install -e .` kurar).
> Linux'ta ayrıca `sudo apt install python3-tk` gerekebilir.

Akış başlamadan önce gereken gerçek ajan komutları kontrol edilir. Workflow hangi
ajanları kullanıyorsa onların komutları (`codex`, `gemini`, `claude`) PATH içinde
yoksa sistem sahte çalıştırmaya düşmez; hangi komutun eksik olduğunu söyler.

Gemini adimlari varsayilan olarak API key kullanmadan Antigravity CLI uzerinden
calisir: `agy --dangerously-skip-permissions -p`. Eski Gemini CLI'ye donmek
gerekirse `MAESTRO_GEMINI_BACKEND=gemini-cli` ortam degiskenini ayarla.
Antigravity icinde belirli bir modeli zorlamak istersen `MAESTRO_ANTIGRAVITY_MODEL`
degerini kullanabilirsin. Varsayilan ornek akista Gemini adimlarinin fallback'i
Claude olarak ayarlidir.

## Web Panel

Tarayicida calisan panel icin:

```bash
python web_panel.py --open
```

Windows'ta `web_panel.bat` dosyasina cift tiklayabilirsin. Panel varsayilan
olarak `http://127.0.0.1:8765` adresinde acilir (Python'un standart HTTP
sunucusu; ek web framework'u yok).

> Guvenlik: panel yerel olmayan bir adreste dinletilirse (`--host 0.0.0.0`)
> erisim token'i zorunludur — `--token` vermezsen otomatik uretilir ve
> baslangicta URL ile birlikte yazdirilir (`http://.../?token=...`).

Panelde:
- `Is Istegi` alanini kaydedip akisi bastan baslatabilir veya secili adimdan devam edebilirsin.
- `Kaynak` alanina eski proje klasoru veya tek kod dosyasi yolu girip taratabilirsin; panel `kaynak_context.md` uretir ve ajanlar akisa baslarken bunu okur.
- Codex/Gemini/Claude komut durumlari ustte gorunur.
- Checkpoint aciksa her adim sonunda `Devam`, `Tekrarla`, `Durdur` karari webden verilir.
- Canli log, ajan sohbeti, uretilen dosyalar, metrikler ve snapshot ozeti tek ekrandadir.

---

## Çalıştırma

**En kolay yol — menü:**
```bash
./menu.sh        # ya da: python3 menu.py
```
Renkli bir kontrol paneli açılır. Oradan akışı çalıştırır, kaldığı yerden
devam eder, önizleme yapar, logları ve çıktıları görürsün. Her şey tek yerden.

**Menüsüz, doğrudan komutla istersen:**

```bash
./run.sh                 # akışı baştan başlat (araçları da kontrol eder)
./run.sh --dry-run       # hiçbir şey çalıştırma, sadece ne yapacağını göster
./run.sh --yes           # checkpoint'lerde sorma, tam otomatik
./run.sh --resume        # bir önceki çalışmanın kaldığı yerden devam et
./run.sh --from 3        # 3. adımdan başlat
```

İlk kez deniyorsan menüden **5) Önizleme**'yi seç, akışı gör. Sonra
**1) Akışı çalıştır** ile başlat; her adım sonunda **Enter** ile devam,
**r** ile o adımı tekrarlat, **q** ile çık.

## Kendi projene uyarlama
Sadece **`workflow.py`** dosyasını düzenle. Orada:
- `PROJECT_DIR` → üç ajanın çalışacağı ortak klasör.
- `STAGES` → adımlar. Her adımda hangi ajan, ne yapacak, hangi dosyayı okuyup
  hangisini yazacak yazılı. Prompt'ları kendi işine göre değiştir.

Mantık hep aynı: **planla → tasarla → kodla → kontrol et → düzelt.**
Ajanları sırayla farklı işlere koşarsın, paslaşmayı dosyalar halleder.

## Dosyalar
- `gui.py` → masaüstü uygulama (sohbet-merkezli ana ekran + Araçlar penceresi)
- `web_panel.py` → tarayıcı paneli (operasyon dashboard'u)
- `menu.py` → terminal menüsü (cmd içinde çalışan)
- `orkestra.py` → motor: doğrulama, durum, snapshot, limit/fallback, sağlık kontrolü
- `runner.py` → ortak ajan süreç koşucusu (gui + web_panel aynı çekirdeği kullanır)
- `workflow.py` → iş akışı (senin düzenleyeceğin dosya)
- `ui_tabs/` → Araçlar penceresi sekme kurucuları
- `constants.py` / `models.py` / `logging_config.py` → şablonlar, pydantic durum modeli, dosya logu
- `tests/` + `pytest.ini` → test paketi (sahte ajanlarla uçtan uca)
- `pyproject.toml` → bağımlılık manifesti (`pip install -e .[dev]`)
- `uygulama.bat` / `uygulama.sh`, `web_panel.bat`, `menu.sh` / `run.sh` → başlatıcılar
- `project/` → çıktılar (`logs/`, `sohbet.md`, `.orkestra/` altında snapshot/metrik/run kayıtları)
- `DEGISIKLIKLER.md` → yapılan tüm iyileştirmelerin kaydı

## Testler

Gerçek ajanlara ihtiyaç duymadan tüm akışı sahte ajanlarla test edebilirsin:

```bash
python -m pytest -q     # 60+ test: motor, runner, web panel, güvenlik, toparlama
```

## Önemli not (dürüst olalım)
Bu sistem token harcar — otomatik çalışan her ajan arka planda çok iş yapar.
Aboneliklerinle kullanırsan ekstra **para** çıkmaz ama her aracın **limiti**
harcanır. Limiti az yormak için: prompt'ları net yaz, gereksiz adım koyma,
küçük işlerde `--dry-run` ile önce gör.
## Yeni istek akisi

Masaustu uygulamada sag alttaki **Is Istegi** alanina ne yaptirmak istedigini
yazip **Baslat** dugmesine bas. Bu metin `project/istek.md` dosyasina kaydedilir.
Codex once 3-5 netlestirme sorusu uretir. Cevaplardan sonra `istek.md`
yapilandirilmis final brief olur, Codex `workflow_generated.json` dosyasina bu
projeye ozel adimlari yazar. Uygulama bu workflow'u gosterir; sen onaylarsan
gercek Codex/Gemini/Claude zinciri baslar.

Yeni dosyalar:
- `project/brief_questions.json` -> Codex'in sordugu netlestirme sorulari
- `project/workflow_generated.json` -> onaylanacak otomatik ajan akisi
- `project/istek.md` -> final brief

Komut satirindan baslatacaksan:

```bash
python orkestra.py --request "Yapilacak uygulamayi burada tarif et"
```
