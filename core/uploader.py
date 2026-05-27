"""
Основной цикл: загрузка списка креативов → Google Drive → Pinterest.

Логика работы:
1. Читает список файлов из creatives/{funnel}.txt
2. Фильтрует уже загруженные (через state/{funnel}/uploaded.json)
3. Берёт первые batch_size файлов
4. Ищет файлы на Google Drive рекурсивно
5. Скачивает во временную папку
6. Создаёт кампанию + Ad Group
7. Для каждого файла: загружает Pin → создаёт Ad → сохраняет в state
8. Удаляет временные файлы
"""
from __future__ import annotations

import json
import logging
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

from .api import create_ad_group, create_campaign, upload_and_create_ad
from .auth import get_access_token
from .config import FunnelConfig, load_config
from .gdrive import download_file, find_files_by_names, init_gdrive

log = logging.getLogger(__name__)

# ── Пути ─────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).parent.parent


def _creatives_file(funnel_name: str) -> Path:
    return ROOT / "creatives" / f"{funnel_name}.txt"


def _state_file(funnel_name: str) -> Path:
    state_dir = ROOT / "state" / funnel_name
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "uploaded.json"


# ── State ─────────────────────────────────────────────────────────────────────

def _load_state(state_path: Path) -> Dict[str, dict]:
    """Возвращает {filename: {pin_id, ad_id, campaign_id, ...}}."""
    if state_path.exists():
        return json.loads(state_path.read_text(encoding="utf-8"))
    return {}


def _save_state(state_path: Path, state: Dict[str, dict]) -> None:
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Список креативов ──────────────────────────────────────────────────────────

def _load_creatives_list(funnel_name: str) -> List[str]:
    """
    Читает список имён файлов из creatives/{funnel}.txt.
    Игнорирует пустые строки и комментарии (#).
    """
    path = _creatives_file(funnel_name)
    if not path.exists():
        raise FileNotFoundError(
            f"Файл со списком креативов не найден: {path}\n"
            f"Создайте файл creatives/{funnel_name}.txt с именами файлов (по одному на строку)."
        )
    lines = path.read_text(encoding="utf-8").splitlines()
    return [
        line.strip()
        for line in lines
        if line.strip() and not line.strip().startswith("#")
    ]


# ── Имена кампании/группы ─────────────────────────────────────────────────────

def _build_names(cfg: FunnelConfig) -> tuple[str, str]:
    """Возвращает (campaign_name, ad_group_name) с датой DDMMYY."""
    date_str = datetime.now().strftime("%d%m%y")
    campaign_name = f"{cfg.campaign_name_template}_{date_str}"
    ad_group_name = f"{cfg.campaign_name_template}_AG_{date_str}"
    return campaign_name, ad_group_name


# ── Основная функция ──────────────────────────────────────────────────────────

