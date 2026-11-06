# ⚡ AURIX Downloader

**YouTube kanalidan Telegram kanalga avtomatik MP3 joylovchi bot + YouTube va Instagram yuklovchi.**

AURIX Downloader siz tanlagan YouTube kanalni har 5 daqiqada tekshiradi.
Yangi video chiqishi bilan uni MP3 (192 kbps) ga aylantiradi va Telegram kanalingizga
playable audio sifatida joylaydi. Postda nomi, YouTube havolasi, sanasi va AURIX brendi bo'ladi.
Shuningdek, oddiy foydalanuvchilar botga **YouTube** yoki **Instagram** (reels, post, IGTV) havolasini
yuborib MP3 yoki MP4 yuklab olishlari mumkin.

```
🎵 AURIX MUSIC

🎧 Track: Qo'shiq nomi
📅 Sana: 05.11.2026 15:00
▶️ Original YouTube: https://www.youtube.com/watch?v=...

⚡ Powered by AURIX Downloader
```

> ⚠️ **Huquqiy eslatma.** Botni faqat sizga tegishli yoki tarqatishga **ruxsatingiz bor** YouTube
> kanal bilan ishlating. Bot yopiq (private), faqat obunachilar uchun, pullik, yosh cheklovli va DRM bilan
> himoyalangan videolarni **yuklamaydi** va hech qanday himoyani chetlab o'tmaydi.

---

## 📑 Mundarija

