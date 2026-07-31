# Değişiklikler

## Gemini Antigravity Backend
- Gemini adimlari varsayilan olarak `gemini -p` yerine Antigravity CLI ile calisir: `agy --dangerously-skip-permissions -p`.
- API maliyetinden kacmak icin `GEMINI_API_KEY` zorunlu degil; eski Gemini CLI'ye donmek icin `MAESTRO_GEMINI_BACKEND=gemini-cli` ayarlanabilir.
- Windows'ta yeni kurulan `agy.exe` aktif PATH'e hemen dusmese bile Maestro `%LOCALAPPDATA%\agy\bin\agy.exe` konumunu otomatik dener.

## Motor
- Subprocess çağrıları güvenli hale getirildi: `stdin=DEVNULL`, UTF-8 uyumlu ortam, Windows/POSIX süreç ağacı öldürme ve timeout desteği eklendi.
- `workflow.py` adımları başlamadan doğrulanıyor; eksik `name`, `agent`, `prompt`, hatalı `reads/writes`, bilinmeyen ajan ve geçersiz timeout artık net hata veriyor.
- Bozuk `.orkestra_state.json` dosyası akışı çökertmiyor; temiz başlangıca dönüyor.
- Proje klasörü artık çalıştırılan terminalin konumuna değil, Maestro klasörüne göre çözülüyor.
- Windows terminalinde ANSI ve Unicode çıktı daha dayanıklı hale getirildi.
- `project/sohbet.md` ortak sohbet/handoff alanı eklendi; her ajan promptu bu dosyayı okuyup iş bitince devir notu bırakacak şekilde otomatik sarılıyor.
- Orkestra da adım başlangıcı, başarı, hata, eksik girdi ve timeout durumlarını `sohbet.md` içine yazıyor.
- Gerçek akış başlamadan önce gerekli ajan komutları kontrol ediliyor; eksik `codex`, `gemini` veya `claude` varsa sahte çalıştırma yapılmadan net hata veriliyor.
- Eski Gemini CLI backend'i açılırsa `Gemini Code Assist for individuals` / `UNSUPPORTED_CLIENT` hatası aynı adımı `fallback_agent` ile otomatik devrediyor. Örnek akışta Gemini adımları için fallback `claude`.
- Legacy Gemini CLI API key kullanımı için `GEMINI_API_KEY` user environment değerinden okunuyor; varsayılan Antigravity backend'i bu değere ihtiyaç duymaz.

## Masaüstü Uygulama
- Arayüz Treeview tabanlı modern koyu düzene taşındı; durum, ajan ve süre sütunları eklendi.
- İlerleme çubuğu, canlı adım süresi ve tamamlanan adım süreleri eklendi.
- Worker thread tkinter değişkenlerine doğrudan dokunmuyor; checkpoint ayarı başlatma sırasında kopyalanıyor.
- Hata olsa bile butonlar tekrar açılıyor; worker akışı `try/finally` ile korunuyor.
- Canlı subprocess logu korunurken timeout watchdog çalışıyor.
- Durdur ve pencere kapatma akışları süreç ağacını temizliyor.
- Uygulama içinden `workflow.py` görüntüleme/düzenleme eklendi; kaydetmeden önce söz dizimi ve adım alanları doğrulanıyor.
- Sağ panelde ayrı “Sohbet / Handoff” alanı eklendi; `sohbet.md` canlı takip ediliyor.
- Başlatma sırasında gerçek ajan komutları eksikse GUI akışı durdurup kullanıcıya hangi komutların kurulması gerektiğini gösteriyor.

## Menü ve Başlatıcılar
- `menu.py` mutlak yol ile `orkestra.py` çalıştırıyor; farklı klasörden başlatma sorunu giderildi.
- Menüde bozuk state ve workflow hataları kullanıcıya net gösteriliyor.
- README ile uyum için `run.sh` ve `menu.sh` eklendi.
- Terminal menüsüne `sohbet.md` görüntüleme seçeneği eklendi.

## Doğrulama
- `python -m py_compile orkestra.py gui.py menu.py`
- `python orkestra.py --dry-run --yes`

---

# Yol Haritası Uygulaması (Claude)

Codex'in analiz/yol haritası dokümanına göre yapılan iyileştirmeler.

