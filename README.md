# createclip

**Kick VOD ya da biten bir YouTube yayınının linkini yapıştır → en iyi anlar önizleme olarak gelsin, beğendiklerini seç, dikey (9:16) Türkçe kelime kelime altyazılı videoya çevrilsin.**
Her şey yerelde çalışır (Apple Silicon Mac); video ve ses buluta gitmez (isteğe bağlı Gemini başlık/puan özelliği hariç, bkz. "Otomatik mod").

> *Paste a Kick VOD or finished YouTube live-stream link → finds the best moments from chat activity, cuts clips, burns word-by-word Turkish captions
> (local Whisper) and can reframe to 9:16. Local web editor + CLI.*

## Özellikler
- **Tek ekran, üç adım:** link yapıştır → 20 önizlemeyi izleyip beğendiklerine dokun → **Seçilenleri üret**. Ayar sormaz: varsayılan dikey 1080×1920, 30 fps, oyun+yüz yerleşimi (yüz bulunamazsa bulanık arka plan), altyazı açık.
- **An bulma:** sohbet yoğunluğu (eşsiz sohbetçi sayısı, emote'lara düşük ağırlık, yayının ortalamasına göre z-skoru) ya da ses seviyesi.
- **Altyazı:** `mlx-whisper large-v3` ile kelime zamanlı Türkçe altyazı; aktif kelime vurgulu, 3 font, renk/kontur/boyut/konum ayarı, küfür maskesi (klibe tıklayınca açılan düzenleyicide).
- **9:16:** oyun+yüz (otomatik), bulanık arka plan, tek pencere, iki pencere; pencereleri kareye tıklayarak elle de seçebilirsin.
- **Düzenlenebilir klipler:** kesimi ±1 sn ayarla, metni düzelt (zamanlama korunur), senkron kaydırıcısı, yorum sesi, klip ekle/sil.
- **Yavaş / Hızlı anahtarı:** *Yavaş* üretirken bilgisayarı başka işe kullanabilirsin (varsayılan), *Hızlı* tam güç.
- `.srt` dışa aktarma; kanal izleme + kuyruk, Gemini ile otomatik başlık (aşağıda).

| Altyazı fontları (önizleme) | 9:16 (eski ekran görüntüsü) |
|---|---|
| ![Fontlar](docs/img/fonts.png) | ![Dikey](docs/img/portrait.png) |

## YouTube desteği
Biten YouTube canlı yayınları (ve sohbet tekrarı açık videolar) Kick ile aynı akıştan geçer: `createclip run "https://www.youtube.com/watch?v=…"`.
Sohbet, `yt-dlp`'nin `live_chat` (chat replay) çıktısından tek seferde alınır (112 dk'lık bir yayında ölçüm: 4704 mesaj, 91 sn);
Kick'teki istek sınırı yoktur, hızlı/tam ayrımı da yoktur. Sınırlar: hâlâ süren canlı yayın işlenmez (bitince dene); sohbet tekrarı
kapalı videolarda (YouTube sayfasında "Live chat replay is not available" yazar; yayıncı kapatmış ya da kaldırılmış olabilir) ses
seviyesi yedeği gerekir. Bu yedek tüm videoyu indirdiği için önce **onay istenir** (arayüzde düğme, komut satırında soru ya da
`--audio-fallback`); tahmini boyut ~1,7 MB/dk (yalnızca tahmin). Yedek YouTube'da uçtan uca denenmedi. Bunun yerine `--at` ile elle zaman verilebilir.

## Gereksinimler
`ffmpeg`, `yt-dlp`, `curl` (`brew install ffmpeg yt-dlp`), Python 3.10+. İlk altyazıda
`mlx-community/whisper-large-v3-mlx` (~3 GB) indirilir; ayrı hizalama modeli gerekmez.

## Kurulum
```bash
git clone https://github.com/emirhan-coban/createclip.git
cd createclip && python3 -m venv .venv && ./.venv/bin/pip install -e ".[dev]"
```

