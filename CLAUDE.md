# Pinterest Uploader

Скрипт для массового создания **Pinterest Performance+** кампаний и загрузки креативов.

Владелец: Stas Alekseenko (stasalex@gmail.com)

---

## Быстрый старт

```bash
cd pinterest-uploader
pip install -r requirements.txt
cp .env.example .env         # вставить PINTEREST_CLIENT_ID и PINTEREST_CLIENT_SECRET
# положить client_secrets.json (Google OAuth) в корень папки

python run.py mimika_v21                  # загрузить 10 креативов
python run.py mimika_v21 --limit 3        # загрузить 3 (для теста)
python run.py mimika_v21 --dry-run        # проверить список без загрузки
```

**Первый запуск Pinterest**: откроется браузер для OAuth2-авторизации. Далее токен обновляется автоматически (`pinterest_token.json`).

**Первый запуск Google Drive**: откроется браузер для OAuth2-авторизации. Токен кэшируется в `gdrive_credentials.json`.

---

## Как работает

1. Читает базовые имена из `creatives/{funnel}.txt` (без расширения и маркера формата)
2. Из `state/{funnel}/uploaded.json` фильтрует уже загруженные
3. Берёт первые `batch_size` (по умолчанию 10) файлов
4. Ищет файлы на Drive по папке-префиксу: `CRTV-154-1_MIDEF_ED` → папка `CRTV-154` → файл `CRTV-154-1_9x16_MIDEF_ED.mp4`
5. Загружает только 9x16 или файлы без маркера формата (4x5, 1x1 — пропускаются)
6. Скачивает во временную папку, удаляет файл сразу после загрузки
7. Создаёт Performance+ кампанию (PAUSED, €budget/день, WEB_CONVERSION, start = ближайшая полночь)
8. Создаёт Ad Group (ACTIVE — PP не разрешает PAUSED, CHECKOUT, AUTO BID, geo+language из конфига)
9. Для каждого файла: добавляет UTM → загружает Pin на доску → создаёт Ad (ACTIVE) → сохраняет в state

---

## Структура проекта

```
pinterest-uploader/
├── run.py                  ← точка входа (CLI)
├── requirements.txt
├── .env.example            ← шаблон credentials
├── .env                    ← реальные credentials (не в git)
├── client_secrets.json     ← Google OAuth (не в git)
├── gdrive_credentials.json ← Drive токен (не в git, создаётся автоматически)
├── pinterest_token.json    ← Pinterest OAuth токен (не в git, создаётся автоматически)
├── configs/                ← один yaml = одна воронка
│   └── mimika_v21.yaml
├── creatives/              ← списки базовых имён файлов
│   └── mimika_v21.txt      ← одно базовое имя на строку (без расширения и формата)
├── state/                  ← локальные данные (не в git)
│   └── {funnel}/
│       ├── uploaded.json   ← {basename: {pin_id, ad_id, campaign_id, ...}}
│       └── last_run.log    ← лог последнего запуска
└── core/
    ├── config.py           ← FunnelConfig + загрузчик yaml
    ├── auth.py             ← Pinterest OAuth2 с авто-обновлением
    ├── gdrive.py           ← Drive: умный поиск по папке-префиксу, скачивание
    ├── api.py              ← Pinterest API v5: campaign, ad_group, pin, ad
    └── uploader.py         ← главный цикл загрузки
```

---

## Формат creatives/*.txt

Базовые имена без расширения и без маркера формата. Скрипт сам найдёт нужный файл на Drive:

```
CRTV-154-1_MIDEF_ED      # найдёт CRTV-154-1_9x16_MIDEF_ED.mp4
CRTS-489-5_MIDEF_ED      # найдёт CRTS-489-5_9x16_MIDEF_ED.png
CRTV-617-11              # найдёт CRTV-617-11.mp4 (без маркера формата)
# строки с # и пустые — игнорируются
```