def run_upload(
    funnel_name_or_path: str,
    client_id: str,
    client_secret: str,
    client_secrets_json: str = "client_secrets.json",
    limit: Optional[int] = None,
) -> None:
    """
    Основной цикл загрузки для одной воронки.

    Args:
        funnel_name_or_path: Имя конфига (mimika_v21) или путь к yaml.
        client_id: Pinterest client_id (из .env).
        client_secret: Pinterest client_secret (из .env).
        client_secrets_json: Путь к Google OAuth client_secrets.json.
        limit: Переопределить batch_size (для тестов).
    """
    cfg = load_config(funnel_name_or_path)
    batch_size = limit if limit is not None else cfg.batch_size

    log.info("=== Pinterest Uploader: %s ===", cfg.name)
    log.info("Batch size: %d", batch_size)

    # 1. Список всех креативов
    all_creatives = _load_creatives_list(cfg.name)
    log.info("Всего в списке: %d файлов", len(all_creatives))

    # 2. Фильтрация уже загруженных
    state_path = _state_file(cfg.name)
    state = _load_state(state_path)
    uploaded_names: Set[str] = set(state.keys())

    pending = [name for name in all_creatives if name not in uploaded_names]
    log.info("Уже загружено: %d, ожидают загрузки: %d", len(uploaded_names), len(pending))

    if not pending:
        log.info("Все креативы уже загружены. Нечего делать.")
        return

    # 3. Берём первые batch_size файлов
    batch = pending[:batch_size]
    log.info("Текущий батч (%d файлов): %s", len(batch), ", ".join(batch))

    # 4. Pinterest auth
    access_token = get_access_token(client_id, client_secret)

    # 5. Ищем файлы на Google Drive
    log.info("Поиск файлов на Google Drive...")
    drive = init_gdrive(client_secrets_json)
    found_files = find_files_by_names(drive, cfg.gdrive_folder_id, set(batch))

    if not found_files:
        log.error("Не найдено ни одного файла из батча на Google Drive.")
        return

    missing = set(batch) - set(found_files.keys())
    if missing:
        log.warning("Не найдены на Drive (%d): %s", len(missing), ", ".join(sorted(missing)))

    files_to_upload = [name for name in batch if name in found_files]
    log.info("Будет загружено: %d файлов", len(files_to_upload))

    if not files_to_upload:
        log.error("Нет файлов для загрузки.")
        return

    # 6. Создаём кампанию и Ad Group
    campaign_name, ad_group_name = _build_names(cfg)
    start_time = int(datetime.now().timestamp())  # начало прямо сейчас (кампания PAUSED)

    log.info("Создаём кампанию: %s", campaign_name)
    campaign_id = create_campaign(access_token, cfg, campaign_name, start_time)

    log.info("Создаём Ad Group: %s", ad_group_name)
    ad_group_id = create_ad_group(access_token, cfg, campaign_id, ad_group_name)

    # 7. Скачивание + загрузка в Pinterest
    temp_dir = Path(tempfile.mkdtemp(prefix="pinterest_uploader_"))
    log.info("Временная папка: %s", temp_dir)

    try:
        for filename in files_to_upload:
            log.info("--- Обрабатываем: %s ---", filename)
            drive_file = found_files[filename]
            local_path = temp_dir / filename

            # Скачиваем
            try:
                download_file(drive_file, local_path)
            except Exception as exc:
                log.error("Ошибка скачивания %s: %s — пропускаем", filename, exc)
                continue

            # Загружаем в Pinterest
            ad_name = Path(filename).stem  # имя без расширения
            try:
                pin_id, ad_id = upload_and_create_ad(
                    access_token=access_token,
                    cfg=cfg,
                    campaign_id=campaign_id,
                    ad_group_id=ad_group_id,
                    local_path=local_path,
                    ad_name=ad_name,
                )
            except Exception as exc:
                log.error("Ошибка загрузки %s: %s — пропускаем", filename, exc)
                # Удаляем временный файл
                local_path.unlink(missing_ok=True)
                continue

            # Сохраняем в state
            state[filename] = {
                "pin_id": pin_id,
                "ad_id": ad_id,
                "campaign_id": campaign_id,
                "ad_group_id": ad_group_id,
                "campaign_name": campaign_name,
                "uploaded_at": datetime.now().isoformat(),
            }
            _save_state(state_path, state)
            log.info("Сохранено в state: %s → pin=%s, ad=%s", filename, pin_id, ad_id)

            # Удаляем временный файл
            local_path.unlink(missing_ok=True)

    finally:
        # Удаляем временную папку
        shutil.rmtree(temp_dir, ignore_errors=True)
        log.info("Временная папка удалена: %s", temp_dir)

    # Итог
    uploaded_now = [name for name in files_to_upload if name in state and "uploaded_at" in state.get(name, {})]
    log.info(
        "=== Готово: загружено %d/%d файлов. Кампания: %s (ID: %s) ===",
        len(uploaded_now), len(files_to_upload), campaign_name, campaign_id,
    )
