"""Telegram-бот кампус-отелей «Диск» и «Облако».

Отвечает только за входящие: /start (привязка аккаунта к анкете) и кнопки
«Принять / Отклонить» под заявками. Сами уведомления шлёт бэкенд — так они
не потеряются, если бот перезапускается.

Вся логика заявок живёт в бэкенде: бот ходит в служебные ручки с общим
секретом и ничего не решает сам.
"""

import asyncio
import html
import logging
import os
import re
from contextlib import asynccontextmanager

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message, BotCommand

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")
logging.getLogger("httpx").setLevel(logging.WARNING)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
API_URL = os.getenv("API_URL", "http://backend:8000").rstrip("/")
BOT_SECRET = os.getenv("BOT_SECRET", "").strip()
SITE_URL = os.getenv("SITE_URL", "http://localhost:5173").rstrip("/")
# Прокси до api.telegram.org — нужен там, где Telegram заблокирован.
# Формат: http://user:pass@host:port или socks5://user:pass@host:port.
# Пусто — ходим напрямую.
TELEGRAM_PROXY_URL = os.getenv("TELEGRAM_PROXY_URL", "").strip()

dp = Dispatcher()


def h(value) -> str:
    """Экранирует то, что человек вводил сам, — имена и ники.

    Сообщения размечены HTML: имя вроде «Аня <3» без этого либо теряет кусок
    текста, либо Telegram вовсе отказывается принять сообщение. Бэкенд отдаёт
    такие поля сырыми — разметку тут собираем мы, нам и экранировать.
    """
    return html.escape(str(value or ""))


_api = None


@asynccontextmanager
async def api_client():
    # One pool for the process: repeated callbacks reuse the backend connection.
    if _api is not None:
        yield _api
    else:
        async with httpx.AsyncClient(base_url=API_URL, timeout=10, headers={"X-Bot-Secret": BOT_SECRET}) as client:
            yield client


def search_keyboard():
    if not SITE_URL.startswith("https://"):
        return None
    return {"inline_keyboard": [[{"text": "Открыть поиск соседей", "web_app": {"url": SITE_URL}}]]}


async def require_private_chat(message: Message) -> bool:
    if message.chat.type == "private":
        return True
    await message.answer("Анкета и заявки доступны в личном чате с ботом. Открой его профиль и нажми «Начать».")
    return False


@dp.message(Command("search", "help"))
async def cmd_help(message: Message):
    if not await require_private_chat(message):
        return
    await message.answer(
        "<b>Рядом · Соседи</b>\n\n"
        "Открой поиск, выбери Диск или Облако и расскажи немного о себе. "
        "Сравнивай привычки, знакомься и собирай комнату по взаимному согласию.\n\n"
        "/pending — заявки, которые ждут твоего решения\n"
        "/start — проверить привязку анкеты и уведомления",
        reply_markup=search_keyboard(),
    )


