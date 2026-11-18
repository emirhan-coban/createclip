# createclip

**Kick VOD ya da biten bir YouTube yayınının linkini yapıştır → en iyi anları bulsun, klipleri kessin, Türkçe kelime kelime altyazı bassın, istersen 9:16'ya çevirsin.**
Her klip web arayüzünde düzenlenebilir. Her şey yerelde çalışır (Apple Silicon Mac), buluta video veya ses yüklenmez.

> *Paste a Kick VOD or finished YouTube live-stream link → finds the best moments from chat activity, cuts clips, burns word-by-word Turkish captions
> (local Whisper) and can reframe to 9:16. Local web editor + CLI.*

![Yeni proje formu](docs/img/new-project.png)

## Özellikler
- **An bulma:** sohbet yoğunluğu (eşsiz sohbetçi sayısı, emote'lara düşük ağırlık, yayının ortalamasına göre z-skoru) ya da ses seviyesi.
- **Altyazı:** `mlx-whisper large-v3` ile kelime zamanlı Türkçe altyazı; aktif kelime vurgulu, 3 font, renk/kontur/boyut/konum ayarı, küfür maskesi.
- **9:16:** bulanık arka plan, tek pencere, iki pencere (üst/alt); pencereleri kareye tıklayarak elle seçersin.
- **Üretmeden önce ayar + canlı önizleme**, ön ayar kaydetme (ör. "Shorts").
- **Düzenlenebilir klipler:** kesimi ±1 sn ayarla, metni düzelt (zamanlama korunur), senkron kaydırıcısı, klip ekle/sil, skora göre sıralama.
- Altyazılı **ve** altyazısız sürüm, `.srt` dışa aktarma.

| Altyazı fontları (önizleme) | 9:16 |
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
Komut satırı:
```bash
./.venv/bin/createclip run "<kick-linki>" -n 5                        # altyazılı + altyazısız
./.venv/bin/createclip run "<link>" --layout stack --mask-profanity   # 9:16 iki pencere, küfür yıldızlı
./.venv/bin/createclip run "<link>" --at 1:44:50 --at 0:27:50-0:28:40 # elle zamanlar (sohbet gerekmez)
./.venv/bin/createclip run "<link>" --source audio                    # sohbet yerine ses seviyesi
./.venv/bin/createclip run "<link>" --full-chat --size 0.06 --ypos 0.7 --chunk 2 --sync -0.1 --max-height 1080
```
Çıktı `output/<kanal>-<vod>/` altında: `clips/` (altyazısız), `captioned/` (altyazılı), `words/` (`.json`, `.srt`),
`raw/` (kenar payı olan ham kesit), `chat.jsonl` (önbellek), `manifest.json`.

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
  C --> D[yt-dlp ile sadece<br/>ilgili aralık]
  D --> E[Kesimi konuşma<br/>arasına hizala]
  E --> F[Whisper large-v3<br/>kelime zamanları]
  F --> G[Pillow + ffmpeg<br/>altyazı bindirme]
  G --> H[Opsiyonel 9:16]
  H --> I[Web editörü]
```
1. **Sohbet:** Kick'in resmi olmayan API'sinden `curl` ile, hız sınırının altında (≈1,5 istek/sn) indirilir ve istek istek diske yazılır. Bir istek ~5 sn'lik pencere ve en çok ~25
   mesaj döndürür; `cursor` alanı mesaj atlattığı için kullanılmaz. Alınamazsa en düşük kaliteli VOD (~250 MB) indirilip ses seviyesi ölçülür.
2. **Pik:** 10 sn dilimlerde skor, ilk 2 dk / son 1 dk atlanır, pikler ≥90 sn arayla, pencere pikten 20 sn önce başlar (25-60 sn).
3. **Kesim:** yalnız ilgili aralık (±10 sn pay) indirilir; kesim noktaları `silencedetect` ile en yakın konuşma arasına çekilir.
4. **Altyazı:** ipucu (prompt) kullanılmaz: ölçümde uzun ipucu konuşmanın büyük kısmını atlatıyordu (69 yerine 27 kelime).
   İsteğe bağlı kısa `--vocab "Berk, Derbeder"`. Altyazı Pillow ile çizilip ffmpeg `overlay` ile bindirilir (libass gerekmez).
5. **9:16:** ffmpeg ile pencere kırpma / bulanık arka plan; yüz takibi yok, her yayıncının yerleşimi farklı olduğu için pencereler elle ayarlanır.

### Altyazı senkronu
Kayma kaynağı bulundu ve düzeltildi: kelime zamanları üst üste bindiğinde bindirme zaman çizelgesi gecikiyor ve hata klip boyunca
birikiyordu. Artık altyazı durumları sıralı ve çakışmasız üretilir (`captions.build_states`, birim testli). Whisper kelime
zamanları 5 klipte ses başlangıçlarıyla karşılaştırıldı: medyan sapma ±0,09 sn. Kalan ince kayma için senkron kaydırıcısı var
(varsayılan −0,08 sn).

## Geliştirme
```bash
./.venv/bin/python -m pytest -q       # 30 test
```
Dosyalar: `kick.py` (VOD + sohbet), `peaks.py`, `audio_peaks.py`, `clipper.py`, `transcribe.py`, `captions.py`, `layout.py`,
`youtube.py`, `sources.py` (YouTube + platform seçimi), `ytdlp.py`, `log.py`, `pipeline.py` (iş akışı + düzenleme), `web/` (FastAPI + tek sayfa arayüz), `syncfix.py` (senkron ölçüm aracı).

## Günlük ve hata ayıklama
Her şey `output/createclip.log` dosyasına yazılır (dönen dosya): çalışan her dış komut, çıkış kodu, süre ve hata çıktısının sonu.
Web'de ilerleme çubuğunun altındaki **Günlük** bölümü işin satırlarını canlı gösterir; 2 dk ilerleme olmazsa "takılmış olabilir"
uyarısı çıkar. Komut satırı: `createclip run … -v` (günlüğü ekrana da yazar), `createclip logs -n 100`.

Bilinen takılmalar ve çözümleri (bu makinede gerçekten yaşandı): (1) `yt-dlp`'nin varsayılan bağlantısı "Downloading webpage"de
sonsuza dek bekleyebilir; kod `--impersonate chrome` kullanır (`createclip/ytdlp.py`), 3 dk zaman aşımı vardır.
(2) Whisper modeli diskte olsa da Hugging Face'e güncelleme sorusu IPv6'da takılabilir; önbellekteki model çevrimdışı yüklenir.

## Sınırlar
- Kick sohbet API'si resmi değil; değişirse kırılabilir. VOD'lar Kick'te süreli saklanır.
- Altyazılar yaklaşık: özel isimler yanlış çıkabilir; web'de düzeltip yeniden bas. Kesimi değiştirirsen konuşma yeniden çözülür,
  metin düzeltmelerin sıfırlanır.
- Ses yedeği yalnızca ölçüm adımı gerçek dosyada denendi; tam VOD ile uçtan uca çalıştırılmadı.
- Kick'in CDN'i zaman zaman takılır: indirme 4 dk zaman aşımı ve 3 deneme ile korunur.
- Küfür filtresi yalnızca yaygın kök listesine bakar. İş durdurma (iptal) henüz yok.
- Yalnızca kendi içeriğin ya da izin aldığın yayınlar için kullan.

## Lisans
MIT (bkz. `LICENSE`). Paketlenen fontlar SIL OFL 1.1 (`createclip/fonts/README.md`).
