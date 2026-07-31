# Maestro Gelistirme Plani

Bu plan Maestro'yu sadece ajanlari sirayla calistiran bir panel olmaktan cikarip, arka plani kontrol eden, takilmayi anlayan, test eden, toparlayan ve teslim paketi uretebilen bir orkestrator haline getirmek icin hazirlandi.

## Hedef

- Ayni anda kontrolsuz web panel/process acilmasini engelle.
- Calisan ajanlari ve sistem durumunu kullaniciya net goster.
- Takilan ajanlari otomatik algila ve kullaniciya uygulanabilir secenek sun.
- Workflow state bozulursa dosyalardan toparlayabil.
- Her ajan adimini kalite skoru ve otomatik testlerle denetle.
- Snapshot, rol/profil ve teslim paketi ozellikleriyle uygulamayi urun seviyesine tasiyacak araci tamamla.

## Faz 1: Tek Panel ve Process Yonetimi

Amac: Maestro acildiginda arka planda kac panel ve kac ajan calistigi her zaman bilinsin.

Eklenecekler:

- Tek aktif web panel kilidi.
- Aktif panel port bilgisinin UI'da gosterilmesi.
- Zaten calisan panel varsa yeni panel acmak yerine mevcut paneli tarayicida acma.
- Arka plandaki Maestro web panel, Codex, Claude, Gemini/Antigravity sureclerini listeleme.
- "Tumunu kapat" aksiyonu.
- "Sadece aktif isi durdur" aksiyonu.

Teknik yerler:

- `web_panel.py`
  - `MaestroWebPanel.status_payload()` icine process/port bilgisi ekle.
  - Yeni API: `/api/processes`
  - Yeni API: `/api/processes/stop-all`
  - `shutdown_server()` davranisini genislet.
- `web/static/app.js`
  - Sistem durumu karti.
  - Aktif port, server PID, agent PID listesi.
- `web/static/styles.css`
  - Task/process listesi icin kompakt tablo tasarimi.
- `gui.py`
  - Masaustu arayuzde ayni process monitor ozeti.

Kabul kriterleri:

- Ayni proje icin ikinci panel acilmak istendiginde mevcut panel acilir.
- UI aktif portu ve calisan server PID'ini gosterir.
- Aktif Codex/Claude/Gemini surecleri PID ile gorunur.
- "Tumunu kapat" web panel surecini ve cocuk ajanlari temizler.
- Kapatma sonrasi ilgili port dinlemede kalmaz.

## Faz 2: Canli Is Izleyici

Amac: Ajan calisirken kullanici sadece log degil, canli is sagligi gorsun.

Eklenecek alanlar:

- Aktif ajan.
- PID.
- Sure.
- Son log zamani.
- Son dosya degisim zamani.
- Beklenen cikti dosyalari.
- Olusan/eksik cikti listesi.
- CPU kullanimi.
- Muhtemel durum: normal, sessiz, cikti uretti, takilmis olabilir.

Teknik yerler:

- `web_panel.py`
  - `self.proc_started_at`
  - `self.last_output_at`
  - `self.current_stage_writes`
  - `task_monitor_payload()`
  - API: `/api/task-monitor`
- `orkestra.py`
  - Ortak yardimci: `process_info(pid)`
  - Ortak yardimci: `stage_output_status(project_dir, stage)`
- `web/static/app.js`
  - Task Monitor paneli.
  - 2-3 saniyelik polling.

Kabul kriterleri:

- Ajan calisirken PID ve gecen sure gorunur.
- Son log 60 saniyeden eskiyse UI bunu farkli renkle gosterir.
- Beklenen dosya olustuysa "cikti hazir" durumu gorunur.
- Eksik dosyalar net listelenir.

## Faz 3: Akilli Takilma Algilama

Amac: Gemini icin cozulen takilma mantigini tum ajanlara genellestirmek.

Eklenecekler:

- Ajan bazli takilma politikasi.
- Sessizlik esigi.
- Cikti olustu ama process kapanmadi esigi.
- CPU dusuk + log yok + dosya yok algisi.
- UI aksiyonlari:
  - Tamamlandi say
  - Beklemeye devam et
  - Durdur
  - Fallback ajana devret

Onerilen politika:

```json
{
  "codex": { "silent_warn": 300, "silent_stuck": 600, "output_grace": 30 },
  "claude": { "silent_warn": 300, "silent_stuck": 600, "output_grace": 30 },
  "gemini": { "silent_warn": 180, "silent_stuck": 420, "output_grace": 5 }
}
```

Teknik yerler:

- `orkestra.py`
  - `AGENT_STUCK_POLICIES`
  - `stage_can_force_complete(project_dir, stage, agent, elapsed_since_output)`
  - `stuck_reason(...)`
- `web_panel.py`
  - `_run_one()` icinde genel stuck policy.
  - API: `/api/run/force-complete`
  - API: `/api/run/fallback`
- `web/static/app.js`
  - Takilma banner'i.
  - Aksiyon butonlari.