## Kullanım
Web arayüzü (önerilen):
```bash
./.venv/bin/createclip serve          # http://127.0.0.1:8765
```
Ana ekranda linki yapıştır ve **Başlat**; önizlemeler gelince **Seç**, sonra **Seçilenleri üret**. Biten klipte başlığı düzenleyip **Kaydet**
dersen klip `ready/` klasörüne hazır paket olarak konur. **Gelişmiş** sekmesi: projeler, kanallar/kuyruk, Gemini anahtarı, otomatik izleme, disk temizliği.

Komut satırı (`-n` = baştan sona üretilecek klip sayısı; önizleme/seç akışı arayüzde):
```bash
./.venv/bin/createclip run "<kick-linki>" -n 5                        # 5 altyazılı klip
./.venv/bin/createclip run "<link>" --start 10:00 -n 5                # yayının ilk 10 dk'sını (kalabalık açılış) atla
./.venv/bin/createclip run "<link>" --layout stack --mask-profanity   # 9:16 iki pencere, küfür yıldızlı
./.venv/bin/createclip run "<link>" --at 1:44:50 --at 0:27:50-0:28:40 # elle zamanlar (sohbet gerekmez)
./.venv/bin/createclip run "<link>" --source audio                    # sohbet yerine ses seviyesi
./.venv/bin/createclip run "<link>" --full-chat --size 0.06 --ypos 0.7 --chunk 2 --sync -0.1 --max-height 1080
```
Çıktı `output/<kanal>-<vod>/` altında: `captioned/` (bitmiş dikey altyazılı klip), `clips/` (kırpılmış ara dosya), `words/` (`.json`, `.srt`),
`raw/` (kenar payı olan ham kesit; **taslak önizlemeler bundan oynatılır**), `chat.jsonl` (önbellek), `manifest.json`.
Altyazısız/yerleşimsiz ara sürümler artık varsayılan olarak tutulmaz (`--plain` ile istenir; fazladan bir kodlama maliyeti vardır).
Aynı yayını tekrar çalıştırırsan daha önce kesilmiş anlar atlanır (kaldığın yerden devam).

## Sohbet indirme süreleri (ölçüldü)
Kick'in sohbet API'si bir istekte yalnızca ~5 sn'lik pencere verir ve sürekli yaklaşık **1,5 istek/sn**'ye izin verir
(150 sn'lik ölçüm: 1,2 ve 1,5/sn'de hiç `429` yok; 1,8/sn'de 274 istekten 21'i reddedildi). Yani indirmeyi hızlandırmanın yolu
daha hızlı istemek değil, **daha az istemek**. Bu yüzden iki mod var:

| Mod | 2,5 saatlik yayın | 6 saatlik yayın (59 188 mesaj) | Sonuç |
|---|---|---|---|
| **Akıllı** (varsayılan) | ≈ 8 dk (tahmin) | **23,6 dk** (1781 istek) | en iyi 5 an aynı, ilk 10'un 9'u, ilk 30'un 23'ü |
| **Tam** | ≈ 20 dk | **≈ 57 dk** | eksiksiz |
| Ses seviyesi (`--source audio`) | internet hızına bağlı (ölçülmedi) | — | sohbet yok |

