"""
PinterestFunnelConfig — параметры одной воронки.
Загружается из YAML файла в configs/.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import List
import yaml


@dataclass
class FunnelConfig:
    # Идентификатор воронки
    name: str

    # Pinterest аккаунт
    ad_account_id: str
    order_line_id: str          # ID медиаплана (обязателен для создания кампании)

    # Google Drive
    gdrive_folder_id: str       # ID корневой папки (AUTOVideo / AUTOStatic)

    # Тексты объявления
    campaign_name_template: str  # без даты; дата добавляется автоматически _DDMMYY
    ad_title: str
    ad_description: str
    ad_url: str                  # ссылка на сайт

    # Параметры кампании
    budget_eur: int = 250        # дневной бюджет в евро (на уровне кампании)
    batch_size: int = 10         # сколько креативов заливать за один прогон

    # Таргетинг
    countries: List[str] = field(default_factory=lambda: [
        "US", "AU", "AT", "BE", "BG", "CA", "HR", "CY", "DK", "CZ", "EE", "FI",
        "FR", "DE", "GR", "HU", "IE", "IL", "IT", "LV", "JP", "GB", "CH", "SE",
        "ES", "NL", "LU", "LT", "MT", "NZ", "NO", "KR", "SI", "RS", "SK", "PT",
        "PL", "RO",
    ])

    # Ожидание транскодирования видео
    max_video_wait_sec: int = 300  # максимум секунд ожидания готовности видео


def load_config(name_or_path: str) -> FunnelConfig:
    """
    Загружает конфиг по имени (ищет в configs/) или по полному пути.

    Примеры:
        load_config("mimika_v21")       → configs/mimika_v21.yaml
        load_config("configs/hr.yaml") → по прямому пути
    """
    path = Path(name_or_path)
    if not path.suffix:
        root = Path(__file__).parent.parent
        path = root / "configs" / f"{name_or_path}.yaml"

    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return FunnelConfig(**data)