@dp.message(Command("start"))
async def cmd_start(message: Message):
    if not await require_private_chat(message):
        return
    user = message.from_user
    async with api_client() as client:
        try:
            resp = await client.post(
                "/api/bot/link",
                json={
                    "telegram_id": user.id,
                    "chat_id": message.chat.id,
                    "username": user.username,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            log.warning("link failed: %s", type(exc).__name__)
            await message.answer("Сайт сейчас недоступен, попробуй позже.")
            return

    if not data.get("linked"):
        # Раньше здесь просили вручную вписать ник в анкету: бот искал её
        # только по нику. Теперь мини-апп подтверждает человека подписью
        # Telegram и подставляет ник с фото сам — просить больше нечего.
        await message.answer(
            "Привет! Это <b>Рядом · Соседи</b> для Диска и Облака.\n\n"
            "Не нашёл твою анкету. Открой приложение кнопкой снизу — рядом с "
            "полем ввода — и заполни анкету: имя, фото и ник подтянутся из "
            "Telegram сами.\n\n"
            "После сохранения анкеты отправь /start ещё раз — подключим личные уведомления.",
            reply_markup=search_keyboard(),
        )
        return

    profile = data["profile"]
    campus = {"disk": "Диск", "cloud": "Облако"}.get(profile.get("campus"))
    where = f" Ты в кампус-отеле <b>{campus}</b>." if campus else ""
    await message.answer(
        f"✅ Привет, {h(profile['name'])}! Уведомления включены.{where}\n\n"
        "Буду писать, когда кто-то попросится к тебе в комнату, когда твою "
        "заявку рассмотрят, когда сосед выйдет из комнаты и когда в ней "
        "изменят число мест.\n\n"
        "/pending — заявки, ждущие твоего решения",
        reply_markup=search_keyboard(),
    )


@dp.message(Command("pending"))
async def cmd_pending(message: Message):
    if not await require_private_chat(message):
        return
    async with api_client() as client:
        try:
            resp = await client.get(
                "/api/bot/pending", params={"telegram_id": message.from_user.id}
            )
            resp.raise_for_status()
            items = resp.json()["requests"]
        except httpx.HTTPError:
            await message.answer("Сайт сейчас недоступен, попробуй позже.")
            return

    if not items:
        await message.answer("Заявок, ждущих твоего решения, нет 👌")
        return

    for item in items:
        await message.answer(
            f"🔔 <b>{h(item['who'])}</b> просится в комнату на {item['capacity']}.\n"
            + (f"@{h(item['telegram'])}" if item.get('telegram') else "Публичный ник не указан."),
            reply_markup={
                "inline_keyboard": [
                    [
                        {
                            "text": "✅ Принять",
                            "callback_data": f"vote:{item['id']}:yes",
                        },
                        {
                            "text": "✖️ Отклонить",
                            "callback_data": f"vote:{item['id']}:no",
                        },
                    ]
                ]
            },
        )


def decision_tail(kind, data):
    status = data["status"]
    if kind == "invite":
        return f"Комната на {data['capacity']} создана. Можно знакомиться!" if status == "accepted" else "Приглашение отклонено."
    if kind == "block":
        if status == "approved": return "Блок собран — все согласились."
        if status == "rejected": return "Объединение в блок отклонено."
    else:
        if status == "approved": return f"{h(data['who'])} принят(а) — все согласились."
        if status == "rejected": return f"Заявка {h(data['who'])} отклонена."
    return f"Твой голос учтён: {data['votes_done']} из {data['votes_needed']}. Ждём остальных."


async def apply_decision(call, kind):
    match = re.fullmatch(rf"{kind}:(\d+):(yes|no)", call.data or "")
    if not match:
        await call.answer("Эта кнопка устарела. Открой /pending.", show_alert=True)
        return
    # Stop Telegram's spinner before waiting for the API, rather than 10s later.
    await call.answer("Проверяем и сохраняем ответ…")
    item_id, decision = match.groups()
    payload = {"telegram_id": call.from_user.id,
               "invite_id" if kind == "invite" else "request_id": int(item_id),
               "accept" if kind == "invite" else "approve": decision == "yes"}
    try:
        async with api_client() as client:
            response = await client.post(f"/api/bot/{kind}", json=payload)
        data = response.json()
    except (httpx.HTTPError, ValueError):
        if call.message:
            await call.message.answer("Сервер отвечает дольше обычного. Открой /pending или приложение, чтобы проверить результат перед повтором.", reply_markup=search_keyboard())
        return
    if response.status_code != 200:
        detail = data.get("detail", "Не получилось сохранить ответ. Открой /pending.")
        if not isinstance(detail, str): detail = "Не получилось сохранить ответ. Открой /pending."
        if call.message:
            if response.status_code == 409:
                try: await call.message.edit_reply_markup(reply_markup=None)
                except TelegramBadRequest: pass
            await call.message.answer(h(detail))
        return
    if call.message:
        try:
            await call.message.edit_text(f"{call.message.html_text}\n\n{decision_tail(kind, data)}", reply_markup=None)
        except TelegramBadRequest:
            await call.message.answer(decision_tail(kind, data), reply_markup=search_keyboard())


@dp.callback_query(F.data.startswith("invite:"))
async def on_invite(call: CallbackQuery):
    await apply_decision(call, "invite")


@dp.callback_query(F.data.startswith("block:"))
async def on_block(call: CallbackQuery):
    await apply_decision(call, "block")


@dp.callback_query(F.data.startswith("vote:"))
async def on_vote(call: CallbackQuery):
    await apply_decision(call, "vote")


async def main():
    global _api
    if not TOKEN:
        raise SystemExit("Нет TELEGRAM_BOT_TOKEN — боту нечего делать")
    if not BOT_SECRET:
        raise SystemExit("Нет BOT_SECRET — бэкенд не пустит бота в служебные ручки")

    # Сообщения размечены HTML-тегами — задаём parse_mode по умолчанию.
    # Прокси (если задан) заворачивает все запросы к Telegram, включая polling.
    session = AiohttpSession(proxy=TELEGRAM_PROXY_URL) if TELEGRAM_PROXY_URL else None
    if TELEGRAM_PROXY_URL:
        log.info("Хожу в Telegram через прокси")
    bot = Bot(
        token=TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    # На всякий случай снимаем вебхук: мы работаем на long polling.
    await bot.delete_webhook(drop_pending_updates=False)
    log.info("Бот запущен, слушаю обновления")
    await bot.set_my_commands([
        BotCommand(command="search", description="Открыть поиск соседей"),
        BotCommand(command="pending", description="Заявки, ожидающие решения"),
        BotCommand(command="start", description="Анкета и уведомления"),
        BotCommand(command="help", description="Как найти соседей"),
    ])
    async with httpx.AsyncClient(base_url=API_URL, timeout=httpx.Timeout(10, connect=3),
                                 headers={"X-Bot-Secret": BOT_SECRET},
                                 limits=httpx.Limits(max_connections=20, max_keepalive_connections=10)) as client:
        _api = client
        try:
            await dp.start_polling(bot)
        finally:
            _api = None
            await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
