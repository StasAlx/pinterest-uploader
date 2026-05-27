"""
Pinterest Ads API v5: создание кампании, ad group, pin, ad.

Ключевые исправления относительно старых скриптов:
- targeting_spec: используем 'location' вместо 'GEO', 'age_bucket' вместо 'AGE_BUCKET'
- убран is_performance_plus (не поддерживается API v5)
- статус кампании и ad group: PAUSED (включается вручную)
- ожидание транскодирования видео через GET /media/{media_id}
"""
from __future__ import annotations

import base64
import logging
import mimetypes
import time
from pathlib import Path
from typing import Optional, Tuple

import requests

from .config import FunnelConfig

BASE_URL = "https://api.pinterest.com/v5"
log = logging.getLogger(__name__)


# ── Хелперы ───────────────────────────────────────────────────────────────────

def _headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }


def _extract_id(resp_data: dict) -> str:
    """Извлекает ID из ответа Pinterest API (формат: {items: [{data: {id: ...}}]})."""
    items = resp_data.get("items", [resp_data])
    if not isinstance(items, list):
        items = [items]
    for item in items:
        exc = item.get("exceptions")
        if exc:
            raise RuntimeError(f"Pinterest API error: {exc}")
        data = item.get("data", item)
        for key in ("id", "campaign_id", "ad_group_id", "pin_id", "ad_id"):
            if data.get(key):
                return str(data[key])
    raise RuntimeError(f"Не удалось извлечь ID из ответа: {resp_data}")


def _post(access_token: str, url: str, payload: list, label: str) -> str:
    """POST запрос с логированием. Возвращает ID созданного объекта."""
    r = requests.post(url, headers=_headers(access_token), json=payload, timeout=30)
    if not r.ok:
        log.error("[%s] Ответ API: %s %s", label, r.status_code, r.text)
        r.raise_for_status()
    return _extract_id(r.json())


# ── Кампания ──────────────────────────────────────────────────────────────────

def create_campaign(access_token: str, cfg: FunnelConfig, name: str, start_time: int) -> str:
    """Создаёт кампанию WEB_CONVERSION с CBO бюджетом €budget_eur/день."""
    payload = [{
        "ad_account_id": cfg.ad_account_id,
        "name": name,
        "status": "PAUSED",
        "objective_type": "WEB_CONVERSION",
        "daily_spend_cap": cfg.budget_eur * 1_000_000,   # микровалюта (1 EUR = 1_000_000)
        "is_flexible_daily_budgets": True,
        "start_time": start_time,
        "order_line_id": cfg.order_line_id,
    }]
    campaign_id = _post(
        access_token,
        f"{BASE_URL}/ad_accounts/{cfg.ad_account_id}/campaigns",
        payload,
        label="create_campaign",
    )
    log.info("Кампания создана: %s (ID: %s)", name, campaign_id)
    return campaign_id


# ── Ad Group ──────────────────────────────────────────────────────────────────

def create_ad_group(access_token: str, cfg: FunnelConfig, campaign_id: str, name: str) -> str:
    """
    Создаёт Ad Group с оптимизацией на CHECKOUT.
    ВАЖНО: 'location' вместо устаревшего 'GEO' в targeting_spec.
    """
    payload = [{
        "ad_account_id": cfg.ad_account_id,
        "campaign_id": campaign_id,
        "name": name,
        "status": "PAUSED",
        "billable_event": "IMPRESSION",
        "bid_strategy_type": "AUTOMATIC_BID",
        "optimization_goal_metadata": {
            "conversion_tag_v3_goal_metadata": {
                "conversion_event": "CHECKOUT",
            }
        },
        "targeting_spec": {
            "location": cfg.countries,
        },
    }]
    ag_id = _post(
        access_token,
        f"{BASE_URL}/ad_accounts/{cfg.ad_account_id}/ad_groups",
        payload,
        label="create_ad_group",
    )
    log.info("Ad Group создан: %s (ID: %s)", name, ag_id)
    return ag_id


# ── Video Pin ─────────────────────────────────────────────────────────────────

def _wait_for_media_ready(access_token: str, media_id: str, max_wait_sec: int) -> None:
    """Ждёт завершения транскодирования видео через GET /media/{media_id}."""
    poll_interval = 10
    elapsed = 0
    while elapsed < max_wait_sec:
        time.sleep(poll_interval)
        elapsed += poll_interval
        try:
            r = requests.get(
                f"{BASE_URL}/media/{media_id}",
                headers=_headers(access_token),
                timeout=15,
            )
            if r.ok:
                status = r.json().get("status", "")
                if status == "succeeded":
                    log.info("Видео готово (elapsed: %ds)", elapsed)
                    return
                if status == "failed":
                    raise RuntimeError(f"Транскодирование видео завершилось ошибкой: media_id={media_id}")
                log.debug("Видео обрабатывается (status=%s, elapsed=%ds)...", status, elapsed)
        except RuntimeError:
            raise
        except Exception as exc:
            log.warning("Ошибка при проверке статуса видео: %s", exc)
    log.warning("Таймаут ожидания транскодирования (%ds) для media_id=%s", max_wait_sec, media_id)