Загружаются: `9x16` и файлы без маркера. Пропускаются: `4x5`, `1x1`, `16x9`.

---

## Конфиг воронки (YAML)

| Поле | Описание |
|------|----------|
| `name` | Идентификатор воронки (совпадает с именем yaml) |
| `ad_account_id` | ID рекламного аккаунта Pinterest |
| `order_line_id` | ID медиаплана (обязателен для API v5) |
| `board_id` | ID доски для пинов (обязателен — без него 404) |
| `gdrive_folder_id` | ID корневой папки на Google Drive (содержит AUTOVideo/AUTOStatic) |
| `campaign_name_template` | Шаблон имени — дата `_DDMMYY` добавляется автоматически |
| `ad_title` | Заголовок пина |
| `ad_description` | Описание пина |
| `ad_url` | Базовый URL (UTM добавляются автоматически) |
| `budget_eur` | Дневной бюджет в евро (CBO, уровень кампании), по умолчанию 250 |
| `batch_size` | Файлов за один прогон, по умолчанию 10 |
| `is_performance_plus` | Performance+ кампания (по умолчанию True) |
| `countries` | Список стран ISO (по умолчанию Tier1: US, GB, CA, AU, NZ, IE) |
| `language` | Язык таргетинга (по умолчанию `["en"]`) |
| `max_video_wait_sec` | Таймаут транскодирования видео, по умолчанию 300 |

---

## Добавить новую воронку

```bash
cp configs/mimika_v21.yaml configs/new_funnel.yaml
# Заменить: name, ad_account_id, order_line_id, board_id, gdrive_folder_id,
#           campaign_name_template, ad_title, ad_description, ad_url

touch creatives/new_funnel.txt
# Добавить базовые имена файлов (одно на строку)

python run.py new_funnel --dry-run  # проверить
python run.py new_funnel            # запустить
```

---

## Pinterest API v5 — важные детали

- `targeting_spec`: `location` (не `GEO`), `locale` для языка
- **`is_performance_plus: true`** — поддерживается, включает Performance+
- Performance+ **не поддерживает `age_bucket`** (ошибка 3151) — алгоритм сам оптимизирует аудиторию
- Performance+ ad group **не может быть в статусе PAUSED** (ошибка 4073) — создаём ACTIVE
- `daily_spend_cap` в микровалюте: €1 = 1 000 000
- `order_line_id` обязателен при создании кампании
- `board_id` обязателен при создании пина — без него 404
- OAuth scope: `ads:write,pins:write,pins:read,boards:read,boards:write`
- Видео: POST `/media` → S3 upload → poll GET `/media/{media_id}` → POST `/pins`
- Ошибка **2945**: pin не готов к продвижению → ретрай 3×30с

### Статусы объектов

| Объект | Статус | Почему |
|--------|--------|--------|
| Кампания | PAUSED | Включается вручную после проверки |
| Ad Group | ACTIVE | PP не разрешает PAUSED |
| Объявление | ACTIVE | Кампания PAUSED — реального показа нет |

---

## UTM-метки

Добавляются автоматически к каждому объявлению:

```
utm_source=pinterest&utm_medium=paid_social
&utm_campaign={campaign_name}
&utm_content={creative_basename}
```

---

## Поиск на Google Drive

Быстрый (~15 сек на батч из 10 файлов):
- `CRTV-154-1_MIDEF_ED` → ищем папку `CRTV-154` в AUTOVideo
- `CRTS-489-5_MIDEF_ED` → ищем папку `CRTS-489` в AUTOStatic
- Учитывает суффикс `UPLOADED` (`CRTV-154 UPLOADED`)
- ~12 API-запросов вместо 1724 (рекурсивный обход всех папок)

---

## Аккаунты

| Аккаунт | Приложение |
|---------|-----------|
| `549765419738` | Mimika |
| `549766762721` | Youth |

Доска для пинов Mimika: `993114224018984197` (Пины только для рекламы, PROTECTED)
