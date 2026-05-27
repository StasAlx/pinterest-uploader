"""
Google Drive: поиск файлов по имени и скачивание.
Структура папок: gdrive_folder_id → AUTOVideo/AUTOStatic → CRTV-xxx → файлы

Поиск по базовому имени (без расширения и маркера формата):
    'CRTV-154-1_MIDEF_ED'  →  найдёт 'CRTV-154-1_9x16_MIDEF_ED.mp4'
    'CRTV-617-11'          →  найдёт 'CRTV-617-11.mp4' (без маркера)

Фильтр форматов: загружаются только 9x16 или файлы без маркера формата.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, Optional, Set

from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive

MIME_FOLDER = "application/vnd.google-apps.folder"
log = logging.getLogger(__name__)

# Маркер формата в имени файла: 9x16, 4x5, 1x1 и т.д.
_FORMAT_RE = re.compile(r"\d+x\d+", re.IGNORECASE)


# ── Хелперы по имени файла ────────────────────────────────────────────────────

def file_basename(title: str) -> str:
    """
    Возвращает базовое имя файла: без расширения и маркера формата.
    'CRTV-154-1_9x16_MIDEF_ED.mp4' → 'CRTV-154-1_MIDEF_ED'
    'CRTV-617-11.mp4'               → 'CRTV-617-11'
    """
    stem = Path(title).stem                     # убираем расширение
    cleaned = _FORMAT_RE.sub("", stem)          # убираем маркер формата
    cleaned = re.sub(r"_+", "_", cleaned)       # схлопываем двойные подчёркивания
    return cleaned.strip("_")


def file_format(title: str) -> Optional[str]:
    """
    Возвращает маркер формата в нижнем регистре, или None.
    'CRTV-154-1_9x16_MIDEF_ED.mp4' → '9x16'
    'CRTS-489-5_4x5_MIDEF_ED.jpg'  → '4x5'
    'CRTV-617-11.mp4'              → None
    """
    stem = Path(title).stem
    m = _FORMAT_RE.search(stem)
    return m.group(0).lower() if m else None


def is_uploadable(title: str) -> bool:
    """
    Возвращает True, если файл подходит для загрузки:
    - маркер формата 9x16 (вертикальное видео/фото)
    - OR маркер формата отсутствует
    """
    fmt = file_format(title)
    return fmt is None or fmt == "9x16"


# ── Google Drive init ─────────────────────────────────────────────────────────

def init_gdrive(client_secrets_path: str = "client_secrets.json") -> GoogleDrive:
    """Инициализирует Google Drive с OAuth2. При первом запуске откроется браузер."""
    gauth = GoogleAuth()
    gauth.settings["client_config_file"] = client_secrets_path
    gauth.settings["save_credentials"] = True
    gauth.settings["save_credentials_backend"] = "file"
    gauth.settings["save_credentials_file"] = str(
        Path(client_secrets_path).parent / "gdrive_credentials.json"
    )
    gauth.LocalWebserverAuth()
    return GoogleDrive(gauth)


# ── Поиск по базовому имени (основной) ───────────────────────────────────────

def find_files_by_basenames(
    drive: GoogleDrive,
    root_folder_id: str,
    basenames: Set[str],
) -> Dict[str, object]:
    """
    Рекурсивно ищет файлы по базовому имени (без расширения и маркера формата).
    Загружаемые форматы: 9x16 или без маркера.

    Возвращает {basename: drive_file_object}.
    Ключ — базовое имя из txt-списка; значение — объект файла Drive.
    """
    result: Dict[str, object] = {}
    _search_by_basename(drive, root_folder_id, set(basenames), result)
    missing = basenames - set(result.keys())
    if missing:
        log.warning("Не найдено на Google Drive: %s", ", ".join(sorted(missing)))
    return result


def _search_by_basename(
    drive: GoogleDrive,
    folder_id: str,
    targets: Set[str],
    result: Dict[str, object],
) -> None:
    """Рекурсивный обход папок; заполняет result по мере нахождения файлов."""
    if not targets:
        return

    try:
        items = drive.ListFile(
            {"q": f"'{folder_id}' in parents and trashed=false"}
        ).GetList()
    except Exception as exc:
        log.error("Ошибка при листинге папки %s: %s", folder_id, exc)
        return

    subfolders = []
    for item in items:
        if item["mimeType"] == MIME_FOLDER:
            subfolders.append(item["id"])
            continue

        # Проверяем формат (только 9x16 или без маркера)
        if not is_uploadable(item["title"]):
            log.debug("Пропускаем (не тот формат): %s", item["title"])
            continue

        bn = file_basename(item["title"])
        if bn in targets and bn not in result:
            result[bn] = item
            log.debug("Найден: %s (basename=%s)", item["title"], bn)

    # Обходим подпапки только для тех basename, что ещё не найдены
    remaining = targets - set(result.keys())
    for subfolder_id in subfolders:
        if not remaining:
            break
        _search_by_basename(drive, subfolder_id, remaining, result)
        remaining = targets - set(result.keys())


# ── Скачивание ────────────────────────────────────────────────────────────────

def download_file(drive_file, dest_path: Path) -> None:
    """Скачивает файл с Google Drive в dest_path."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    drive_file.GetContentFile(str(dest_path))
    size_kb = dest_path.stat().st_size // 1024
    log.info("Скачан: %s (%d KB)", dest_path.name, size_kb)
