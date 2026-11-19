"""Отправка уведомлений в Telegram.

Сообщения шлёт сам бэкенд через Bot API — отдельный процесс бота нужен только
для входящих (/start и кнопки). Так уведомление не теряется, если бот перезапущен.
"""

import logging
from typing import List, Optional, Union

import httpx

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PROXY_URL

log = logging.getLogger(__name__)
# Bot API tokens are part of request URLs. Do not let HTTPX info logs record them.
logging.getLogger("httpx").setLevel(logging.WARNING)

API = "https://api.telegram.org/bot{token}/{method}"


async def deliver(messages: List[dict]) -> None:
    """Отправляет пачку сообщений. Запускается в фоне (BackgroundTasks), уже
    после того как ответ ушёл клиенту — поэтому сетевые задержки Telegram не
    тормозят действия на сайте. Каждое сообщение — dict с chat_id/text/markup.
    """
    for msg in messages:
        await send_message(
            msg["chat_id"],
            msg["text"],
            msg.get("reply_markup"),
            msg.get("message_thread_id"),
        )


async def send_message(
    chat_id: Union[int, str],  # личка — id, общая лента — id или @ник группы
    text: str,
    reply_markup: Optional[dict] = None,
    message_thread_id: Optional[int] = None,
) -> bool:
    """Шлёт сообщение. Никогда не роняет вызывающий код.

    Уведомление — не критичная часть: если бот не настроен или человек не нажал
    /start, действие на сайте всё равно должно пройти.
    """
    resp = await _post_message(chat_id, text, reply_markup, message_thread_id)
    if resp is None:
        return False
    if resp.status_code != 200:
        log.warning("Telegram не принял сообщение: HTTP %s", resp.status_code)
        return False
    return True


async def _post_message(chat_id, text, reply_markup=None, message_thread_id=None):
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        return None
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    # Тема супергруппы. Без него сообщение уходит в «General», а не туда,
    # где его ждут.
    if message_thread_id:
        payload["message_thread_id"] = message_thread_id

    try:
        async with httpx.AsyncClient(timeout=10, proxy=TELEGRAM_PROXY_URL) as client:
            return await client.post(
                API.format(token=TELEGRAM_BOT_TOKEN, method="sendMessage"),
                json=payload,
            )
    except httpx.HTTPError as exc:
        log.warning("Не смог отправить в Telegram: %s", type(exc).__name__)
        return None


async def send_profile_review(telegram_id: int, token: str) -> tuple[str, int]:
    response = await _post_message(
        telegram_id,
        "Ты всё ещё планируешь жить в Диске и ищешь соседей?\n\n"
        "Мы скрыли твою анкету из поиска до подтверждения. Нажми «Да, ещё ищу», "
        "чтобы вернуть её. Если не ответишь за 48 часов, мы удалим анкету.",
        {"inline_keyboard": [
            [{"text": "Да, ещё ищу", "callback_data": f"review:{token}:keep"}],
            [{"text": "Не буду жить в Диске", "callback_data": f"review:{token}:leaving"}],
            [{"text": "Больше не ищу", "callback_data": f"review:{token}:done"}],
        ]},
    )
    if response is None:
        return "failed", 0
    try:
        result = response.json()
    except ValueError:
        result = {}
    if not isinstance(result, dict):
        result = {}
    if response.status_code == 200 and result.get("ok") is True:
        return "sent", 0
    if response.status_code == 403 and result.get("description") == "Forbidden: bot was blocked by the user":
        return "blocked", 0
    if response.status_code == 429:
        parameters = result.get("parameters")
        retry_after = parameters.get("retry_after") if isinstance(parameters, dict) else None
        return "failed", max(1, retry_after) if isinstance(retry_after, int) else 60
    return "failed", 0


class DocumentError(Exception):
    """Файл не ушёл в Telegram — в отличие от уведомлений, об этом надо сказать.

    Человек нажал «выгрузить» и ждёт файл: молча проглотить ошибку нельзя,
    иначе он будет искать в чате то, чего там нет.
    """


async def send_document(
    chat_id: int, filename: str, content: bytes, caption: str = ""
) -> None:
    """Отправляет файл в личку. Бросает DocumentError, если не получилось."""
    if not TELEGRAM_BOT_TOKEN:
        raise DocumentError("Бот не настроен на сервере")
    if not chat_id:
        raise DocumentError("Неизвестно, в какой чат отправлять")

    try:
        async with httpx.AsyncClient(timeout=60, proxy=TELEGRAM_PROXY_URL) as client:
            resp = await client.post(
                API.format(token=TELEGRAM_BOT_TOKEN, method="sendDocument"),
                data={"chat_id": str(chat_id), "caption": caption[:1024]},
                files={"document": (filename, content)},
            )
    except httpx.HTTPError as exc:
        log.warning("Не смог отправить файл в Telegram: %s", type(exc).__name__)
        raise DocumentError("Telegram не отвечает, попробуй ещё раз")

    if resp.status_code != 200:
        # Причину не угадываем — в мини-апп заходят из чата с ботом, так что
        # обычное «нажми /start» тут ни при чём. Подробности пишем в лог.
        log.warning("Telegram не принял файл: HTTP %s", resp.status_code)
        raise DocumentError("Telegram не принял файл, попробуй ещё раз")


def invite_keyboard(invite_id: int) -> dict:
    """Кнопки под приглашением «давай жить вместе»."""
    return {
        "inline_keyboard": [
            [
                {"text": "🤝 Согласен", "callback_data": f"invite:{invite_id}:yes"},
                {"text": "✖️ Отказаться", "callback_data": f"invite:{invite_id}:no"},
            ]
        ]
    }


def vote_keyboard(request_id: int) -> dict:
    """Кнопки «Принять / Отклонить» под заявкой."""
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Принять", "callback_data": f"vote:{request_id}:yes"},
                {"text": "✖️ Отклонить", "callback_data": f"vote:{request_id}:no"},
            ]
        ]
    }