Kabul kriterleri:

- Gemini ciktiyi yazip kapanmazsa otomatik tamamlanir.
- Codex/Claude icin otomatik oldurme daha temkinli olur; once uyari verir.
- Kullanici stuck durumunda panelden karar verebilir.
- Force complete sadece beklenen ciktilar varsa calisir.

## Faz 4: Workflow Devam ve State Kurtarma

Amac: State dosyasi, workflow hash veya panel restart yuzunden kullanici kaldigi yeri kaybetmesin.

Eklenecekler:

- "Dosyalara gore ilerlemeyi toparla" butonu.
- Cikti dosyalari varsa completed state'i yeniden insa etme.
- Workflow hash degisince uyarili gecis.
- Eski workflow ve yeni workflow farkini gosterme.

Teknik yerler:

- `orkestra.py`
  - `infer_completed_from_outputs(project_dir, stages)`
  - `repair_state_from_outputs(project_dir, stages)`
  - `workflow_diff_summary(old_stages, new_stages)`
- `web_panel.py`
  - API: `/api/state/repair`
  - API: `/api/workflow/diff`
  - `diagnostics_payload()` icine state kurtarma onerisi.
- `web/static/app.js`
  - "Ilerlemeyi dosyalardan toparla" butonu.
  - Workflow degisim uyarisi modal'i.

Kabul kriterleri:

- `plan.md`, `tasarim.md`, `rapor.md`, `kontrol.md` varsa ilgili adimlar tamamlandi sayilabilir.
- Workflow hash uyusmazsa UI sebebi soyler.
- Kullanici onaylamadan eski ilerleme sifirlanmaz.

## Faz 5: Net UI Durumlari

Amac: Panelde durumlar log okumadan anlasilsin.

Durumlar:

- Hazir
- Calisiyor
- Checkpoint bekliyor
- Takilmis olabilir
- Durduruldu
- Tamamlandi
- Hata

Teknik yerler:

- `web_panel.py`
  - Status enum benzeri sabitler.
  - `status_payload()` icine `statusKind`, `statusLabel`, `statusSeverity`.
- `web/static/app.js`
  - Status badge ve status banner.
- `web/static/styles.css`
  - Her durum icin renk/stil.
- `gui.py`
  - Desktop status label ayni mantiga yaklastirilir.

Kabul kriterleri:

- Her durum tek bakista ayirt edilir.
- Takilma ve checkpoint ayni gorunmez.
- Hata mesajinda sonraki uygulanabilir aksiyon bulunur.

## Faz 6: Ajan Kalite Skoru

Amac: Ajan adimi gercekten is yapti mi, yoksa sadece konustu mu hizli anlasilsin.

Skor kriterleri:

- Beklenen dosyalar olustu.
- Beklenen dosyalar bos degil.
- Sohbet devir notu eklendi.
- Sonraki ajana net talimat var.
- Test/smoke sonucu var.
- Hata veya eksik cikti yok.

Skor modeli:

- 90-100: Guvenli
- 70-89: Kabul edilebilir
- 40-69: Kontrol gerekli
- 0-39: Basarisiz veya eksik

Teknik yerler:

- `orkestra.py`
  - `score_stage_quality(project_dir, stage, idx, output_text, test_result=None)`
  - `quality_report_path`
- `web_panel.py`
  - `_record_metric()` icine kalite skoru.
  - Status payload icine son kalite ozetleri.
- `web/static/app.js`
  - Ajan kalite karti.

Kabul kriterleri:

- Her tamamlanan adim icin skor uretilir.
- Eksik devir notu veya bos cikti skoru dusurur.
- UI'da son 5 adimin kalite durumu gorunur.

## Faz 7: Otomatik Smoke Test

Amac: Kodlama ve duzeltme adimlarindan sonra proje otomatik kontrol edilsin.

Calisacak kontroller:

- Python:
  - `python -m py_compile`
  - `python -m compileall -q`
  - `pytest`, test klasoru varsa
- Node:
  - `npm test`, script varsa
  - `npm run build`, script varsa
- Genel:
  - README var mi?
  - requirements/package manifest var mi?
  - Calistirma komutu var mi?

Teknik yerler:

- `web_panel.py`
  - Mevcut `run_project_tests()` genisletilecek.
  - `auto_smoke_after_stage(stage)` eklenecek.
- `orkestra.py`
  - Ortak test raporu modeli.
- `project/test_raporu.json`
  - Standart format.
- `web/static/app.js`
  - Test raporu karti.

Kabul kriterleri:

- Kodlama veya duzeltme adimi sonrasi smoke test otomatik calisir.
- Sonuc `test_raporu.json` icine yazilir.
- UI basarili/basarisiz testleri okunur sekilde gosterir.

## Faz 8: Snapshot Karsilastirma Ekrani

Amac: Her ajan adiminda ne degisti net gorulsun ve geri donus kolay olsun.

Eklenecekler:

- Snapshot listesi.
- Snapshot detayinda dosya degisimleri.
- Diff goruntuleme.
- Tumuyle geri don.
- Tek dosyayi geri al.

