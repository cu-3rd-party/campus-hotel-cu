from fastapi import HTTPException

from backend import schemas, telegram_auth
from backend.api.auth.telegram import router
from backend.helpers import _telegram_profile


@router.post("/api/auth/telegram/webapp", response_model=schemas.TelegramProfileOut)
async def auth_telegram_webapp(payload: schemas.TelegramWebAppAuth):
    """Вход из Telegram Mini App (сайт открыт внутри Telegram)."""
    try:
        user = telegram_auth.verify_webapp_init_data(payload.init_data)
    except telegram_auth.TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    return await _telegram_profile(user)