def _upload_video_pin(
    access_token: str,
    cfg: FunnelConfig,
    local_path: Path,
) -> Tuple[str, str]:
    """Загружает видео на Pinterest и создаёт Pin. Возвращает (pin_id, creative_type)."""
    # Шаг 1: Инициализация загрузки
    r = requests.post(
        f"{BASE_URL}/media",
        headers=_headers(access_token),
        json={"media_type": "video"},
        timeout=30,
    )
    if not r.ok:
        log.error("Media init failed: %s %s", r.status_code, r.text)
        r.raise_for_status()
    media_info = r.json()
    media_id = media_info["media_id"]
    upload_url = media_info["upload_url"]
    upload_fields = media_info["upload_parameters"]
    log.info("Media init OK: media_id=%s", media_id)

    # Шаг 2: Загрузка файла на S3
    with open(local_path, "rb") as f:
        upload_r = requests.post(
            upload_url,
            data=upload_fields,
            files={"file": (local_path.name, f)},
            timeout=300,
        )
    if not upload_r.ok:
        log.error("S3 upload failed: %s %s", upload_r.status_code, upload_r.text)
        upload_r.raise_for_status()
    log.info("Видео загружено на S3: %s", local_path.name)

    # Шаг 3: Ожидание транскодирования
    _wait_for_media_ready(access_token, media_id, cfg.max_video_wait_sec)

    # Шаг 4: Создание Pin
    pin_payload = {
        "media_source": {
            "source_type": "video_id",
            "media_id": media_id,
            "cover_image_key_frame_time": 1,
        },
        "title": cfg.ad_title,
        "description": cfg.ad_description,
        "link": cfg.ad_url,
        "creative_type": "VIDEO",
    }
    for attempt in range(3):
        pin_r = requests.post(
            f"{BASE_URL}/pins",
            headers=_headers(access_token),
            json=pin_payload,
            timeout=30,
        )
        if pin_r.ok:
            pin_id = pin_r.json()["id"]
            log.info("Video pin создан: %s", pin_id)
            return pin_id, "VIDEO"
        log.warning("Pin create failed (attempt %d/3): %s %s", attempt + 1, pin_r.status_code, pin_r.text)
        time.sleep(30)

    raise RuntimeError(f"Не удалось создать video pin для {local_path.name} после 3 попыток")


# ── Image Pin ─────────────────────────────────────────────────────────────────

def _upload_image_pin(
    access_token: str,
    cfg: FunnelConfig,
    local_path: Path,
) -> Tuple[str, str]:
    """Загружает изображение и создаёт Pin через base64. Возвращает (pin_id, creative_type)."""
    mime, _ = mimetypes.guess_type(str(local_path))
    with open(local_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")

    pin_payload = {
        "media_source": {
            "source_type": "image_base64",
            "content_type": mime or "image/jpeg",
            "data": img_b64,
        },
        "title": cfg.ad_title,
        "description": cfg.ad_description,
        "link": cfg.ad_url,
        "creative_type": "REGULAR",
    }
    r = requests.post(
        f"{BASE_URL}/pins",
        headers=_headers(access_token),
        json=pin_payload,
        timeout=60,
    )
    if not r.ok:
        log.error("Image pin failed: %s %s", r.status_code, r.text)
        r.raise_for_status()
    pin_id = r.json()["id"]
    log.info("Image pin создан: %s", pin_id)
    return pin_id, "REGULAR"


# ── Ad ────────────────────────────────────────────────────────────────────────

def _create_ad(
    access_token: str,
    cfg: FunnelConfig,
    campaign_id: str,
    ad_group_id: str,
    pin_id: str,
    creative_type: str,
    ad_name: str,
) -> str:
    """Создаёт объявление (promoted pin). Повторяет при ошибке 2945 (видео не готово)."""
    payload = [{
        "ad_account_id": cfg.ad_account_id,
        "campaign_id": campaign_id,
        "ad_group_id": ad_group_id,
        "creative_type": creative_type,
        "pin_id": pin_id,
        "name": ad_name,
        "status": "PAUSED",
    }]
    for attempt in range(3):
        r = requests.post(
            f"{BASE_URL}/ad_accounts/{cfg.ad_account_id}/ads",
            headers=_headers(access_token),
            json=payload,
            timeout=30,
        )
        resp = r.json() if r.ok or r.status_code < 500 else {}

        # Проверяем error 2945 (pin ещё не готов к продвижению)
        items = resp.get("items", [])
        if items:
            exc = items[0].get("exceptions")
            if exc and exc.get("code") == 2945:
                log.warning("Pin не готов (2945), ждём 30с... (попытка %d/3)", attempt + 1)
                time.sleep(30)
                continue

        if not r.ok:
            log.error("Ad create failed: %s %s", r.status_code, r.text)
            r.raise_for_status()

        ad_id = _extract_id(resp)
        log.info("Ad создан: %s (ID: %s)", ad_name, ad_id)
        return ad_id

    raise RuntimeError(f"Не удалось создать ad для pin {pin_id} после 3 попыток")


# ── Основная функция ──────────────────────────────────────────────────────────

def upload_and_create_ad(
    access_token: str,
    cfg: FunnelConfig,
    campaign_id: str,
    ad_group_id: str,
    local_path: Path,
    ad_name: str,
) -> Tuple[str, str]:
    """
    Загружает файл как Pin и создаёт объявление.
    Возвращает (pin_id, ad_id).
    """
    is_video = local_path.suffix.lower() in (".mp4", ".mov")
    if is_video:
        pin_id, creative_type = _upload_video_pin(access_token, cfg, local_path)
    else:
        pin_id, creative_type = _upload_image_pin(access_token, cfg, local_path)

    ad_id = _create_ad(
        access_token, cfg, campaign_id, ad_group_id, pin_id, creative_type, ad_name
    )
    return pin_id, ad_id
