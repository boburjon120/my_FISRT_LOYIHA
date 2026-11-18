# NetGuard ML Analytics

Tarmoq trafigini tasniflash va anomaliyalarni klasterlash uchun web-ilova. Tarmoq ulanishlari "Xavfsiz" yoki "Shubhali" sinfga ajratiladi va guruhlanadi.

Ilova tashqi kutubxonalarsiz yozilgan: ML va grafik kutubxonalari (scikit-learn, Chart.js, D3 va boshqalar) ishlatilmagan. Hammasi sof HTML5, CSS3 va Vanilla JavaScript.

## Ishga tushirish

Uchala faylni bitta papkada saqlang va `index.html` ni brauzerda oching. Server yoki o'rnatish kerak emas.

## Fayllar

| Fayl | Vazifasi |
|------|----------|
| `index.html` | Sahifa tuzilmasi: yon panel, 5 ta bo'lim, ikonkalar (inline SVG) |
| `style.css` | Dizayn tizimi: ranglar, tipografiya, kartochkalar, jadvallar, moslashuvchan grid |
| `script.js` | Algoritmlar, umumiy holat (state), Canvas grafiklar va SVG daraxt |

## Bo'limlar

1. **Dashboard.** Uchala algoritmning natijalari, klasterlar grafigi va ma'lumotlar jadvali.
2. **Ma'lumotlar bazasi.** Yozuv qo'shish va o'chirish, boshlang'ich 20 talik bazani tiklash, min/max chegaralari. Baza o'zgarsa, hamma narsa avtomatik qayta hisoblanadi.
3. **KNN (k = 3).** Normalizatsiya sonlar bilan, barcha masofalarning ochiq formulasi, saralash, 3 ta qo'shni va ovoz berish.
4. **Decision Tree (max_depth = 2).** SVG daraxt sxemasi, har bir tugun uchun Gini hisobi, nomzod chegaralar jadvali va qaror hududlari grafigi.
5. **K-means (q = 3).** Iteratsiyalar bosqichma-bosqich bajariladi. Har bir iteratsiya logida masofalar, yangi markazlar va J hisobi bor. Grafikda klaster nurlari va J dinamikasi ko'rsatiladi.

## Algoritmlar

- **Normalizatsiya.** Min-Max formulasi: `z = (x − min) / (max − min)`. Agar barcha qiymatlar teng bo'lsa, `z = 0`.
- **KNN.** Evklid masofasi: `d = √(Σ(z₁ − z₂)²)`. Bashorat `ŷ = arg max N_c`, ya'ni eng ko'p ovoz olgan sinf.
- **Decision Tree.** Gini indeksi `G = 1 − Σp²`. Ajratish sifati vaznli Gini bilan baholanadi: `G_ajratish = (n_L/n)·G_L + (n_R/n)·G_R`.
- **K-means.** Markaz klaster a'zolarining o'rtachasi: `μ = (1/|C|)·Σz`. Xatolik `J = ΣΣ‖z − μ‖²`. Biriktirishlar o'zgarmay qolsa, jarayon to'xtaydi. Eng ko'pi 100 iteratsiya.

## Holat (state)

Barcha bo'limlar bitta umumiy holatdan foydalanadi. Holat `localStorage` ga uchta kalit bilan saqlanadi:

- `dataset`
- `newPoint`
- `kmeansState`

Ilova bir nechta brauzer oynasida ochiq bo'lsa, oynalar bir-biri bilan sinxronlanadi.

## Klaviatura

- `1`–`5`: bo'limlar o'rtasida o'tish.
- `N`: K-means'ning keyingi qadami.