## Faz 1 — Hızlı düzeltmeler
- **menu.py:** gizli `11) İstek düzenle` seçeneği MENU listesine eklendi (kod vardı ama listede görünmüyordu).
- **orkestra.py:** `_normalize_stage` içindeki elle yazılmış fallback eşlemesi (`gemini→claude`, `claude→codex`) kaldırıldı; tek kaynak `DEFAULT_FALLBACK_AGENTS`'ten okunuyor (mimari tutarlılık).
- **Sessiz `except Exception` blokları (23 adet, orkestra.py + gui.py):** artık hatayı sessizce yutmuyor; tanı amaçlı logger'a yazıyor (kritik yerlerde `exc_info`/traceback ile, best-effort olanlar `debug` seviyesinde).

## Faz 2a — Sabitlerin ayrılması
- `PROJECT_TEMPLATES` ve `BUILTIN_WORKFLOWS` sözlükleri gui.py'den yeni **`constants.py`** modülüne taşındı (Single Responsibility); gui.py import ediyor.

## Faz 3 — Mimari
- **`logging_config.py`:** rotasyonlu dosya logu (`maestro.log`, `RotatingFileHandler`, UTF-8). orkestra/gui/menu bu merkezi logger'a bağlandı.
- **`models.py`:** pydantic `OrkestraState` modeli. `_clean_state` artık elle dict kontrolü yerine pydantic ile doğruluyor/temizliyor; geri kalan kod bozulmasın diye **dict arayüzü korundu**.

## Faz 4 — Testler
- **`pytest.ini` + `tests/`** kuruldu. **`tests/fake_agent.py`** sahte ajan scripti gerçek codex/gemini/claude yerine geçer (`WRITE:`/`FAILNOW`/`LIMITFAIL`/`HANG` belirteçleri + Türkçe/emoji encoding testi).
- **`tests/test_state.py`:** state round-trip/bozuk/eksik dosya, snapshot oluştur-listele-geri yükle-diff, workflow doğrulama + fallback sabiti, pydantic model.
- **`tests/test_pipeline.py`:** uçtan uca sahte ajan akışı — dosya üzerinden paslaşma, ajan hatası, eksik girdi/çıktı, timeout (süreç ağacı öldürme), fallback devri, "araç kurulu değil" (FileNotFoundError).
- Sonuç: **21/21 test geçiyor.**

## Bilinçli ertelendi (kullanıcı kararı)
- **Faz 2b/2c:** gui.py'nin (~3350 satır) tab modüllerine (`ui_tabs/`) ve View/Controller (MVC) ayrımına bölünmesi. Büyük/riskli ve ekranda manuel doğrulama gerektirdiği için bu oturumda **yapılmadı**; çalışan GUI olduğu gibi korundu. İleride ayrı bir oturumda ele alınabilir (öneri: önce orkestrasyon mantığını `controller.py`'ye çıkarmak — böylece sahte ajanlarla test edilebilir olur).

## Doğrulama (Claude)
- `python -m py_compile constants.py logging_config.py models.py orkestra.py gui.py menu.py`
- `python -m pytest -q` → **21 passed**

---

# Token İsrafı Teşhisi ve Düzeltmeleri (Claude)

Kullanıcı "uygulama çok token yiyor, sürekli tekrar çalışıyor" dedi. Loglar (`project/.orkestra/metrics.jsonl`, `project/logs/web_*.log`) incelenerek kanıta dayalı teşhis yapıldı.

## Teşhis
- **Otomatik sonsuz döngü YOK.** Asıl sebep: pahalı planlama adımı (codex, 5-13 dk) **her "Başlat"ta sıfırdan tekrar koşuyordu** — `_launch`, `start_idx==1` iken durum dosyasını siliyordu. 4 tam planlama ≈ 32 dk codex xhigh.
- Bu, ChatGPT/codex **kullanım limitini tüketti** → sonra codex anında `You've hit your usage limit` ile patlıyor (~8s) = "çalışıyor ama hızlı bitiyor" görüntüsü.
- Uygulama codex'in limit hatasını **tanımıyordu** (yalnızca gemini/claude tanınıyordu) → kullanıcıya net mesaj yoktu.
- (Ayrı kusur) claude bazen bayat fnm/npm shim yolu yüzünden anında patlıyordu — bunu **Codex** `resolve_tool` ile düzeltti.

## Düzeltmeler
- **orkestra.py:** `USAGE_LIMIT_MARKERS` + `is_usage_limit_error()` + `usage_limit_notice()` eklendi; `fallback_agent_for` artık **codex** limitini de tanıyor. Tüm ajanlar için net Türkçe "kullanım limiti doldu" mesajı (mümkünse "tekrar deneme saati" ile).
- **gui.py (limit mesajı):** bir adım kullanım limiti yüzünden patlayınca kullanıcıya belirgin uyarı (messagebox) gösterilir — duvara toslayıp tekrar denemeyi önler.
- **gui.py (resume-guard):** aynı workflow'da tamamlanmış adım varken `_launch(start_idx=1)` çağrılınca, durum silinip pahalı adım tekrar koşulmadan önce kullanıcıya sorulur: **Devam et (resume) / Baştan başla / İptal**.

