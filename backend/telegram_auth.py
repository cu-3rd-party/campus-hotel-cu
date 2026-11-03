import asyncio
import hashlib
import hmac
import json
import time
import re
from typing import Optional
from urllib.parse import parse_qsl, urlsplit, urljoin

import httpx

from config import (
    AUTH_MAX_AGE_SECONDS,
    MAX_UPLOAD_BYTES,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_PROXY_URL,
)


class TelegramAuthError(Exception):
    pass


def _data_check_string(payload: dict) -> str:
    return "\n".join(f"{k}={payload[k]}" for k in sorted(payload))


def _matches(data_check_string: str, secret_key: bytes, provided_hash: str) -> bool:
    if not isinstance(provided_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", provided_hash):
        return False
    calculated = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(calculated, provided_hash)


def _check_age(auth_date) -> None:
    if isinstance(auth_date, bool) or not re.fullmatch(r"[0-9]{1,12}", str(auth_date)):
        raise TelegramAuthError("Некорректный auth_date")
    try:
        issued = int(auth_date)
    except (TypeError, ValueError):
        raise TelegramAuthError("Некорректный auth_date")
    age = time.time() - issued
    if age < -60:
        raise TelegramAuthError("Некорректное время входа Telegram, открой приложение заново")
    if age > AUTH_MAX_AGE_SECONDS:
        raise TelegramAuthError("Подпись Telegram устарела, войди заново")


def _check_user(user: dict) -> dict:
    if not isinstance(user, dict) or type(user.get("id")) is not int or not 0 < user["id"] < 2**52:
        raise TelegramAuthError("Некорректные данные пользователя Telegram")
    for field in ("username", "first_name", "last_name", "photo_url"):
        if field in user and (not isinstance(user[field], str) or len(user[field]) > 2048):
            raise TelegramAuthError("Некорректные данные пользователя Telegram")
    if user.get("username") and not re.fullmatch(r"[A-Za-z0-9_]{1,32}", user["username"]):
        raise TelegramAuthError("Некорректный ник пользователя Telegram")
    return user


def verify_login_widget(data: dict) -> dict:
    """Проверка данных Telegram Login Widget.

    Ключ: secret = SHA256(bot_token).
    https://core.telegram.org/widgets/login#checking-authorization
    """
    if not TELEGRAM_BOT_TOKEN:
        raise TelegramAuthError("Вход через Telegram не настроен на сервере")

    if not isinstance(data, dict) or len(str(data)) > 16384:
        raise TelegramAuthError("Некорректные данные входа")
    payload = {k: v for k, v in data.items() if v is not None}
    provided = payload.pop("hash", None)
    if not provided:
        raise TelegramAuthError("Нет подписи (hash)")

    secret_key = hashlib.sha256(TELEGRAM_BOT_TOKEN.encode("utf-8")).digest()
    if not _matches(_data_check_string(payload), secret_key, provided):
        raise TelegramAuthError("Подпись Telegram не совпала")

    _check_age(payload.get("auth_date"))
    return _check_user(payload)


def verify_webapp_init_data(init_data: str) -> dict:
    """Проверка initData из Telegram Mini App (telegram-web-app.js).

    Ключ: secret = HMAC_SHA256(key="WebAppData", msg=bot_token) — отличается
    от схемы Login Widget.
    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    if not TELEGRAM_BOT_TOKEN:
        raise TelegramAuthError("Вход через Telegram не настроен на сервере")

    if not isinstance(init_data, str) or len(init_data) > 16384:
        raise TelegramAuthError("Некорректный initData")

    try:
        values = parse_qsl(init_data, strict_parsing=True, keep_blank_values=True, max_num_fields=32)
        pairs = dict(values)
        if len(values) != len(pairs):
            raise ValueError("duplicate fields")
    except ValueError:
        raise TelegramAuthError("Некорректный initData")

    provided = pairs.pop("hash", None)
    if not provided:
        raise TelegramAuthError("Нет подписи (hash)")

    secret_key = hmac.new(
        b"WebAppData", TELEGRAM_BOT_TOKEN.encode("utf-8"), hashlib.sha256
    ).digest()
    if not _matches(_data_check_string(pairs), secret_key, provided):
        raise TelegramAuthError("Подпись Telegram не совпала")

    _check_age(pairs.get("auth_date"))

    try:
        user = json.loads(pairs.get("user", "{}"))
    except json.JSONDecodeError:
        raise TelegramAuthError("Некорректные данные пользователя")
    if not user:
        raise TelegramAuthError("Telegram не передал данные пользователя")
    return _check_user(user)


async def fetch_profile_photos(
    telegram_id: int, limit: int = 6, offset: int = 0
) -> tuple[list[bytes], int]:
    """Скачивает аватарки пользователя — у многих их несколько.

    Через Bot API: getUserProfilePhotos отдаёт список, каждая аватарка — набор
    размеров; берём самый крупный. Возвращаем сами картинки (вызывающий их
    сохранит) и общее число аватарок, чтобы знать, есть ли что догружать.

    Порциями: тянуть сразу все — долго, особенно через прокси.
    """
    if not TELEGRAM_BOT_TOKEN:
        return [], 0

    api = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    files = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}"
    try:
        async with httpx.AsyncClient(
            timeout=15, follow_redirects=False, proxy=TELEGRAM_PROXY_URL
        ) as client:
            resp = await client.get(
                f"{api}/getUserProfilePhotos",
                params={"user_id": telegram_id, "limit": limit, "offset": offset},
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                return [], 0

            result = data["result"]
            total = int(result.get("total_count", 0))

            async def one(sizes: list) -> Optional[bytes]:
                """Одна аватарка: получаем путь к файлу и скачиваем."""
                if not sizes:
                    return None
                # Размеры отсортированы по возрастанию — берём последний.
                info = await client.get(
                    f"{api}/getFile", params={"file_id": sizes[-1]["file_id"]}
                )
                if info.status_code != 200 or not info.json().get("ok"):
                    return None
                path = info.json()["result"].get("file_path")
                if not path:
                    return None
                async with client.stream("GET", f"{files}/{path}") as blob:
                    if blob.status_code != 200:
                        return None
                    raw = bytearray()
                    async for chunk in blob.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > MAX_UPLOAD_BYTES:
                            return None
                    return bytes(raw)

            # Параллельно: последовательное скачивание заметно медленнее.
            loaded = await asyncio.gather(
                *(one(sizes) for sizes in result.get("photos", [])),
                return_exceptions=True,
            )
            photos = [b for b in loaded if isinstance(b, bytes)]
            return photos, total
    except (httpx.HTTPError, httpx.InvalidURL, KeyError, ValueError):
        # Аватарки — приятное дополнение: не смогли получить, не страшно.
        return [], 0


async def fetch_usernames(telegram_ids: list[int]) -> dict[int, str]:
    """Ники по Telegram ID через getChat.

    Нужно для выгрузки: у части анкет ник пустой или устарел (человек его
    сменил), а связаться с ним по одному числовому ID нельзя.

    Telegram отдаёт данные только про тех, кого бот «видел» — то есть кто
    хоть раз ему написал. На остальных просто не будет ответа: это лучше,
    чем ничего, и ошибкой выгрузку не роняет.
    """
    if not TELEGRAM_BOT_TOKEN or not telegram_ids:
        return {}

    api = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    found: dict[int, str] = {}
    try:
        async with httpx.AsyncClient(timeout=15, proxy=TELEGRAM_PROXY_URL) as client:

            async def one(chat_id: int) -> tuple[int, Optional[str]]:
                try:
                    resp = await client.get(
                        f"{api}/getChat", params={"chat_id": chat_id}
                    )
                    if resp.status_code != 200:
                        return chat_id, None
                    data = resp.json()
                    if not data.get("ok"):
                        return chat_id, None
                    return chat_id, data["result"].get("username")
                except (httpx.HTTPError, KeyError, ValueError):
                    return chat_id, None

            # Bot API ограничивает частоту запросов — идём небольшими пачками.
            for start in range(0, len(telegram_ids), 10):
                chunk = telegram_ids[start : start + 10]
                for chat_id, username in await asyncio.gather(
                    *(one(cid) for cid in chunk)
                ):
                    if username:
                        found[chat_id] = str(username).lstrip("@")
    except (httpx.HTTPError, httpx.InvalidURL):
        return found
    return found


async def download_avatar(url: str) -> Optional[bytes]:
    """Скачивает аватар с CDN Telegram.

    Ссылки t.me/i/userpic/... живут недолго, поэтому картинку сохраняем у себя.
    """
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False, proxy=TELEGRAM_PROXY_URL) as client:
            for _ in range(4):
                target = urlsplit(url)
                host = target.hostname or ""
                allowed = (host == "t.me" and target.path.startswith("/i/userpic/")) or host == "telegram-cdn.org" or bool(re.fullmatch(r"cdn[0-9]+\.telegram-cdn\.org", host))
                if target.scheme != "https" or target.port not in (None, 443) or target.username or target.password or not allowed:
                    return None
                async with client.stream("GET", url) as resp:
                    if resp.is_redirect:
                        url = urljoin(url, resp.headers.get("location", ""))
                        continue
                    resp.raise_for_status()
                    raw = bytearray()
                    async for chunk in resp.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > MAX_UPLOAD_BYTES:
                            return None
                    return bytes(raw)
            return None
    except (httpx.HTTPError, httpx.InvalidURL, ValueError):
        return None
