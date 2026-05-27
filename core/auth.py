"""
Pinterest OAuth2 Authorization Code Flow с автообновлением токена.
Токен сохраняется в pinterest_token.json и не требует браузера при повторных запусках.
"""
from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

import requests

BASE_URL = "https://api.pinterest.com/v5"
REDIRECT_URI = "https://mentalgrowth.app/"
TOKEN_FILE = Path(__file__).parent.parent / "pinterest_token.json"
SCOPE = "ads:write,pins:write,pins:read"

log = logging.getLogger(__name__)


def _load_token() -> Optional[dict]:
    if TOKEN_FILE.exists():
        return json.loads(TOKEN_FILE.read_text())
    return None


def _save_token(token: dict) -> None:
    TOKEN_FILE.write_text(json.dumps(token, indent=2))
    log.info("Токен сохранён в %s", TOKEN_FILE.name)


def _token_request(client_id: str, client_secret: str, data: dict) -> dict:
    creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    r = requests.post(
        f"{BASE_URL}/oauth/token",
        headers={
            "Authorization": f"Basic {creds}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data=data,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def _first_time_auth(client_id: str, client_secret: str) -> dict:
    import webbrowser

    auth_url = (
        f"https://www.pinterest.com/oauth/"
        f"?client_id={client_id}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={SCOPE}"
    )
    print(f"\nОткрой в браузере для авторизации Pinterest:\n{auth_url}\n")
    webbrowser.open(auth_url)
    redirect_response = input("После авторизации вставь полный redirect URL:\n").strip()

    code_list = parse_qs(urlparse(redirect_response).query).get("code")
    if not code_list:
        raise SystemExit("Не найден параметр 'code' в URL. Авторизация не прошла.")

    data = _token_request(client_id, client_secret, {
        "grant_type": "authorization_code",
        "code": code_list[0],
        "redirect_uri": REDIRECT_URI,
    })
    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_at": time.time() + data.get("expires_in", 2592000) - 300,
    }


def get_access_token(client_id: str, client_secret: str) -> str:
    """Возвращает действующий access_token, обновляя его при необходимости."""
    token = _load_token()

    if token and time.time() < token.get("expires_at", 0):
        mins = (token["expires_at"] - time.time()) / 60
        log.info("Используем сохранённый токен (истекает через %.0f мин)", mins)
        return token["access_token"]

    if token and token.get("refresh_token"):
        log.info("Обновляем Pinterest токен...")
        try:
            data = _token_request(client_id, client_secret, {
                "grant_type": "refresh_token",
                "refresh_token": token["refresh_token"],
                "scope": SCOPE,
            })
            token = {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token", token["refresh_token"]),
                "expires_at": time.time() + data.get("expires_in", 2592000) - 300,
            }
            _save_token(token)
            return token["access_token"]
        except Exception as exc:
            log.warning("Не удалось обновить токен: %s. Пробуем полную авторизацию.", exc)

    log.info("Первый запуск — требуется авторизация через браузер.")
    token = _first_time_auth(client_id, client_secret)
    _save_token(token)
    return token["access_token"]
