# autoshorts

Video linkini (ya da kanalı) ver; en iyi anları bulsun, dikey (9:16) kliplere çevirsin ve `ready/` klasörüne kaydetsin.
Her klip yanında başlık + açıklama (`.txt`) ve kapak (`.jpg`) ile gelir. YouTube'a panelden onaylayarak yükleyebilirsin; diğer yerlere kendin yüklersin.
Her şey kendi bilgisayarında çalışır (Apple Silicon Mac hedeflenir).

```
kanal/link ─► download.py (yt-dlp) ─► finder.py (an bul) ─► render.py (9:16, ses) ─► export.py ─► ready/<tarih>/
```

## Kurulum
```bash
brew install ffmpeg yt-dlp
python3 -m venv .venv && ./.venv/bin/pip install -e ".[dev]"
./.venv/bin/autoshorts doctor
```

## Kullanım
**Web arayüzü** (önerilen): link yapıştır, yayının zaman çizelgesinde sohbet yoğunluğunu ve bulunan anları canlı izle, klipleri oynat, başlık/açıklamayı düzenle, indir. React arayüzü `web/` klasöründe:
```bash
(cd web && npm install && npm run build)      # arayüzü derle (Node gerekir)
./.venv/bin/autoshorts serve --open           # http://127.0.0.1:8765
```
Geliştirirken: `autoshorts serve` + `cd web && npm run dev` (5173, API'yi 8765'e yönlendirir).