## Doğrulama
- `python -m py_compile orkestra.py gui.py` + `python -c "import gui"`
- `python -m pytest -q` → **35 passed** (Codex'in eklediği testler dâhil)
- Not: GUI'nin davranışsal değişiklikleri (limit mesajı + resume-guard) ekranda **manuel test** gerektirir.

---

# Sohbet/Akış Paneli Yeniden Tasarımı (Claude)

Kullanıcı: canlı çıktıyı okuduğu alan kafa karıştırıyordu; Claude-vari temiz bir konuşma görünümü istedi.

## Değişiklik
- `gui.py` "Sohbet" sekmesindeki çıktı alanı `CTkTextbox`'tan **`CTkScrollableFrame` + gerçek kart widget'larına** çevrildi.
- Her mesaj artık ayrı bir kart: konuşmacıya göre renkli başlık (● Sen / Codex / Gemini / Claude / Orkestra), zaman damgası ve okunaklı gövde. ASCII kutu çizgileri (┌──└──) kaldırıldı.
- Kullanıcı mesajları hafif farklı arka planla ayrışır; gövde metni pencere genişliğine göre `wraplength` ile sarılır (`_on_chat_resize`).
- `_speaker_label` kısa isimlere çevrildi; `_speaker_color` eklendi; `_refresh_chat` içindeki ölü (erişilemez) eski textbox kodu temizlendi.
- Ham `LOG` paneli hata ayıklama için olduğu gibi duruyor.

## Doğrulama
- `python -m py_compile gui.py` + `python -c "import gui"`
- Başsız (headless) render testi: app örneklenip `_render_chat` örnek veriyle koşturuldu → 3 kart, resize ve boş durum sorunsuz; istisna yok.
- `python -m pytest -q` → **35 passed**
- Not: görsel sonuç (renk/boşluk) ekranda gözle onaylanmalı.

---

# Claude-vari Arayüz + İki Katman (Basit / Operasyon) (Claude)

Kullanıcı "uygulama Claude Code gibi, baya gelişmiş olsun" dedi. İki katmanlı yön: açık **Basit Mod** (ana ekran) + koyu **Operasyon Modu** (Araçlar penceresi).

## Açık tema + Claude düzeni
- `gui.py` tamamen **açık (claude.ai) temaya** geçti (renk sabitleri krem/beyaz + koyu yazı; `set_appearance_mode("light")`).
- Ana ekran: solda sade adım listesi (Durum + Adım; Ajan/Süre gizli), ortada avatarlı konuşma kartları, altta **composer** (mesaj kutusu + ▶ Gönder + **Enter ile gönder**, Shift+Enter yeni satır).
- 10 sekme ayrı **⚙ Araçlar** penceresine (`CTkToplevel`) taşındı; ham log "Teknik Log" sekmesinde. Üst başlık inceltildi (28px → 17px).

## Codex + Antigravity UX yol haritası
- **#1 Akıllı Devam:** durum çubuğu "kaldığın yer · sonraki adım" gösterir (`_update_idle_status`).
- **#2 Ajan adım detayı:** sol listede adıma tıkla → okur/yazar/fallback/checkpoint/timeout (`_on_stage_select`).
- **#3 Risk & Limit:** araç hazırlık (● / ○) + akış için eksik araç uyarısı (+ limit/tekrar-çalıştırma uyarıları zaten var).
- **#4 Artifact review:** Plan/Tasarım/Rapor/Kontrol çıktıları Araçlar "Dosyalar" sekmesinde (mevcut).
- **#5 Operasyon Modu (koyu):** Araçlar penceresi + sekme çubuğu koyu chrome'a alındı (#0B1120 / #0F172A).
- **#6 Snapshot zaman çizgisi:** Araçlar "Geçmiş" sekmesinde snapshot + geri yükle + diff (mevcut).

## Sağlamlık + temizlik
- **Kapanış düzeltmesi:** `on_close` artık Araçlar (Toplevel) penceresini önce yok ediyor → kapanış yarışı/exit 255 giderildi (artık exit 0).
- Kullanıcı isteğiyle `project/` çalışma verisi (sohbet/çıktı/snapshot/metrics) **temizlendi** — temiz başlangıç.

## Doğrulama
- Her değişiklik sonrası başsız smoke test (CTk `root.withdraw()` + `OrkestraApp`) + son toplu relaunch.
- `python -m pytest -q` → **35 passed**.

---

# Kod İnceleme Maddeleri Uygulaması (Claude)

Codex/Antigravity inceleme listesinden uygulananlar:

- **Kalite skoru bug'ı (web_panel.py):** `last_test_result` okunuyordu ama hiç set edilmiyordu; üstelik skorlama (`_record_metric` → `score_stage_quality`) smoke testten ÖNCE koşuyordu. Smoke test artık metrikten önce çalışır ve `self.last_test_result` set edilir → kalite skoru gerçek test sonucunu görür.
- **Web panel token güvenliği:** `--token` argümanı; yerel olmayan host'ta token otomatik üretilip zorunlu kılınır. Doğrulama: `Authorization: Bearer`, `maestro_token` cookie'si veya `?token=` (ilk girişte cookie bırakılır, frontend değişikliği gerekmez). 401 dönen mevcut panel artık "çalışıyor" sayılır.
- **`shutdown_server` çökmesi:** hiç akış başlatılmadan kapanışta `app.worker` AttributeError veriyordu → `getattr` ile düzeltildi (auth smoke testi yakaladı).
- **GUI workflow editörü exec riski:** doğrulama artık `exec` yerine **AST** ile (PROJECT_DIR/DEFAULT_TIMEOUT/STAGES yalnızca literal atamalardan `ast.literal_eval`); kod hiç çalıştırılmaz. Gerçek workflow.py ile doğrulandı.
- **Bağımlılık manifesti:** `pyproject.toml` eklendi (pydantic, customtkinter; extras: dev=pytest, monitor=psutil).
- **Test kapsamı:** `tests/test_web_panel_auth.py` — token 401/200/cookie, token'sız yerel kullanım, worker'sız kapanış, smoke→kalite-skoru bağlantısı. Toplam: **41 passed**.
- **Graphify:** graf güncellendi + `graphify install` koşuldu.

**Bilinçli ertelenen:** wizard tarzı ürün akışı (büyük UX işi).

---

# Core Runner Ayrımı + Varsayılan Smoke (Claude)

İnceleme listesinin en büyük iki maddesi uygulandı.

## `runner.py` — ortak ajan süreç koşucusu
- gui.py ve web_panel.py'deki **kopya `_run_one` döngüleri tek kaynağa** indirildi: `runner.run_agent_stage(...)`.
- Web panelin daha evrimli döngüsü temel alındı: canlı çıktı + akış içi limit/kota fallback tespiti, zaman aşımı, per-ajan **sessizlik (stuck) tespiti**, **çıktı-hazır zarafet süresi** (output grace), kullanıcı "tamamlandı say"/"fallback tetikle" olayları (opsiyonel), Antigravity transcript özeti.
- İki arayüz callback'lerle adapte oldu (log, süreç kaydı, aktivite). **GUI bu sayede stuck-tespiti ve genel output-grace kazandı** (önceden yalnız web panelde vardı).
- Doğrulama: web panel testleri ortak runner üstünde **birebir yeşil** (Antigravity zorunlu-tamamlama dahil); GUI yolu başsız sahte-ajan testiyle doğrulandı (başarı → dosya üretildi, HANG → timeout).

## Varsayılan sıfır-maliyet smoke (web panel)
- `test_command` tanımlı değilse ve adım kodlama/düzeltme ise (`kod/code/fix/düzelt/implement`), projede .py varsa **`compileall` sözdizimi smoke'u** otomatik koşar (`_default_test_command`). Token harcamaz.
- Debug sırasında özellik kendini kanıtladı: sahte ajanın yazdığı geçersiz .py'yi gerçek `SyntaxError` olarak yakalayıp karar bekleyişine geçti.
- Testler: kodlama adımında varsayılan smoke koşar (success), planlama adımında koşmaz.

## Doğrulama
- `python -m pytest -q` → **43 passed** · graf güncellendi.

---

# Wizard Faz Şeridi + Teslim Paketi (Claude)

İnceleme listesinin son maddesi (#8, hafif sürüm): ana akış artık görünür bir sihirbaz gibi.

- **Faz şeridi (gui.py, topbar):** `İstek → Sorular → Workflow onayı → Çalıştır → Kontrol → Teslim`. Aktif faz mavi, tamamlananlar yeşil, bekleyenler soluk. Kancalar: akıllı başlatma → Sorular; workflow onay penceresi → Workflow; çalıştırma → Çalıştır; akış biterse → Teslim (durursa → Kontrol); Sıfırla → İstek.
- **Teslim fazında "📦 Teslim paketi" butonu** belirir; `orkestra.create_delivery_package` ile çıktılar `project/packages/` altına zip'lenir.
- **Sağlamlık:** `_set_phase` şerit kurulmamış arayüz varyantında sessizce atlar (Codex'in `_build_codex_ui` yeniden yazımıyla çakışmaya dayanıklı). Not: Codex `_build_ui`'yi `_build_codex_ui`'ye devretmiş ve eski gövde metod içinde erken `return` sonrası **ölü kod** olarak duruyor; şerit canlı bölgeye kuruldu, ölü bölge temizliği ayrı işe bırakıldı.

## Doğrulama
- Başsız test: 6 fazın vurgusu + Teslim butonunun yalnız Teslim fazında görünmesi doğrulandı.
- `python -m pytest -q` → **43 passed**.

---

# Faz 2 Tamamlanışı: Sekme Modülleri + View/Controller (Claude)

Yol haritasının bekleyen son iki maddesi kapatıldı.

- **#5 Sekme bölmesi:** 9 sekme kurucusu (`_build_files_tab` … `_build_setup_tab`, 179 satır) **`ui_tabs/` paketine** taşındı (files_tab.py, preview_tab.py, marketplace_tab.py, metrics_tab.py, file_map_tab.py, terminal_tab.py, history_tab.py, prompts_tab.py, setup_tab.py). gui.py'deki metodlar tembel-delege stub'lara indi (döngüsel import yok; her modül ihtiyaç duyduğu adları `from gui import ...` ile alır — adlar AST'den hesaplandı, elle değil).
- **#6 View/Controller:** süreç/orkestrasyon mantığı zaten `runner.py`'ye çıkarılmıştı; sekme bölmesiyle birlikte pratik ayrım tamamlandı (görünüm kurucuları ui_tabs'ta, süreç runner'da, veri/doğrulama orkestra+models'ta).
- Refactor **script-güdümlü** yapıldı (yedek scratchpad'te): elle taşıma hatası riski yok.

## Doğrulama
- Derleme (gui + 9 modül) · **43/43 test** · başsız duman: init'te 9 sekme gerçekten kuruldu, tüm widget referansları yerinde, faz şeridi + kart render + temiz kapanış OK.

---

# Operasyon Paketi: 8 Maddelik İyileştirme Listesi (Claude)

Kullanıcının verdiği listeden uygulananlar (çekirdek mantık orkestra.py'de test edilebilir saf fonksiyonlar; GUI bunlara bağlandı):

- **Run geçmişi:** her çalıştırma `runs.jsonl`'a kaydedilir (istek özeti, workflow hash, ajanlar, adım süreleri, durum/hata, üretilen dosyalar). Araçlar > Geçmiş sekmesinde "Çalıştırma Geçmişi" paneli.
- **Otomatik hata sınıflandırma:** `classify_failure` — limit / eksik-araç / login / timeout / eksik-çıktı / test-hatası / path-encoding / ajan-sapması + Türkçe öneri. Adım patlayınca GUI "⛔ Hata türü: … — Öneri: …" gösterir; run kaydına da yazılır.
- **Workflow versiyonlama:** `save_generated_workflow` artık değişen her workflow'un eski sürümünü `.orkestra/workflow_versions/` altına saklar; `list/restore/diff_workflow_versions` fonksiyonları hazır (geri dönüş + birleşik fark).
- **Başlamadan sağlık kontrolü:** `preflight_check` — workflow geçerliliği, eksik CLI'lar, proje klasörü yazılabilirliği, ilk adımın eksik girdileri, önceki yarım iş. "Başlat"ta hatalar engeller, uyarılar onaya bağlanır.
- **Yarım işi toparlama sihirbazı:** footer'da "Toparla" → tek pencerede 4 yol: son başarılı adımdan devam / **dosyalara göre toparla** (`infer_completed_from_outputs` ile) / adımı tekrar çalıştır / sıradaki adımı fallback ajanla çalıştır.
- **Artifact review:** Dosyalar sekmesi adları rolleriyle: İstek / Plan / Tasarım / Kodlama Raporu / Kontrol / Hata.
- **Ajan bütçe paneli:** Performans sekmesindeki mevcut per-ajan özet (koşu/süre/hata/fallback) + run geçmişindeki hata sınıfları bu ihtiyacı karşılıyor (yeni ekran eklenmedi).
- **Güvenli işlem onayı:** kısmen mevcut (sıfırlama/geri yükleme onayları); ajanların kendi dosya işlemleri tasarım gereği tam-otomatik olduğundan ek kapı eklenmedi (bilinçli karar).

## Doğrulama
- 20 yeni birim test (`tests/test_ops_core.py`): sınıflandırma kategorileri, run kayıtları, versiyonlama+restore+diff, preflight senaryoları, dosyadan-toparlama. Toplam: **63 passed**.
- Başsız GUI duman: runs paneli gerçek kayıtla doldu, Toparla penceresi açılıp kapandı, artifact sekmeleri kuruldu.

---

# Altyapı Paketi: Olay Logu + Provider Sistemi + CI (Claude)

İkinci inceleme listesinden (5 madde):

- **Ortak runner (madde 16):** zaten yapılmıştı — `runner.py` hem GUI hem web panelde bağlı (doğrulandı).
- **Yapısal olay logu:** `.orkestra/events.jsonl` — makine okunur olaylar: `run_started`, `stage_started`, `stage_finished` (ok/sebep/süre), `fallback_detected`, `test_failed`, `run_finished`. Runner adım olaylarını, GUI/web panel run olaylarını yazar. Kullanıcı logundan tamamen ayrı.
- **Provider/plugin sistemi:** Maestro kökündeki `providers.json` ile yeni ajan CLI'ları eklenebilir (aider, cursor, yerel LLM...): `{"aider": {"command": ["aider", "--message", "{prompt}"], "fallback": "claude"}}`. İmport sırasında otomatik yüklenir; doğrulayıcılar ve fallback zinciri yeni ajanı otomatik tanır. Bozuk girdiler atlanır, uygulama çökmez.
- **CI:** lokal `ci.bat` (derleme → encoding bekçisi → import duman → pytest) + `.github/workflows/ci.yml` (ubuntu, py3.12). CI kendisi çalıştırılarak doğrulandı.
- **Encoding:** tüm md/py/bat/toml/sh dosyaları tarandı — **mojibake yok, hepsi UTF-8** (incelemede görülen bozukluk cp1254 konsol çıktısıydı, dosyalar değil). `tools/check_encoding.py` bekçisi CI'ya bağlandı; kendi kaynağı bilerek saf ASCII (kendini yakalayamaz — ilk sürümde yakalamıştı, düzeltildi).

## Doğrulama
- `ci.bat` → **CI OK, 67 passed** (4 yeni test: olay roundtrip, provider kaydı + bozuk spec reddi, uçtan-uca olay akışı).

---

# Konsolidasyon + Gözlemlenebilirlik Kapanışı (Claude)

Kalan bilinçli eksikler kapatıldı:

- **`orkestra.run_stage` runner'a taşındı (üçüncü kopya döngü silindi):** CLI'nin inline subprocess/timeout/antigravity bloğu artık `runner.run_agent_stage` üstünde. CLI böylece sessizlik (stuck) tespiti, çıktı-zarafeti, akış-içi limit yakalama ve `stage_started/finished` olay kayıtlarını da kazandı; ajan çıktısı eskisi gibi çalıştırma log dosyasına akar. Hata mesajları sebep-temelli (`timeout/stuck/not-found/exit`). 10 CLI testi ortak runner üstünde birebir yeşil.
- **Ajan Karar Kayıtları paneli:** Araçlar > Geçmiş'e eklendi — her adım için kim / neye baktı / neyi değiştirdi / özet (decisions.jsonl artık görünür).
- **Web API gözlemlenebilirlik uçları:** `GET /api/runs`, `/api/decisions`, `/api/events` (auth kapsamında; testli).

Doğrulama: `ci.bat` **100 passed** + mega-duman **14/14**. Kalan tek bilinçli erteleme: menu.py'nin üretilmiş-workflow sistemine bağlanması (legacy ama tutarlı çalışıyor).

---

# Kusursuzluk Turu: 3 Paralel Derin İnceleme + 20 Düzeltme (Claude)

Üç uzman alt-ajan kod tabanını paralel taradı (motor / GUI thread-güvenliği / web+testler): **25 bulgu**, hepsi kanıt satırıyla. Doğrulanıp düzeltilenler:

## Kritik (YÜKSEK)
- **gui `_launch` kalıcı kilit:** `_busy(True)` preflight kapılarından ÖNCE açılıyordu; sağlık kontrolü akışı engellerse uygulama sonsuza dek "meşgul" kalıyordu → busy artık tüm kapılardan sonra.
- **Hayalet değişkenli çift metrik:** eksik-girdi dalında `miss_out/elapsed/active_stage` daha tanımlanmadan kullanan artık satır → ilk turda `UnboundLocalError` (genel "beklenmeyen hata"ya dönüşüyordu). Silindi.
- **Worker → tkinter Var okumaları:** `max_attempts/agent_fallback/long_step/auto_fix` worker'dan okunuyordu (threaded-Tcl'de `RuntimeError` ile koşuyu öldürebilir) → değerler `_launch`'ta ana thread'de kopyalanır, worker kopyayı okur.
- **`infer_completed_from_outputs` İKİ KEZ tanımlıydı** (Codex ikincisini eklemiş): gölgeleyen sürüm bitişik-olmayan liste dönebiliyordu ([1,3]) → resume adım atlardı. Önek-güvenli tek tanım kaldı; regresyon testi eklendi.

## Mimari (mega-duman yakaladı)
- **`ui()` artık Tcl'e hiç dokunmuyor:** worker→UI çağrıları thread-güvenli kuyruğa yazılır, ana thread pompası çalıştırır. `root.after`'ın worker'dan RuntimeError'la sessizce kaybolması (busy kilidinin açılamaması) sınıf olarak yok edildi.

## Motor
- `classify_failure` öncelik düzeltmesi (test/eksik-çıktı sebebi, çıktıdaki "limit/429" kelimelerine yenilmez) · runner fallback-tespit yarışı (limit sinyali kaybolamaz; `finally`'de süreç ağacı öldürme → Ctrl+C yetim bırakmaz) · `--compare` Ctrl+C mesajı · **JSONL kilitli ekleme** (`_locked_append`: GUI+web aynı projeye yazarken satır karışamaz; Win `msvcrt`/POSIX `fcntl`) · providers.json yerleşik ajanı ezemez · `assess_run_quality` "test" alt-dizi yanılgısı giderildi · `suggest_agent` eşitlik önceliği belirlendi.

## Web panel
- **Token log'a sızmaz** (`log_message` redaksiyonu, testli) · bayat force-complete/fallback sinyali yeni adımı öldüremez (her adım başında temizlenir, testli) · checkpoint/test-karar bekleyişindeki kayıp-uyandırma yarışı kapatıldı (event önce temizlenir + `decision` da yoklanır) · `Content-Disposition` CRLF enjeksiyonu kapatıldı (safe_name) · Bearer/cookie sabit-zamanlı ve düzgün ayrıştırılır · `status_payload` proc yarışı (500 riski) kapatıldı · başarısız smoke denemesi artık metriğe yazılır.

## GUI (diğer)
- Durdur artık **ad-hoc** koşuları ve 180sn'lik test kontrolünü de öldürebilir (süreç kaydı + Popen) · kapanışta TÜM açık diyaloglar yok edilir (grab/TclError artıkları bitti) · run-kaydı süre sözlüğü kopya ile okunur · Toparla "dosyalara göre" taşması sahte "TAMAMLANDI" yerine net bilgi verir.

## Doğrulama
- **13 yeni test** (regresyonlar + `test_runner_direct.py`: timeout/force/fallback-tespiti/bayat-sinyal + POST-auth 401 + static traversal + token-redaksiyon) → `ci.bat` **99 passed**.
- Mega-duman: **14/14** başsız kontrol (kanban, mod, sihirbaz, aksiyon panelleri, adhoc koşu, kalite etiketi, bildirim, fazlar).

**Bilinçli ertelenen:** `orkestra.run_stage`'in inline döngüsünün runner'a taşınması (CLI yolu kendi testleriyle sağlam; ayrı odaklı tur) · menu.py'nin üretilmiş-workflow sistemine bağlanması.

---

# Kullanılabilirlik Paketi: Sihirbaz / Modlar / Kartlar / Bildirim / Aksiyonlar / Kalite (Claude)

7-12 numaralı istek listesi uygulandı:

- **Başlangıç sihirbazı:** footer'da "✨ Sihirbaz" — istek + proje tipi / hedef platform / tasarım tarzı / test beklentisi seçimleri (`compose_wizard_brief` ile yapısal blok olarak isteğe eklenir) → doğrudan akıllı başlatmaya gider. "Farketmez" seçimleri yazılmaz.
- **Basit / Uzman mod:** faz şeridinin yanında anahtar. Basit modda yalnız Sihirbaz/Başlat/Devam/Durdur; Adımdan/Toparla/Önizleme/Araçlar/Limitler/Roller/Workflow/Sıfırla gizlenir. Tercih `.maestro_ui.json`'da kalıcı.
- **İş kartları:** Araçlar > "İş Kartları" — adımlar Trello benzeri 4 kolonda (Bekliyor / Çalışıyor / Kontrol gerek / Tamamlandı), ajan + süre etiketiyle; her durum değişiminde tazelenir.
- **Bildirim sistemi:** iş bitti / hata / checkpoint beklemede → farklı Windows sesleri (`winsound`) + görev çubuğunda pencere yanıp sönmesi (`FlashWindowEx`, stdlib ctypes). Toast yerine bilinçli tercih: sıfır ek bağımlılık.
- **Hata çözüm butonları:** adım patlayınca panel açılır — "Claude ile düzelt" / "Codex'e kontrol ettir" (ana akışın state'ini BOZMADAN tek seferlik ad-hoc ajan koşusu) / "Son snapshot'a dön" / "Testleri tekrar çalıştır" (compileall + varsa pytest; token harcamaz).
- **Sonuç kalite etiketi:** `assess_run_quality` — hazır / eksik (hangi dosyalar) / test geçmedi / kontrol gerekli. Akış sonunda konuşmaya yazılır, run kaydına eklenir ve Geçmiş panelinde her satırda görünür.

## Doğrulama
- 2 yeni birim test (kalite etiketi senaryoları, sihirbaz brief kompozisyonu) → `ci.bat` **86 passed**.
- Başsız duman: kanban 4 kolon + kartlar, mod gizle/göster, bildirim, sihirbaz ve aksiyon pencereleri.

---

# Akıllı Ajan Katmanı: Karar/Hafıza/Strateji Paketi (Claude)

6 maddelik istek listesi uygulandı (çekirdek orkestra.py'de, uçlar GUI/web'e bağlı):

- **Ajan karar kayıtları:** her başarılı adımda `decisions.jsonl`'a kayıt — ajan, baktığı dosyalar (reads), değiştirdikleri, ve sohbet.md'deki son devir notundan çıkarılan özet (`extract_last_handoff`). Devir notu talimatı "NEDEN o yaklaşımı seçtin"i de ister.
- **Ajan karşılaştırma modu:** `run_agent_comparison` — aynı görev seçili ajanlara AYRI klasörlerde (`karsilastirma/<ajan>/`) yaptırılır; süre/sonuç/üretilen dosyalarla `karsilastirma.md` raporu. CLI: `python orkestra.py --compare "görev" [--compare-writes a.md,b.md]`. (Uyarı: token × ajan sayısı.)
- **Otomatik ajan seçimi:** workflow'da `"agent": "auto"` yazılabilir — `suggest_agent` iş türüne göre çözer (UI/tasarım→gemini, test/plan/kontrol→codex, kod/refactor→claude).
- **Retry stratejisi:** `retry_strategy(kategori)` — limit/sapma→fallback, timeout→aynı ajan, eksik-çıktı/test→**prompt güçlendirilerek** tekrar (GUI retry döngüsüne bağlandı), eksik-araç/login/path→kullanıcıya sor.
- **Context sıkıştırıcı:** `build_context_summary` → `proje_ozeti.md` (dizin ağacı + önemli/en güncel dosyaların ilk satırları, boyut sınırlı). Özet varsa prompt sarmalayıcısı ajanlara "önce özeti oku, tüm dosyaları gezme" der.
- **Ajan hafızası:** `.orkestra/hafiza.md` — stack/karar/yasaklı tercihler; her ajan promptuna otomatik enjekte edilir (sınırlı uzunlukta) ve ajanlara "kalıcı karar oluştuysa hafızaya tek satır ekle" talimatı verilir.

## Doğrulama
- 17 yeni birim test: handoff çıkarma, karar kayıtları, hafıza (+prompt enjeksiyonu), context özeti (+prompt ipucu), suggest_agent + `auto` çözümü, retry eylem tablosu, sahte ajanlarla uçtan uca karşılaştırma modu.
- `ci.bat` → **84 passed**, encoding temiz, importlar sağlam.

---

# Ölü Kod Temizliği (Claude)

- AST tabanlı tespit: fonksiyon gövdesinde çıplak `return` sonrası erişilemez ifadeler tarandı (gui, web_panel, orkestra, menu).
- **349 satır ölü kod silindi** (tamamı gui.py): `_build_codex_ui` içindeki eski UI gövdesi (328 satır — Codex'in yeniden yazımından artakalan) + `on_resume` (11) + `on_from` (10) artıkları.
- Doğrulama: tarama tekrarında ölü kod kalmadı; derleme + **43/43 test** + tam başsız duman testi (init, faz şeridi, sohbet kartları, sahte-ajan koşusu, temiz kapanış). Silme öncesi yedek scratchpad'e alındı.