Akıllı mod: önce her 8. pencereyi örnekler, sonra en güçlü adayların (en çok 60) ±45 sn çevresini ayrıntılı indirir; anlar yoğun
veriden seçilir. Parametreler gerçek 6 saatlik veride tarandı (istekleri ~%33'e indirirken ilk 10 korundu). Yarıda kalan indirme
(kapanma, uyku, kopma) **kaldığı yerden devam eder**: her istek `chat.log.jsonl` dosyasına eklenir; akıllı ve tam mod aynı
önbelleği paylaşır. Not: 2,5 saatlik değer o yayında ölçülen istek sayısından değil, ölçeklemeden hesaplandı.

## Nasıl çalışır
```mermaid
flowchart LR
  A[Kick VOD linki] --> B[Sohbet indir<br/>veya ses analizi]
  B --> C[Pikler: z-skoru<br/>30 aday]
  C --> D[20 an: kodlamasız<br/>paralel önizleme indirme]
  D --> E[Sen seç]
  E --> F[Whisper large-v3<br/>kelime zamanları]
  F --> G[Tek ffmpeg geçişi:<br/>9:16 + altyazı, 30 fps]
  G --> I[Hazır klip / düzenleyici]
```
1. **Sohbet:** Kick'in resmi olmayan API'sinden `curl` ile, hız sınırının altında (≈1,5 istek/sn) indirilir ve istek istek diske yazılır. Bir istek ~5 sn'lik pencere ve en çok ~25
   mesaj döndürür; `cursor` alanı mesaj atlattığı için kullanılmaz. Alınamazsa ses seviyesine bakılır: YouTube'da yalnız ses akışı (112 dk için 38 MB, 13 sn), Kick'te ses-yalnız biçim olmadığından en düşük video (≈1,7 MB/dk); ses seviyesi ölçülür.
2. **Pik:** 10 sn dilimlerde skor, ilk 2 dk / son 1 dk atlanır, pikler ≥90 sn arayla, pencere pikten 20 sn önce başlar (25-60 sn).
3. **Önizleme:** yalnız ilgili aralık (±10 sn pay) **yeniden kodlanmadan** indirilir (birkaç aralık aynı anda); kesim noktaları `silencedetect` ile en yakın konuşma arasına çekilir.
   Taslak seçilince tam kare kırpılır.
4. **Altyazı:** ipucu (prompt) kullanılmaz: ölçümde uzun ipucu konuşmanın büyük kısmını atlatıyordu (69 yerine 27 kelime).
   İsteğe bağlı kısa `--vocab "Berk, Derbeder"`. Altyazı Pillow ile çizilip (yalnız altyazı bandı kadar görsel) ffmpeg `overlay` ile bindirilir (libass gerekmez).
5. **9:16:** yerleşim ve altyazı **tek ffmpeg geçişinde** basılır; oyun+yüz (OpenCV ile yüz bulma), bulanık arka plan, tek veya iki pencere; pencereler düzenleyicide elle ayarlanabilir.

### Altyazı senkronu
Kayma kaynağı bulundu ve düzeltildi: kelime zamanları üst üste bindiğinde bindirme zaman çizelgesi gecikiyor ve hata klip boyunca
birikiyordu. Artık altyazı durumları sıralı ve çakışmasız üretilir (`captions.build_states`, birim testli). Whisper kelime
zamanları 5 klipte ses başlangıçlarıyla karşılaştırıldı: medyan sapma ±0,09 sn. Kalan ince kayma için senkron kaydırıcısı var
(varsayılan −0,08 sn).

## Geliştirme
```bash
./.venv/bin/python -m pytest -q       # 84 test
```
Dosyalar: `kick.py` (VOD + sohbet), `peaks.py`, `audio_peaks.py`, `clipper.py`, `transcribe.py`, `captions.py`, `layout.py`,
`youtube.py`, `sources.py` (YouTube + platform seçimi), `watch.py` (izleyici + kuyruk), `review.py` (klip listesi + hazır paket), `ytdlp.py`, `log.py`, `pipeline.py` (önizleme/üretim hattı + düzenleme), `render.py` + `encode.py` (tek geçişli render, kodlayıcı ayarı),
`overlay.py`, `compile.py`, `cleanup.py`, `dupes.py`, `moments.py` + `gemini.py` + `titles.py` + `autometa.py` (Gemini/Claude başlık ve puan), `settings.py`, `autostart.py`, `notify.py`, `doctor.py`,
`web/` (FastAPI + tek sayfa arayüz), `syncfix.py` (senkron ölçüm aracı), `scripts/bench.py` (kodlama ölçümü).

## Klip kanalı akışı (izleyici, kuyruk, onay kutusu)
```bash
./.venv/bin/createclip channels add kick.com/kanal -n 5 --layout blur --max-height 1080   # ya da youtube.com/@kanal
./.venv/bin/createclip watch --every 6          # tara + işle + bekle (gece açık bırak); --once: bir kez
./.venv/bin/createclip queue                    # durum; queue retry|confirm|rm <id>, queue clear
./.venv/bin/createclip serve                    # http://127.0.0.1:8765  → Klipler ekranı
```
- **İzleyici:** kanalın biten yayınlarını `yt-dlp` ile listeler (Kick: `kick.com/<kanal>/videos`, YouTube: `/@kanal/streams`),
  canlı/süresi 0 olanları ve `--min-minutes`'tan kısaları atlar, **yeni olanları** kuyruğa koyar. Kanalı ilk eklediğinde yalnızca en yeni
  `--backfill` kadar yayın girer (tüm geçmiş değil). En eski önce işlenir: Kick resmi yardım sayfasına göre yayınları 7 gün (doğrulanmış
  kanalda 30 gün) saklıyor, bu yüzden tarama aralığını bundan kısa tut (üçüncü taraf kaynaklar süreyi farklı veriyor).
- **Kuyruk** (`output/queue.json`): durdurup başlatınca kaldığı yerden devam eder; hata 3 kez denenir; sohbet yoksa iş **"onay bekliyor"**
  olur (tüm sesi indirmeden önce sorar), `queue confirm <id>` ya da arayüzdeki düğme.
- **Hazır klipler** (ana ekranın altı): biten klipler; başlığı düzenle, **Kaydet** (onay) ya da **Sil**. Başlık/açıklama/etiket
  önerisi Gemini (ya da Claude) anahtarı varsa model üretir, yoksa kural tabanlıdır (ilk cümle, kaynak bağlantısı + zaman damgası, sık kelimeler). Kuyruktan gelen
  yayınlarda en iyi 5 klip üretilmiş, kalan 15 taslak olarak önizleme bölümünde bekler.
  Kaydedilen klip **hazır pakete** aktarılır: `ready/<tarih>/<proje>_<klip>/` içinde `video.mp4`, `baslik.txt`, `aciklama.txt`,
  `etiketler.txt`, `kapak.jpg`; platform sınırı/dikey değil uyarısı verir. **Otomatik yükleme yoktur** (YouTube'da denetimsiz API
  projelerinin yüklemeleri özel kalır, TikTok'ta denetimsiz istemci yalnızca özel hesaba paylaşır; bunlar üçüncü taraf kaynaklardan, denenmedi).
- **Kanal profili:** bir klibin altyazı stilini ve 9:16 yerleşimini editörde bir kez ayarla, klip kartındaki **Kanal profili yap** ile
  o yayıncının sonraki tüm klipleri bu ayarla çıksın.

> **Yeniden kullanım uyarısı.** YouTube, Ekim 2026'da Shorts önerilerini değiştirip başkasının klibini katkısız yeniden yükleyen kanalların
> erişimini düşüreceğini duyurdu (ve "yalnızca sesli anlatım, küçük kurgu, şablonlu toplu düzenleme" özgün sayılmıyor). Yeniden kullanım
> politikası izin alınsa bile geçerli ve kanal düzeyinde değerlendiriliyor. Bu araç kesim/altyazı/yerleşim otomasyonudur; kanalın
> özgün katkısını (yorum, bağlam, derleme) senin eklemen gerekir. Ayrıntı ve güncel kurallar için YouTube Yardım'ı oku; bu hukuki tavsiye değildir.

## Özgün katkı araçları, ses ve temizlik

YouTube'un Ekim 2026 Shorts güncellemesi, başkasının klibini katkısız yeniden yükleyen kanalların erişimini düşürüyor
(kaynak: üçüncü taraf özetleri; resmi sayfayı yayından önce kontrol et). Bu yüzden klibe kendi katkını eklemek için araçlar var.
Hiçbiri "politikaya uyar" garantisi değildir.

- **Sohbet tepkisi** (`--reactions` ya da editörde Ekler): o anda yayına yazılan gerçek mesajlar videoda görünür
  (komutlar, çok uzun mesajlar, tekrarlar ve çok sık mesajlar elenir).
- **Başlık kartı**: ilk 3 saniyede klibin ne hakkında olduğunu söyleyen kart.
- **Yorum sesi**: editörde klip oynarken mikrofona konuş (kulaklık tak); kayıt klibe karıştırılır, sen konuşurken orijinal ses kısılır.
- **Derleme**: `createclip compile -n 5` (arayüzde düğmesi yok). Açılış kartı, geri sayım kartları,
  klipler; kaynak yayın ve zaman damgası listesi yanında `.txt` olarak çıkar (`ready/derleme/`).
- **Yüz takibi** (`--layout face`): OpenCV (Haar) ile yayıncının yüz kamerasını bulur; üstte oyun, altta yakın yüz.
  Bulunamazsa bulanık arka plana döner. Ölçüm: tek bir yayıncının 12 klibinin 12'sinde bulundu (0,87-0,89 / 0,74-0,77 konumunda),
  klip başına ~1,5 sn. Başka yayıncılarda denenmedi; yan profil, kapalı yüz ve değişen kamera yerleşimi sorun çıkarabilir.
  Kurulum: `pip install 'opencv-python-headless<5'` (5.x sürümünde yüz bulucu yok).
- **Ses seviyesi**: yeni kesimler -16 LUFS'a yaklaştırılır (tek geçişli loudnorm). Ölçüm: 5 klipte seviye farkı 3,9 LU'dan 2,0 LU'ya indi.
- **Ölü sessizlik**: klip uzun bir sessizlikle başlıyor/bitiyorsa baş/son kırpılır (ses ve görüntü birlikte).
- **Benzer klipler**: aynı anın iki kez bulunması ya da farklı projelerde benzer konuşma "benzer klip" etiketiyle işaretlenir.
- **Başlık önerisi (isteğe bağlı)**: Gemini anahtarı yoksa `ANTHROPIC_API_KEY` ayarlıysa üretilen her klibin konuşma metni Anthropic'e gönderilip
  başlık/açıklama/etiket yazılır (otomatik, düğme yok). Anahtar yokken yerel, basit öneri kullanılır. Gerçek API ile denenmedi (yalnız sahte yanıtla test edildi).
- **İptal**: çalışan iş, alttaki çubuktan iptal edilir; çalışan ffmpeg/yt-dlp süreci öldürülür (konuşma çözme sürerken bir sonraki adımda durur).
- **Bildirim**: izleyici ve web işleri bitince macOS bildirimi çıkar.
- **Temizlik**: `createclip cleanup` neyin silineceğini gösterir, `--yes` ile siler. Yalnız yeniden üretilebilir dosyalar
  (ham kesit, kare, ses indirmesi, reddedilen klipler); klipler ve sohbet kaydı kalır. `createclip keep <proje>` ya da arayüzde "Koru" ile
  bir proje temizlik ve silmeden tamamen korunur; son N günde değişen projelere dokunulmaz.

Yapılmayanlar: otomatik YouTube/TikTok/Instagram yükleme (API'ler denetim gerektirir, "hazır paket" kullan) ve ek an sinyalleri
(kahkaha/anahtar kelime): etiketli veri olmadan iyileşme ölçülemediği için eklenmedi.

## Hız: önizle → seç → üret (ölçüldü)

Eski akış her klibi sırayla baştan sona işliyordu (günlükten klip başına ≈ 3 dk: indirme 43 sn, yerleşim 63 sn, altyazı 40 sn, Whisper 23 sn,
kırpma 9 sn; 20 klip ≈ 1 saat) ve aynı dakikayı 4 kez kodluyordu, her şey 60 fps / 1080×1920'ydi. Şimdi:

1. **Önizleme:** en iyi 20 an aynı anda (6 paralel) **kodlamasız** indirilir; ana ekranda oynatılır. Seçilmeyenler hiç işlenmez.
2. **Üret:** yalnız seçilenler: kırpma → Whisper (tek işçi) → **tek geçişte** 9:16 yerleşim + altyazı (30 fps, `veryfast`, altyazı yalnız
   altyazı bandı kadar bir görselle); birkaç klip aynı anda ilerler.
3. Kuyruk/izleyici (gece): en iyi 5 otomatik üretilir, 15 taslak sabaha önizleme olarak bekler.

| Ölçüm (aynı 30 sn klip, yoğun makinede) | Süre |
|---|---|
| Eski zincir: trim + yerleşim + altyazı (60 fps, medium) | 282 sn |
| Yeni: trim + tek geçiş (libx264 veryfast, 30 fps) | 37 sn |
| Yeni, Apple donanım kodlayıcısı (`CREATECLIP_ENCODER=videotoolbox`) | 22 sn (dosya daha küçük; kalite göz kontrolüyle doğrulanmadı) |

İndirme (YouTube, 40-65 sn'lik aralıklar): `--force-keyframes-at-cuts` kesiti yeniden kodlar; kaldırıldı. Kopya kesim zamanda hizalı
çıktı (ses çapraz ilişkisiyle kayma 0,0005 sn) ve 4 paralel indirme 238 sn yerine 65 sn sürdü; 8 önizleme ≈ 117 sn (yoğun makine).
**Uçtan uca (gerçek YouTube yayını, 8 klip, hepsi üretildi):** 8 önizleme 117 sn, 8 bitmiş dikey altyazılı klip toplam **744 sn**
(≈ 93 sn/klip; eski akışta günlükteki 3 dk/klip ile ≈ 24 dk). Çıktı doğrulandı: 1080×1920, 30 fps, süre 45,0 sn, ses var, altyazı bandı ve oyun+yüz yerleşimi
yerinde. Bu çalışma sırasında makinenin yük ortalaması 80-150'ydi (başka uygulamalar + 3 eşzamanlı kodlama), Whisper klip başına ~80 sn sürdü
(boşta 15-23 sn); en yavaş aşama tek Whisper işçisi olduğundan boş makinede çok daha hızlı beklenir ama bu **ölçülmedi**.
Asıl kazanç seçmeli akışta: 5 klip seçilince 8 yerine 5 klip üretilir.
**Yavaş / Hızlı anahtarı** (ana ekranda, ayar anında geçerli): *Yavaş* (varsayılan) ağır araçları düşük öncelikte (`nice 10`), kodlamayı 4 çekirdekle,
2 klip + 4 indirmeyle çalıştırır, bilgisayar başka işe kullanılabilir; *Hızlı* tam güç (3 klip, 6 indirme, tüm çekirdekler). `CREATECLIP_FAST=1` varsayılanı hızlı yapar. Aradaki süre farkı ölçülmedi.
Rakamlar bu makinede, başka uygulamaların yükü altında (yük ortalaması 30-80) alındı; boştaki makinede mutlak süreler daha kısa olur.

**Whisper turbo (`large-v3-turbo`) denendi, kullanılmıyor:** 6 gerçek Türkçe klipte 3-5 kat hızlıydı ama 2 klipte konuşmanın büyük kısmını
atladı (large-v3'ün bulduğu kelimelerin %37 ve %44'ü; konuşma süresi 67 sn yerine 39 sn). Varsayılan large-v3 kaldı;
`CREATECLIP_WHISPER_MODEL` ile değiştirilebilir. `scripts/bench.py` kodlama ölçümünü tekrarlar.

## Otomatik mod (Gemini ile)

1. **Gelişmiş** sekmesinde: **Kanallar** bölümünden kanalı ekle, **Ayarlar**'dan "Otomatik mod"u aç ve istersen ücretsiz [Gemini anahtarını](https://aistudio.google.com/apikey) kaydet.
2. Uygulama açıkken kanalları her N saatte bir tarar (varsayılan 3; Kick VOD'u 7 günde silinebilir), yeni yayınları işler, bitince bildirim verir.
3. Gemini anahtarı varsa her klip **başlık, açıklama, etiket** ve **AI puanı (1-10)** ile gelir; sıralama `skor × (0.5 + AI/10)`. Anahtar yoksa eski davranış (yerel basit öneri, yalnız sohbet/ses skoru).
4. **Kaydet** = hemen `ready/<tarih>/…` hazır paketi (Shorts).
5. Bilgisayar açılınca kendiliğinden başlasın: `createclip autostart on` (kapatmak: `off`).

Notlar: Yükleme otomasyonu yoktur (kasıtlı). Anahtar `settings.json`'da (0600) saklanır. Ücretsiz katmanda gönderilen klip metni/sesi Google'ın ürün geliştirmesinde kullanılabilir. AI puanının sıralamayı ne kadar iyileştirdiği **ölçülmedi**; Gemini limit/model adı değişebilir (`CREATECLIP_GEMINI_MODEL` ile model seçilir, varsayılan `gemini-flash-latest`). Gemini gerçek anahtarla henüz denenmedi; testler sahte HTTP ile.

## Günlük ve hata ayıklama
Her şey `output/createclip.log` dosyasına yazılır (dönen dosya): çalışan her dış komut, çıkış kodu, süre ve hata çıktısının sonu.
Web'de ilerleme çubuğunun altındaki **Günlük** bölümü işin satırlarını canlı gösterir; 2 dk ilerleme olmazsa "takılmış olabilir"
uyarısı çıkar. Komut satırı: `createclip run … -v` (günlüğü ekrana da yazar), `createclip logs -n 100`.

Bilinen takılmalar ve çözümleri (bu makinede gerçekten yaşandı): (1) `yt-dlp`'nin varsayılan bağlantısı "Downloading webpage"de
sonsuza dek bekleyebilir; kod `--impersonate chrome` kullanır (`createclip/ytdlp.py`), 3 dk zaman aşımı vardır.
(2) Whisper modeli diskte olsa da Hugging Face'e güncelleme sorusu IPv6'da takılabilir; önbellekteki model çevrimdışı yüklenir.

## Görüntü kalitesi
YouTube'da ≤720p tek parça (ses+video birlikte) yalnızca 360p'dir; eski seçici bu yüzden 360p indiriyordu (ölçüldü: biçim 18, 640×360).
Artık H.264 ayrı video+ses akışları birleştirilir (denendi: 720p60 → 1280×720 60 fps h264+aac, görüntü/ses süreleri eşit; Kick'te
720p60/1080p60). Kaynak 720p iken dikey çıktı 1080×1920'ye büyütülür (ek ayrıntı yok, platform standardı); 1080p kaynak için `--max-height 1080`.
Klip iki kez kodlanır: kesim (crf 18, hızlı ön ayar, 30 fps) ve tek geçişli son render (crf 21 `veryfast`); bunun görsel etkisi ölçülmedi.

## Sınırlar
- Kick sohbet API'si resmi değil; değişirse kırılabilir. VOD'lar Kick'te süreli saklanır.
- Altyazılar yaklaşık: özel isimler yanlış çıkabilir; web'de düzeltip yeniden bas. Kesimi değiştirirsen konuşma yeniden çözülür,
  metin düzeltmelerin sıfırlanır.
- Ses yedeği yalnızca ölçüm adımı gerçek dosyada denendi; tam VOD ile uçtan uca çalıştırılmadı.
- Kick'in CDN'i zaman zaman takılır: indirme 4 dk zaman aşımı ve 3 deneme ile korunur.
- Küfür filtresi yalnızca yaygın kök listesine bakar. Çalışan iş alttaki çubuktan iptal edilir.
- Yalnızca kendi içeriğin ya da izin aldığın yayınlar için kullan.

## Lisans
MIT (bkz. `LICENSE`). Paketlenen fontlar SIL OFL 1.1 (`createclip/fonts/README.md`).
