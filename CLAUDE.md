# Pinterest Uploader

Скрипт для массового создания рекламных кампаний в **Pinterest Ads** (API v5).

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
python run.py mimika_v21 --dry-run        # проверить без загрузки
```

**Первый запуск Pinterest**: откроется браузер для OAuth2-авторизации. Далее токен обновляется автоматически (`pinterest_token.json`).

**Первый запуск Google Drive**: откроется браузер для OAuth2-авторизации. Токен кэшируется в `gdrive_credentials.json`.

---

## Как работает

1. Читает список имён файлов из `creatives/{funnel}.txt`
2. Из state-файла (`state/{funnel}/uploaded.json`) фильтрует уже загруженные
3. Берёт первые `batch_size` (по умолчанию 10) файлов
4. Находит файлы на Google Drive рекурсивным поиском по имени
5. Скачивает во временную папку
6. Создаёт новую кампанию Pinterest (PAUSED, €budget/день, WEB_CONVERSION)
7. Создаёт Ad Group (CHECKOUT, AUTO BID, геотаргетинг из конфига)
8. Для каждого файла: загружает Pin → создаёт Ad → сохраняет в state
9. Удаляет временные файлы

---

## Структура проекта

```
pinterest-uploader/
├── run.py              ← точка входа
├── requirements.txt
├── .env.example        ← шаблон credentials
├── .env                ← реальные credentials (не в git)
├── client_secrets.json ← Google OAuth (не в git)
├── pinterest_token.json← Pinterest OAuth токен (не в git, создаётся автоматически)
├── configs/            ← один yaml = одна воронка
│   └── mimika_v21.yaml
├── creatives/          ← списки файлов для каждой воронки
│   └── mimika_v21.txt  ← имена файлов (по одному на строку)
├── state/              ← локальные данные (не в git)
│   └── {funnel}/
│       ├── uploaded.json   ← {filename: {pin_id, ad_id, campaign_id, ...}}
│       └── last_run.log    ← лог последнего запуска
└── core/
    ├── config.py       ← FunnelConfig + загрузчик yaml
    ├── auth.py         ← Pinterest OAuth2 с авто-обновлением токена
    ├── gdrive.py       ← Google Drive: рекурсивный поиск, скачивание
    ├── api.py          ← Pinterest API v5: campaign, ad_group, pin, ad
    └── uploader.py     ← главный цикл загрузки
```

---

## Добавить новую воронку

```bash
cp configs/mimika_v21.yaml configs/new_funnel.yaml
# Заменить: name, ad_account_id, order_line_id, gdrive_folder_id,
#           campaign_name_template, ad_title, ad_description, ad_url

# Создать список креативов:
touch creatives/new_funnel.txt
# Добавить имена файлов (одно на строку)

python run.py new_funnel --dry-run  # проверить конфиг
python run.py new_funnel            # запустить
```

---

## Конфиг воронки (YAML)

| Поле | Описание |
|------|----------|
| `name` | Идентификатор воронки (совпадает с именем yaml) |
| `ad_account_id` | ID рекламного аккаунта Pinterest |
| `order_line_id` | ID медиаплана (обязателен для API) |
| `gdrive_folder_id` | ID корневой папки на Google Drive |
| `campaign_name_template` | Шаблон: дата `_DDMMYY` добавляется автоматически |
| `ad_title` | Заголовок объявления |
| `ad_description` | Описание объявления |
| `ad_url` | URL лендинга |
| `budget_eur` | Дневной бюджет в евро (CBO, уровень кампании), по умолчанию 250 |
| `batch_size` | Файлов за один прогон, по умолчанию 10 |
| `max_video_wait_sec` | Таймаут ожидания транскодирования видео (сек), по умолчанию 300 |

---

## Pinterest API v5 — важные детали

- `targeting_spec`: используется `location` (не `GEO`), `age_bucket` (не `AGE_BUCKET`)
- `is_performance_plus`: **не поддерживается** в v5, не использовать
- `daily_spend_cap`: в микровалюте (€1 = 1 000 000)
- `order_line_id`: обязателен при создании кампании
- Видео: POST `/media` → S3 upload → poll GET `/media/{media_id}` → POST `/pins`
- Ошибка **2945**: pin не готов к продвижению — скрипт автоматически ретраит 3 раза с паузой 30с

---

## Форматы файлов

Скрипт автоматически определяет тип по расширению:
- `.mp4`, `.mov` → Video Pin (`creative_type: VIDEO`)
- Всё остальное → Image Pin (`creative_type: REGULAR`, загрузка через base64)

---

## State-файлы

`state/{funnel}/uploaded.json` — словарь `{filename: {...}}`. При повторном запуске уже загруженные файлы пропускаются. Для перезагрузки файла — удалить его запись из JSON.

---

## Аккаунты

| Аккаунт | Приложение |
|---------|-----------|
| `549765419738` | Mimika |
| `549766762721` | Youth |