Ana sayfanın altında **terminal** var: işin adımları, çalıştırdığı her komut (yt-dlp, ffmpeg), süreleri ve hataları canlı akar; küçültülebilir, kopyalanabilir. Editörde dışa aktarma ve kamera arama işleri de aynı terminali açar. 20 dakika (Ayarlar'dan değişir) hiç ilerleme olmayan iş kendiliğinden durdurulur; 5 dakikada terminalde uyarı çıkar.

**Bilgisayarı yormama** (Ayarlar > Bilgisayar gücü, varsayılan *Tasarruf*): Mac'te donanım H.264 kodlayıcısı (VideoToolbox), ffmpeg için 2 iş parçacığı ve tüm alt işlemler için düşük öncelik (`nice`) kullanılır. Bu makinede (M3) 40 sn'lik 1080p kaynak için ölçüm (arka planın hâlâ bulanık olduğu sürümde): eski yöntem 84 sn / 103 işlemci-saniyesi, yeni bulanıklık + x264 15 sn / 48, + donanım kodlayıcı 7 sn / 19. Donanım kodlayıcı aynı görsel kalite için x264'ten yaklaşık %40 daha büyük dosya üretir; *Tam hız* seçeneği x264 ve tüm çekirdekleri kullanır. Mac dışında donanım kodlayıcı yoksa x264 (2 iş parçacığı) kullanılır.

**Çekiliş / tekrar eden mesajlar:** Yayında herkes aynı mesajı (“katılıyorum”, `!katıl`) yazdığında sohbet tepesi sahte olur. Sohbet puanı bunları saymaz: `!` ile başlayan komutlar, 10 sn'lik bir aralığı tek başına domine eden metinler ve aynı metin akışta 6+ aralığı domine ediyorsa (kampanya) her yerde. Kahkaha (`ahahah`, `kkkk`, `lol`) gerçek tepki sayılır. Herkesin farklı rastgele metin yazdığı (klavyeye basma) ya da tek kısa kelime bağırdığı (GOL, pog) hype anları sayılır; yalnızca uzun bir metnin 15 dakika içinde 15+ aralıkta tekrar tekrar yapıştırılması çekiliş sayılır. Ayrıca aynı 10 dakikadan en çok 3 klip çıkar, bu yüzden uzun bir coşku/çekiliş bölgesi tüm klipleri yutamaz. Yok sayılan mesajlar terminale yazılır.

**Tekli klip** (menüde “Tekli klip”, `/tekli`): yayın linki, başlangıç zamanı ve süre; analiz yapılmaz, yalnızca o aralık indirilip klibe çevrilir. Elle verilen zamanlar cümleye kaydırılmaz, yazdığın gibi kalır.


**Kamera üstte, oyun altta:** Ayarlar > "Yeni kliplerin yerleşimi" ile yeni klipler otomatik olarak iki pencereli üretilir: OpenCV ile yayıncının kamera yüzü bulunur ve üst pencereye (%30/35/40/50 oranında), tüm oyun görüntüsü alt pencereye konur; yüz bulunamazsa siyah arka plan kullanılır. Editörde "İki pencere" sekmesinde oran seçilir (%30·%70 … %60·%40), pencereler yer değiştirir, **Kamerayı bul** ile mevcut klibin kamerası aranır. Kurulum: `pip install -e ".[faces]"`. Kaynak görüntüsü 14 günden eski ve düzenlenmemiş klipler kendiliğinden temizlenir (Ayarlar).

**Paketleme:** `autoshorts build-ui` arayüzü derleyip paketin içine (`autoshorts/webdist`) gömer; böylece `pip install .` ile kurulan kopya `web/` klasörü olmadan da arayüzü sunar.

**Düzenleyici** (`/editor/<klip>`): klibi panelde açıp **Düzenle**. Kaynak görüntü (klibin ±30 sn çevresi) saklanır; eski klipler için ilk açılışta yayından indirilir. Önizleme, zaman çizelgesi (kare şeridi + ses dalgası), kırpma tutamaçları, yerleşim (siyah arka plan / tek pencere / iki pencere; önizlemede sürükleyip kaydır, yakınlaştır), ses seviyesi ve ses dengeleme. **Dışa aktar** düzenlemeyi ffmpeg ile işler, `ready/` klasörüne yeni dosya olarak yazar, klibi ona bağlar ve önceki sürümü aynı klasördeki `_eski/` içine taşır; düzenleme projesi kaydedilir. Kaynak görüntüler yer kaplar: Ayarlar > Depolama'dan temizlenir (hazır klipler silinmez). Kısayollar: Boşluk oynat/duraklat, ← → 0,1 sn (⇧ ile 1 sn), I / O başlangıç/bitiş, ⌘Z geri al. **Metin katmanı:** Metin ekle ile başlık/etiket/emoji; istediğin aralıkta ekranda kalır (süre klibin başından sayılır), önizlemede sürükleyerek taşınır, zaman çizelgesinde çubuk olarak görünür ve sürüklenip kaydırılır. Yazı tipi, boyut, renk, kontur, arka zemin ayarlanır; en çok 12 katman. Emoji tek karakterli olanlar için çalışır (macOS Apple Color Emoji); ZWJ birleşik emojiler (👨‍👩‍👧) birleşmez.
Komut satırı:
```bash
autoshorts run "<video-linki>" -n 5                 # en iyi 5 anı kes → ready/<tarih>/
autoshorts run "<link>" --start 10:00               # ilk 10 dakikayı atla (açılış kalabalığı)
autoshorts run "<link>" --at 1:44:50-1:45:40        # elle zaman ver (sohbet/ses analizi gerekmez)
autoshorts run "<link>" --engine audio              # sohbet yerine ses yüksekliği

autoshorts add kick.com/kanal                       # kanalı izle (ya da youtube.com/@kanal)
autoshorts watch                                    # tara → klip üret, saatte bir (--once: tek tur)
autoshorts clips                                    # üretilen klipler
autoshorts config                                   # ayarlar; değiştirmek için: config max_len=45 output_dir=/yol
```
Çıktı: `ready/2026-11-23/<kanal>_<zaman>_<id>.mp4` + `.txt` (başlık, açıklama, kaynak bağlantısı, etiketler) + `.jpg`.
Başlıkları ve açıklamayı yüklemeden önce düzenle; kural tabanlıdır (yayın başlığı + zaman damgalı kaynak bağlantısı + etiketler).

- **YouTube engeli:** 429 / "bot değilsin" yanıtı alınırsa `BlockedError` ile durur, kalan klipleri denemez; birkaç saat bekle.

> **Yeniden kullanım riski.** Başkasının yayınından alınan klipleri katkısız yüklemek YouTube'un yeniden kullanım politikasının
> hedefidir ve kanal erişimini düşürebilir; TikTok/Instagram da benzer kurallar uygular. Yayıncıdan izin al ve klibe kendi
> katkını (yorum, bağlam) ekle. Hukuki tavsiye değildir.

## YouTube'a yükleme
Hiçbir klip kendiliğinden yüklenmez: Panel > Klipler'de klibi açıp **Sıraya al** (Ayarlar'daki günlük saatler, varsayılan 13:00 ve 20:00),
bir yayın zamanı seçip **Bu saate yükle** ya da **Şimdi yayınla** de ve onayla. Zamanlanan videoyu YouTube kendisi yayınlar, bilgisayarın açık kalması gerekmez.
Video "çocuklara özel değil" ve "Eğlence" kategorisiyle yüklenir.

