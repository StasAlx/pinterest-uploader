"""
Точка входа Pinterest Uploader.

Использование:
    python run.py mimika_v21
    python run.py mimika_v21 --limit 3      # загрузить только 3 файла (тест)
    python run.py youth_v1 --dry-run        # проверить конфиг без загрузки
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Загружаем .env из папки проекта
load_dotenv(Path(__file__).parent / ".env")

from core.config import load_config
from core.uploader import run_upload


def _setup_logging(funnel_name: str) -> None:
    """Настраивает логирование в файл и консоль."""
    log_dir = Path(__file__).parent / "state" / funnel_name
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "last_run.log"

    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%H:%M:%S"

    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_path, mode="w", encoding="utf-8"),
    ]
    logging.basicConfig(level=logging.INFO, format=fmt, datefmt=datefmt, handlers=handlers)
    logging.info("Лог: %s", log_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Pinterest Ads Uploader")
    parser.add_argument("funnel", help="Имя воронки (напр. mimika_v21) или путь к YAML-конфигу")
    parser.add_argument("--limit", type=int, default=None, help="Загрузить не более N файлов (по умолчанию: batch_size из конфига)")
    parser.add_argument("--dry-run", action="store_true", help="Проверить конфиг и список файлов без загрузки")
    args = parser.parse_args()

    _setup_logging(args.funnel)

    # Проверяем env-переменные
    client_id = os.getenv("PINTEREST_CLIENT_ID")
    client_secret = os.getenv("PINTEREST_CLIENT_SECRET")
    if not client_id or not client_secret:
        logging.error(
            "Не найдены PINTEREST_CLIENT_ID / PINTEREST_CLIENT_SECRET в .env. "
            "Скопируйте .env.example в .env и заполните credentials."
        )
        sys.exit(1)

    client_secrets_json = os.getenv(
        "GOOGLE_CLIENT_SECRETS",
        str(Path(__file__).parent / "client_secrets.json"),
    )

    if args.dry_run:
        logging.info("=== DRY RUN ===")
        cfg = load_config(args.funnel)
        logging.info("Конфиг загружен: %s", cfg.name)
        logging.info("Ad account: %s", cfg.ad_account_id)
        logging.info("GDrive folder: %s", cfg.gdrive_folder_id)
        logging.info("Бюджет: €%d/день", cfg.budget_eur)
        logging.info("Batch size: %d", args.limit or cfg.batch_size)

        from core.uploader import _load_creatives_list, _load_state, _state_file
        creatives = _load_creatives_list(cfg.name)
        state = _load_state(_state_file(cfg.name))
        pending = [c for c in creatives if c not in state]
        logging.info("Всего в списке: %d, загружено: %d, ожидают: %d", len(creatives), len(state), len(pending))
        batch = pending[:args.limit or cfg.batch_size]
        logging.info("Следующий батч: %s", ", ".join(batch) if batch else "(нет файлов)")
        return

    run_upload(
        funnel_name_or_path=args.funnel,
        client_id=client_id,
        client_secret=client_secret,
        client_secrets_json=client_secrets_json,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