Teknik yerler:

- `orkestra.py`
  - Mevcut snapshot fonksiyonlari genisletilecek.
  - `snapshot_file_diff(snapshot_id, file)`
  - `restore_single_snapshot_file(snapshot_id, file)`
- `web_panel.py`
  - API: `/api/snapshots`
  - API: `/api/snapshots/diff`
  - API: `/api/snapshots/restore-file`
- `web/static/app.js`
  - Snapshot tablosu ve diff viewer.

Kabul kriterleri:

- Kullanici her adimin degistirdigi dosyalari gorebilir.
- Diff okunur sekilde gosterilir.
- Tek dosya geri alma calisir.
- Geri alma oncesi onay istenir.

## Faz 9: Ajan Rolleri ve Prompt Profilleri

Amac: Kullanici ajan secmek yerine rol secsin; Maestro dogru ajan ve prompt'u onersin.

Roller:

- Planlayici
- UI/UX denetci
- Kod yazici
- Testci
- Refactor uzmani
- Paketleme uzmani
- Guvenlik/kontrol uzmani

Teknik yerler:

- `orkestra.py`
  - Rol modeli.
  - `agent_for_role(role, project_type)`
  - `prompt_profile_for_role(role)`
- `gui.py`
  - Mevcut prompt profile yapisi role baglanir.
- `web_panel.py`
  - Workflow template olustururken rol secimi.
- `web/static/app.js`
  - Role tabanli workflow editor.

Kabul kriterleri:

- Kullanici workflow adiminda rol secebilir.
- Rol secilince ajan ve prompt otomatik dolar.
- Isterse kullanici ajan/prompt'u elle override edebilir.

## Faz 10: Teslim Paketi Butonu

Amac: Is bitince tek tusla yuklemeye veya paylasmaya hazir paket uretilsin.

Paketleme adimlari:

- `__pycache__`, `.pytest_cache`, gecici log/cache temizligi.
- README kontrolu.
- requirements/package manifest kontrolu.
- Test raporu kontrolu.
- Zip olusturma.
- Paket manifesti.
- "Yuklemeye hazir" raporu.

Teknik yerler:

- `web_panel.py`
  - API: `/api/package/create`
  - `create_delivery_package(target_dir)`
- `orkestra.py`
  - Paket yardimcilari ortak hale getirilebilir.
- `web/static/app.js`
  - Teslim Paketi butonu.
  - Paket gecmisi.

Kabul kriterleri:

- Tek tusla zip uretilir.
- Zip icinde gereksiz cache dosyalari olmaz.
- Paket raporu hangi testlerin gectigini soyler.
- UI paket yolunu ve boyutunu gosterir.

## Onerilen Uygulama Sirasi

1. Faz 1: Tek Panel ve Process Yonetimi
2. Faz 2: Canli Is Izleyici
3. Faz 3: Akilli Takilma Algilama
4. Faz 4: Workflow Devam ve State Kurtarma
5. Faz 5: Net UI Durumlari
6. Faz 7: Otomatik Smoke Test
7. Faz 6: Ajan Kalite Skoru
8. Faz 8: Snapshot Karsilastirma
9. Faz 9: Ajan Rolleri
10. Faz 10: Teslim Paketi

Bu siralama bilincli: once process ve state guvenligi cozulecek, sonra kalite ve urunlesme ozellikleri eklenecek.

## Minimum MVP Kapsami

Ilk teslim icin su paket yeterli:

- Tek panel kilidi.
- Process listesi.
- Aktif agent PID/sure/son log zamani.
- Takilma uyarisi.
- Dosyalardan state toparlama.
- Net status badge.
- Kodlama sonrasi otomatik smoke test.

Bu MVP tamamlaninca Maestro zaten gundelik kullanimda cok daha guvenilir olur.

## Riskler

- Windows process agaclari her zaman tutarli raporlanmayabilir; `taskkill /T /F` yedek yol olarak kalmali.
- Codex/Claude/Gemini CLI ciktisi surume gore degisebilir; takilma algisi tek log kalibina baglanmamali.
- Force complete sadece beklenen ciktilar varsa aktif olmali; aksi halde yarim is tamamlandi sanilabilir.
- Snapshot geri alma dikkatli yapilmali; kullanici onayi olmadan dosya restore edilmemeli.
- Paketleme cache temizligi proje disina cikmamali; path guvenligi korunmali.

## Basari Olcutu

Bu plan bittiginde kullanici sunlari yapabilmeli:

- Maestro'yu acinca arka planda ne calistigini tek ekranda gorebilmeli.
- Ajan takilinca sebebini anlayip panelden mudahale edebilmeli.
- Workflow state bozulsa bile dosyalardan toparlayabilmeli.
- Her adimin kalitesini ve test sonucunu gorebilmeli.
- Degisiklikleri snapshot diff ile denetleyebilmeli.
- Is bitince tek tusla temiz teslim paketi alabilmeli.
