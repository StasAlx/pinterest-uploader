"""
Google Drive: поиск файлов по имени и скачивание.
Структура папок: gdrive_folder_id → AUTOVideo/AUTOStatic → CRTV-xxx → файлы
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, Optional, Set

from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive

MIME_FOLDER = "application/vnd.google-apps.folder"
log = logging.getLogger(__name__)


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


def find_files_by_names(drive: GoogleDrive, root_folder_id: str, filenames: Set[str]) -> Dict[str, object]:
    """
    Рекурсивно ищет файлы по именам в дереве папок.
    Возвращает {имя_файла: drive_file_object}.
    """
    result: Dict[str, object] = {}
    _search_recursive(drive, root_folder_id, set(filenames), result)
    missing = filenames - set(result.keys())
    if missing:
        log.warning("Не найдено на Google Drive: %s", ", ".join(sorted(missing)))
    return result


def _search_recursive(drive: GoogleDrive, folder_id: str, targets: Set[str], result: Dict) -> None:
    """Обходит папки рекурсивно, заполняет result по мере нахождения файлов."""
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
        if item["title"] in targets and item["mimeType"] != MIME_FOLDER:
            result[item["title"]] = item
            targets = targets - {item["title"]}
            log.debug("Найден: %s", item["title"])
        elif item["mimeType"] == MIME_FOLDER:
            subfolders.append(item["id"])

    for subfolder_id in subfolders:
        if not targets:
            break
        _search_recursive(drive, subfolder_id, targets, result)


def download_file(drive_file, dest_path: Path) -> None:
    """Скачивает файл с Google Drive по dest_path."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    drive_file.GetContentFile(str(dest_path))
    size_kb = dest_path.stat().st_size // 1024
    log.info("Скачан: %s (%d KB)", dest_path.name, size_kb)