1. [Qanday ishlaydi](#-qanday-ishlaydi)
2. [Loyiha tuzilmasi](#-loyiha-tuzilmasi)
3. [1-qadam: Bot yaratish](#1-qadam-botfather-orqali-bot-yaratish)
4. [2-qadam: Admin ID](#2-qadam-telegram-id-ingizni-bilish)
5. [3-qadam: Botni kanalga admin qilish](#3-qadam-botni-telegram-kanalga-administrator-qilish)
6. [4-qadam: .env sozlash](#4-qadam-env-faylini-sozlash)
7. [Kompyuterda ishga tushirish](#-kompyuterda-lokal-ishga-tushirish)
8. [VPS ga joylash (Ubuntu 24.04 + Docker)](#-vps-ga-joylash-ubuntu-2404--docker)
   · [Render.com ga joylash](#-rendercom-ga-joylash-bepul-cheklangan)
9. [Admin buyruqlari](#-admin-buyruqlari)
10. [Testlar](#-testlar)
11. [Muammolar va yechimlar](#-muammolar-va-yechimlar)

---

## 🧠 Qanday ishlaydi

```
 YouTube RSS ──(har 5 daqiqa)──► Monitor ──► SQLite navbat ──► Ishchi (worker)
                                   │              │                 │
                       yangi video ID lari   qayta ishga tushsa   yt-dlp → FFmpeg MP3
                       (dublikatlar yo'q)    ham saqlanadi        → Telegram sendAudio
```

* **Monitoring**: YouTube RSS feed (`/feeds/videos.xml?channel_id=...`) har `CHECK_INTERVAL_SECONDS` da tekshiriladi.
* **Dublikat yo'q**: har bir video ID SQLite da saqlanadi (`processed_videos`), Telegram post ID si esa `channel_posts` da.
  Bitta video hech qachon ikki marta joylanmaydi.
* **Navbat** SQLite da saqlanadi: server o'chib qolsa ham navbat yo'qolmaydi. Yarim qolgan ish qayta navbatga qo'yiladi.
* **Offline vaqt**: bot o'chiq bo'lganda chiqqan videolar (`LOOKBACK_HOURS` ichida) qayta yonganda avtomatik joylanadi.
* **Birinchi ulanish**: kanal birinchi marta qo'shilganda eski videolar "ko'rildi" deb belgilanadi va spam bo'lmaydi.
  Xohlasangiz `INITIAL_BACKFILL_COUNT=3` qilib, oxirgi 3 tasini ham joylashingiz mumkin.
* **Xatolar**: tarmoq xatolarida bot qayta urinadi (1, 2, 4, 8… daqiqa). Doimiy xatolarda (yopiq video va h.k.)
  adminlarga xabar yuboradi.
* **Premyera / jonli efir**: tugashini kutadi (har 15 daqiqada tekshiradi).
* **Telegram limiti (50 MB)**: uzun audio bo'lsa bitreyt avtomatik pasaytiriladi (minimal 64 kbps). MP4 da sifat 720p → 480p → 360p tanlanadi.

## 📁 Loyiha tuzilmasi

```
aurix_downloader/
├── bot.py               # Kirish nuqtasi: bot + monitor + navbat
├── config.py            # .env sozlamalari
├── database.py          # SQLite (aiosqlite) jadvallar va so'rovlar
├── monitor.py           # YouTube RSS monitoring (fon xizmati)
├── queue_worker.py      # Navbat: video → MP3 → kanal
├── youtube_service.py   # RSS, kanal ID aniqlash, yt-dlp metama'lumot, ruxsat tekshiruvi
├── audio_service.py     # yt-dlp audio + FFmpeg MP3 konvertatsiya
├── video_service.py     # Foydalanuvchilar uchun MP4
├── telegram_service.py  # sendAudio, caption, qayta urinishlar
├── admin.py             # Admin buyruqlari va panel
├── handlers/            # /start, menyu, havola qabul qilish
├── keyboards/           # Tugmalar
├── utils/               # Validatsiya (SSRF himoya), log, matnlar
├── tests/               # pytest testlar (tashqi xizmatlar mock qilingan)
├── downloads/  logs/  data/
├── Dockerfile  docker-compose.yml  healthcheck.py
├── requirements.txt  requirements-dev.txt
└── .env.example
```

**Ma'lumotlar bazasi jadvallari:** `users`, `source_channels`, `processed_videos`, `download_jobs`,
`channel_posts`, `bot_statistics`, `settings`.

---

## 1-qadam: BotFather orqali bot yaratish

1. Telegramda [@BotFather](https://t.me/BotFather) ni oching → `/newbot`.
2. Bot nomini yozing, masalan: `AURIX Downloader`.
3. Username yozing (oxiri `bot` bilan tugashi shart), masalan: `aurix_downloader_bot`.
4. BotFather bergan **token**ni saqlang (`1234567890:AA...`). Bu maxfiy parol — hech kimga bermang!
5. Tavsiya: `/setuserpic` orqali qora-ko'k-binafsha logotip, `/setdescription` orqali tavsif qo'ying.

## 2-qadam: Telegram ID ingizni bilish

[@userinfobot](https://t.me/userinfobot) ga `/start` yozing — u sizning raqamli ID ingizni beradi
(masalan `123456789`). Shu ID `.env` dagi `ADMIN_IDS` ga yoziladi.
Bir nechta admin bo'lsa: `ADMIN_IDS=123456789,987654321`.

## 3-qadam: Botni Telegram kanalga administrator qilish

Bot kanalga post joylay olishi uchun u **administrator** bo'lishi shart.

1. Telegram kanalingizni oching → kanal nomini bosing → **✏️ Tahrirlash (Edit)**.
2. **Administratorlar (Administrators)** → **Administrator qo'shish (Add Admin)**.
3. Qidiruvga botingiz username ini yozing (`@aurix_downloader_bot`) va tanlang.
4. Huquqlardan **«Xabar joylash» (Post Messages)** ni albatta yoqing. Qolganlari shart emas.
5. **Saqlash (Save)** ni bosing.

✨ Bot ishlab turgan bo'lsa, u sizga avtomatik xabar yuboradi: *"Bot kanalga administrator qilindi"*.
Unda kanal ID si va **«✅ Shu kanalga joylash»** tugmasi bo'ladi. Uni bossangiz, kanal darhol sozlanadi.

Yoki qo'lda:
* Ochiq kanal: `/set_destination_channel @kanal_username`
* Yopiq kanal: `/set_destination_channel -1001234567890`

## 4-qadam: .env faylini sozlash

```bash
cp .env.example .env
```

```bash
nano .env
```

Eng kamida shularni to'ldiring:

| O'zgaruvchi | Ma'nosi | Misol |
|---|---|---|
| `BOT_TOKEN` | BotFather bergan token | `1234567890:AAE...` |
| `ADMIN_IDS` | Admin Telegram ID lari | `123456789` |
| `TELEGRAM_CHANNEL_ID` | Telegram kanal (botda ham o'rnatsa bo'ladi) | `@aurix_music` |
| `YOUTUBE_CHANNEL` | Kuzatiladigan YouTube kanal (botda ham o'rnatsa bo'ladi) | `https://www.youtube.com/@kanal` |

Boshqa sozlamalar (`CHECK_INTERVAL_SECONDS`, `LOOKBACK_HOURS`, `AUDIO_BITRATE_KBPS`,
`MAX_CONCURRENT_DOWNLOADS` va h.k.) `.env.example` ichida izohlari bilan berilgan.

> Bot ichida `/set_source_channel` va `/set_destination_channel` bilan o'rnatilgan qiymatlar
> `.env` dagidan ustun turadi va bazada saqlanadi.

---

## 💻 Kompyuterda (lokal) ishga tushirish

Talablar: **Python 3.13**, **FFmpeg**.

```bash
sudo apt update && sudo apt install -y ffmpeg git python3.13 python3.13-venv
```

> Ubuntu 24.04 da Python 3.13 bo'lmasa: `sudo add-apt-repository ppa:deadsnakes/ppa` dan keyin yuqoridagi buyruqni takrorlang.
> Eng oson yo'l esa Docker (pastda).

```bash
git clone https://github.com/boburjon120/my_FISRT_LOYIHA.git
```

```bash
cd my_FISRT_LOYIHA/aurix_downloader
```

```bash
python3.13 -m venv .venv
```

```bash
source .venv/bin/activate
```

```bash
pip install -r requirements-dev.txt
```

```bash
cp .env.example .env
```

`.env` ni to'ldiring, so'ng:

```bash
python bot.py
```

Telegramda botingizga `/start`, keyin `/admin` yozing. To'xtatish: `Ctrl + C`.

---

## 🚀 VPS ga joylash (Ubuntu 24.04 + Docker)

### 1. Serverga ulaning

```bash
ssh root@SERVER_IP
```

### 2. Docker o'rnating (bir marta)

```bash
sudo apt update && sudo apt install -y git curl
```

```bash
curl -fsSL https://get.docker.com | sudo sh
```

Docker server qayta yonganda avtomatik ishga tushishi uchun:

```bash
sudo systemctl enable --now docker
```

Tekshirish:

```bash
docker compose version
```

### 3. Loyihani yuklab oling

```bash
git clone https://github.com/boburjon120/my_FISRT_LOYIHA.git
```

```bash
cd my_FISRT_LOYIHA/aurix_downloader
```

### 4. Sozlamalar

```bash
cp .env.example .env
```

```bash
nano .env
```

(`BOT_TOKEN`, `ADMIN_IDS` va kanallarni yozing. Saqlash: `Ctrl+O`, `Enter`, chiqish: `Ctrl+X`.)

### 5. Ishga tushiring

```bash
docker compose up -d --build
```

Hammasi shu! 🎉 Konteyner `restart: unless-stopped` rejimida ishlaydi:
bot xato bilan to'xtasa yoki server qayta yuklansa, **o'zi qayta ishga tushadi** va monitoring avtomatik davom etadi.

### Foydali buyruqlar

Loglarni ko'rish (jonli):

```bash
docker compose logs -f --tail 100
```

Holatni ko'rish (`healthy` bo'lishi kerak):

```bash
docker compose ps
```

Qayta ishga tushirish:

```bash
docker compose restart
```

To'xtatish:

```bash
docker compose down
```

Yangilash (yangi kod chiqqanda):

```bash
git pull && docker compose up -d --build
```

yt-dlp ni yangilash (YouTube o'zgarganda kerak bo'ladi — oyiga bir marta tavsiya etiladi):

```bash
docker compose build --no-cache && docker compose up -d
```

Bazaning zaxira nusxasi (backup):

```bash
docker compose cp aurix:/app/data/aurix.db ./aurix-backup-$(date +%F).db
```

Fayl loglari konteyner ichida `/app/logs/aurix.log` da (5 MB dan aylanadi):

```bash
docker compose exec aurix tail -n 100 /app/logs/aurix.log
```

Ma'lumotlar Docker volume larda saqlanadi (`aurix_data`, `aurix_logs`, `aurix_downloads`) — `docker compose down` qilsangiz ham o'chmaydi.

---

## 🌐 Render.com ga joylash (bepul, cheklangan)

> ⚠️ Render bepul tarifida **doimiy disk yo'q**: har qayta ishga tushganda baza tozalanadi.
> Dublikat post bo'lmaydi (bot qayta yonganda mavjud videolarni "ko'rildi" deb belgilaydi),
> lekin bot o'chiq paytda chiqqan video o'tkazib yuborilishi mumkin. Doimiy ish uchun VPS yaxshiroq.

1. https://dashboard.render.com → **New +** → **Blueprint**.
2. GitHub repozitoriyni ulang: `boburjon120/my_FISRT_LOYIHA`. Render `render.yaml` faylini o'zi topadi.
3. So'ralgan qiymatlarni kiriting:
   * `BOT_TOKEN` — @BotFather bergan token
   * `ADMIN_IDS` — Telegram ID ingiz
   * `TELEGRAM_CHANNEL_ID` — masalan `@aurix_music` (yoki keyin botda o'rnating)
   * `YOUTUBE_CHANNEL` — masalan `https://www.youtube.com/@kanal`
4. **Apply** ni bosing. Build 3–6 daqiqa davom etadi. Loglarda `Bot @... started` chiqishi kerak.
5. Xizmat manzilini nusxalang (masalan `https://aurix-downloader.onrender.com`).
   Brauzerda `.../health` ochilsa `{"status": "ok", ...}` ko'rinadi.

### Botni uxlatmaslik (UptimeRobot)

Render bepul xizmati 15 daqiqa so'rov kelmasa uxlaydi. Uni uyg'oq ushlash uchun:

1. https://uptimerobot.com da bepul ro'yxatdan o'ting.
2. **Add New Monitor** → turi **HTTP(s)**.
3. URL: `https://SIZNING-XIZMAT.onrender.com/health`, interval: **5 minutes**.
4. **Create Monitor**.

`PORT` o'zgaruvchisini Render o'zi beradi. Bot uni ko'rsa `/health` sahifasini avtomatik ochadi.

---

## 🛠 Admin buyruqlari

Faqat `ADMIN_IDS` dagi foydalanuvchilar ishlata oladi. Boshqalar `⛔` javobini oladi.

| Buyruq | Vazifasi |
|---|---|
| `/start` | Botni boshlash, asosiy menyu |
| `/admin` | Boshqaruv paneli (tugmalar bilan) |
| `/set_source_channel <havola>` | Kuzatiladigan YouTube kanalni o'rnatish/almashtirish |
| `/set_destination_channel <@kanal>` | Telegram kanalni o'rnatish/almashtirish (bot huquqlari tekshiriladi) |
| `/channel_status` | Monitoring holati, oxirgi tekshiruv, xatolar |
| `/check_now` | Kanalni hozir tekshirish |
| `/queue` | Navbatdagi va jarayondagi videolar |
| `/failed` | Xato bilan tugagan videolar va ishlar |
| `/retry <video_id>` yoki `/retry all` | Xato bo'lganlarni qayta navbatga qo'yish |
| `/stats` | Statistika (joylangan, xato, foydalanuvchilar…) |
| `/restart_monitor` | Monitor va navbat ishchisini qayta ishga tushirish |
| `/help` | Yordam |
| `/cancel` | Joriy amalni bekor qilish |

`/set_source_channel` qabul qiladigan formatlar:
`https://www.youtube.com/@kanal`, `@kanal`, `https://www.youtube.com/channel/UC...`, `UC...` (kanal ID).

### Foydalanuvchi menyusi

* **🎵 YouTube MP3** / **🎬 YouTube Video**: havola yuborish bo'yicha yo'riqnoma.
* **📡 Kanal holati**: qaysi kanal kuzatilmoqda, nechta trek joylandi.
* **ℹ️ Bot haqida**.
* **📸 Instagram Video**: Instagram havolasi bo'yicha yo'riqnoma.
* YouTube havolasini yuborsangiz, bot rasm, nom va davomiylikni ko'rsatadi. Tugmalar:
  **🎵 MP3 yuklab olish**, **🎬 MP4 yuklab olish**, **▶️ YouTube'da tinglash / ko'rish**.
* Instagram havolasini (`instagram.com/reel/…`, `/p/…`, `/tv/…`) yuborsangiz, xuddi shunday karta chiqadi:
  **🎵 MP3**, **🎬 MP4**, **📸 Instagram'da ochish**. Faqat **ochiq (public)** akkauntlar; stories qo'llab-quvvatlanmaydi.

---

## 🧪 Testlar

Barcha tashqi xizmatlar (YouTube, Telegram) mock qilingan. MP3 testlari haqiqiy FFmpeg bilan ishlaydi.

```bash
pytest -q
```

Qamrab olingan: RSS monitoring, yangi video aniqlash, dublikatlar, MP3 konvertatsiya (192 kbps, metama'lumot,
muqova), Telegram `sendAudio` va qayta urinishlar, admin avtorizatsiyasi (haqiqiy aiogram Dispatcher orqali),
navbat ishlovi, restartdan keyin tiklanish, URL validatsiya / SSRF himoyasi.

---

## 🔒 Xavfsizlik

* Barcha maxfiy ma'lumotlar `.env` da. `.env` git ga tushmaydi (`.gitignore`).
* Bot tokeni loglarda avtomatik yashiriladi.
* Faqat `youtube.com` / `youtu.be` havolalari qabul qilinadi. yt-dlp ga faqat tekshirilgan video ID dan
  qayta tuzilgan `https://www.youtube.com/watch?v=ID` beriladi (SSRF himoyasi).
* Bir vaqtda yuklashlar soni cheklangan (`MAX_CONCURRENT_DOWNLOADS`), har foydalanuvchiga bitta faol yuklash va cooldown.
* Foydalanuvchilarga server yo'llari yoki ichki xatolar ko'rsatilmaydi.
* Konteyner root bo'lmagan foydalanuvchi (`aurix`) nomidan ishlaydi.

---

## 🩺 Muammolar va yechimlar

**`Sign in to confirm you're not a bot` / `HTTP 429`**
YouTube ba'zi datacenter IP manzillaridan kelgan so'rovlarni cheklaydi. Bot buni vaqtinchalik xato deb
hisoblab, keyinroq qayta urinadi. Muammo davom etsa:
1. yt-dlp ni yangilang: `docker compose build --no-cache && docker compose up -d`.
2. O'zingizning YouTube akkauntingizdan `cookies.txt` eksport qiling (brauzer kengaytmasi orqali) va konteynerga nusxalang:

   ```bash
   docker compose cp cookies.txt aurix:/app/data/cookies.txt
   ```

   ```bash
   docker compose exec -u root aurix chown aurix:aurix /app/data/cookies.txt
   ```

   `.env` ga `YTDLP_COOKIES_FILE=/app/data/cookies.txt` yozing va `docker compose up -d` qiling.
   Shunda ham yopiq, pullik va yosh cheklovli videolar **yuklanmaydi**: bot bunga yo'l qo'ymaydi.

**Instagram: `login talab qilyapti` / `Instagram vaqtincha so'rovlarni chekladi`**
Instagram serverlardan kelgan so'rovlarni ko'pincha login so'rab bloklaydi. Yechim YouTube'dagi kabi:
**ikkinchi** Instagram akkauntingizdan `cookies.txt` eksport qiling (Inkognito oynada instagram.com ga kiring →
"Get cookies.txt LOCALLY" → Export) va `INSTAGRAM_COOKIES_FILE` ga ko'rsating.
Render'da: Environment → Secret Files → `instagram_cookies.txt`. Asosiy akkauntingizni ishlatmang — Instagram
avtomatik so'rovlar uchun akkauntni bloklashi mumkin. Yopiq akkauntlar baribir yuklanmaydi.

**`Kanal topilmadi yoki bot kanalga qo'shilmagan` / `chat not found`**
Botni kanalga admin qiling (3-qadam) va «Post Messages» huquqini yoqing. Yopiq kanal uchun `-100…` ID ishlating.
Kanal sozlanmaguncha videolar navbatda kutib turadi (urinishlar sarflanmaydi).

**`Fayl Telegram limitidan katta`**
Oddiy Bot API 50 MB gacha fayl qabul qiladi. 4 soatlik audio 64 kbps da ham sig'maydi.
Kattaroq fayllar uchun o'zingizning [Local Bot API Server](https://github.com/tdlib/telegram-bot-api) ni
o'rnatib, `TELEGRAM_API_URL` va `UPLOAD_LIMIT_MB=2000` ni sozlashingiz mumkin
(bot va server bir xil fayl tizimini ko'rishi kerak).

**`BOT_TOKEN noto'g'ri (Unauthorized)`**
`.env` dagi tokenni BotFather dan qayta nusxalang (bo'sh joylarsiz).

**`FFmpeg topilmadi`**
Lokal ishga tushirishda: `sudo apt install -y ffmpeg`. Docker image da FFmpeg allaqachon bor.

**Docker Hub `429 Too Many Requests` (build paytida)**
Boshqa mirror dan foydalaning:

```bash
docker compose build --build-arg BASE_IMAGE=mirror.gcr.io/library/python:3.13-slim
```

---

⚡ *Powered by AURIX Downloader*