**Bir kerelik kurulum** (Google Cloud Console, kanalının Google hesabıyla):
1. console.cloud.google.com'da yeni bir proje oluştur.
2. *APIs & Services > Library*: **YouTube Data API v3**'ü etkinleştir.
3. *Google Auth Platform* (OAuth consent screen): uygulama adı ve e-postanı gir, kullanıcı türü **External**. *Audience* sayfasında **Publish app** ile durumu
   "In production" yap (Testing'de kalırsa izin 7 günde bir düşer). Kendi uygulaman olduğu için bağlanırken "doğrulanmamış uygulama" uyarısı çıkar.
4. *Clients > Create client*: tür **Desktop app**. JSON dosyasını indir.
5. Dosyayı çalışma klasöründe `data/youtube/client_secret.json` olarak kaydet (klasörü Ayarlar > YouTube bölümü tam yoluyla gösterir).
6. `autoshorts serve` açıkken Ayarlar > **YouTube'a bağlan**; izin ekranında kanalını seç.

`data/youtube/` içindeki dosyalar şifre gibidir: paylaşma, repoya ekleme (`data/` zaten yok sayılır). API'nin günlük yükleme kotası vardır (varsayılan 100).

## Klip bulucu motorları (`engine`)
| Motor | Ne yapar | Not |
|---|---|---|
| `chat` | Sohbet yoğunluğu (10 sn dilimde eşsiz sohbetçi, z-skoru) | Kick + YouTube sohbet tekrarı; canlı yayınlar için en iyisi. Kick'te ~1,5 istek/sn sınırı: 6 saatlik yayın ~25 dk |
| `audio` | Ses yüksekliği tepeleri | Sohbet yoksa; YouTube ~0,35 MB/dk, Kick ~1,7 MB/dk |
| `transcript` | **ClipsAI** (videodaki kütüphane), konuşma metninden | Podcast/röportaj için tasarlı, oyun yayınında zayıf; `pip install clipsai whisperx` (torch, Python ≤3.12); **bu repoda denenmedi** |
| `auto` (varsayılan) | `chat`, olmazsa `audio` | |

## Canlı yayın (Kick)
Yayın sürerken de klip alınabilir: canlı yayının linki (`kick.com/<kanal>/videos/<id>`, `autoshorts add`/kanal listesinde "canlı" diye geçen) normal bir VOD gibi
yapıştırılır. Süre, "yayın başlangıcından şimdiye" hesaplanır ve son ~40 sn hariç tutulur (son HLS parçaları eksik olabilir). Elle zamanla (`--at`, Tekli klip)
şimdiye kadarki herhangi bir an kesilir; henüz olmamış bir an net bir hata verir. Sohbetle an bulma yayının o ana kadarki kısmında çalışır
(Kick'in ~1,5 istek/sn sınırı geçerli; yayın uzadıkça tekrar çalıştırınca önbellek sayesinde yalnız yeni kısım istenir). Gerçek canlı yayında denendi
(30 sn'lik kesit → 1080×1920 klip). YouTube canlı yayınları hâlâ yayın bitince işlenir.

**Yayın bitince kalanı al:** aynı video linkini tekrar yapıştır (kanal linkini değil). Yayın canlıyken işlendiyse arama son klibin bitiminden sonrasını kapsar,
önceki bölüm yeniden puanlanmaz. Ayrıca mevcut bir klibin ±15 sn içindeki adaylar aynı an sayılır ve atlanır.

## Geliştirme
```bash
./.venv/bin/python -m pytest -q
```
