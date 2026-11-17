# createclip

Kick VOD linkini yapıştır → en iyi anları bulur, klipleri keser, Türkçe kelime kelime altyazı basar,
istersen 9:16'ya çevirir. Her klip web arayüzünde düzenlenebilir. Her şey yerelde çalışır (Apple Silicon Mac).

## Gereksinimler
`ffmpeg`, `yt-dlp`, `curl` (`brew install ffmpeg yt-dlp`). İlk altyazıda `mlx-community/whisper-large-v3-mlx`
(~3 GB) indirilir; ayrı hizalama modeli gerekmez.

## Kurulum
```bash
cd createclip && python3 -m venv .venv && ./.venv/bin/pip install -e ".[dev]"
```

## Kullanım
```bash
./.venv/bin/createclip serve          # web editörü: http://127.0.0.1:8765
./.venv/bin/createclip run "<kick-linki>" -n 5                       # altyazılı + altyazısız
./.venv/bin/createclip run "<link>" --layout stack --mask-profanity  # 9:16 iki pencere, küfür yıldızlı
./.venv/bin/createclip run "<link>" --at 1:44:50 --at 0:27:50-0:28:40  # elle zamanlar (sohbet gerekmez)
./.venv/bin/createclip run "<link>" --source audio                   # sohbet yerine ses seviyesi
./.venv/bin/createclip run "<link>" --full-chat --size 0.06 --ypos 0.7 --chunk 2 --sync -0.1 --max-height 1080
```
Çıktı: `output/<kanal>-<vod>/` → `clips/` (altyazısız), `captioned/` (altyazılı), `words/` (`.json`, `.srt`),
`raw/` (kenar payı olan ham kesit), `chat.jsonl` (önbellek), `manifest.json`.

## Üretmeden önce (yeni proje formu)
Sohbet modu (hızlı / tam / yalnız ses), klip sayısı ve süre aralığı, çözünürlük, 9:16 yerleşim, altyazı stili
(font, boyut, konum, renk, kontur, kelime/ekran, senkron) ve **canlı önizleme**; ayarlar tarayıcıda hatırlanır,
"ön ayar" olarak kaydedilebilir.

## Web editörü (klip başına)
- **Kesim:** başlangıç/bitiş (±1 sn düğmeleri). Ham kesitin ±10 sn payı içindeyse yeniden indirmez.
- **Altyazı:** aç/kapa, metni düzenle (zamanlama korunur), font, boyut, dikey konum, kelime/ekran, renkler, küfür maskesi.
- **9:16 yerleşim:** yatay / bulanık arka plan / tek pencere / iki pencere. Kaynak kareye tıklayarak pencere
  merkezini seç, yakınlığı kaydırıcıyla ayarla; sağdaki önizleme sonucu gösterir.
- **Senkron:** −1…+1 sn kaydırıcı; yalnız altyazı yeniden basılır. Varsayılan −0,08 sn (altyazı biraz erken).
- Kontur kalınlığı, BÜYÜK/küçük harf; klipler skora göre (en iyi üstte) ya da zamana göre sıralanır.
- Projeye "sıradaki en iyi anı ekle" (30 adaydan) veya elle başlangıç/bitiş ile klip ekleme; klip silme;
  önceki projeleri açma.

## Nasıl çalışır
1. **Sohbet** Kick'in resmi olmayan API'sinden `curl` ile, 4 paralel istekle indirilir ve önbelleğe alınır. Ölçüm (2,5 saatlik
   yayın, ~16 bin mesaj): **hızlı mod 18,4 dk (mesajların %98'i), tam mod 19,6 dk**; süreyi Kick'in hız sınırı (`429`) belirler,
   bu yüzden mod farkı küçüktür. Gerçekten hızlı yol: yalnız ses modu. Bir istek ~5 sn'lik pencere ve en çok ~25
   mesaj döndürür; `cursor` alanı güvenilmez (mesaj atlatır), bu yüzden son mesajdan/5 sn adımla ilerlenir. Alınamazsa en düşük
   kaliteli VOD (~250 MB) indirilip **ses seviyesi** ölçülür.
2. **Pik:** 10 sn dilimlerde eşsiz sohbetçi sayısı (yalnız emote'lar düşük ağırlık), yayının ortalamasına göre
   z-skoru; ilk 2 dk / son 1 dk atlanır; pikler ≥90 sn arayla; pencere pikten 20 sn önce, 25-60 sn.
3. **Kesim:** `yt-dlp --download-sections` ile sadece ilgili aralık (±10 sn pay), sonra kesim noktaları
   `silencedetect` ile en yakın konuşma arasına hizalanır.
4. **Altyazı:** mlx-whisper large-v3 (kelime zamanlı), ipucu (prompt) olmadan: ölçümde uzun ipucu konuşmanın büyük
   kısmını atlatıyordu (69 yerine 27 kelime). `--vocab "Berk, Derbeder"` ile isteğe bağlı kısa kelime listesi verilebilir; Pillow ile
   çizilip ffmpeg `overlay` ile bindirilir (libass gerekmez). Montserrat / Poppins / Gabarito (OFL).
5. **9:16:** ffmpeg ile pencere kırpma / bulanık arka plan; yüz takibi yerine elle ayarlanabilir pencereler
   (her yayıncının yerleşimi farklı olduğu için).

## Altyazı senkronu
Kayma kaynağı bulundu ve düzeltildi: kelime zamanları üst üste bindiğinde (kelime bitişi + 0,15 sn pay sonraki kelimeye taştığında)
bindirme zaman çizelgesi her seferinde gecikiyor ve hata klip boyunca birikiyordu. Artık altyazı durumları sıralı ve
çakışmasız üretilir (`captions.build_states`). Ses/video akış başlangıçları ve Whisper kelime zamanları 5 klipte ölçüldü:
medyan sapma ±0,09 sn. Kalan ince kayma için senkron kaydırıcısı var.

## Sınırlar
- Kick sohbet API'si resmi değil; değişirse kırılabilir. VOD'lar Kick'te süreli saklanır.
- Altyazılar yaklaşık: özel isimler yanlış çıkabilir; web'de düzeltip yeniden bas. Kesimi değiştirirsen
  konuşma yeniden çözülür ve metin düzeltmelerin sıfırlanır.
- Ses yedeği yalnızca ölçüm adımı gerçek dosyada denendi; tam VOD ile uçtan uca çalıştırılmadı.
- Kick'in CDN'i zaman zaman takılır: indirme 4 dk zaman aşımı ve 3 deneme ile korunur.
- Küfür filtresi yalnızca yaygın kök listesine bakar.
