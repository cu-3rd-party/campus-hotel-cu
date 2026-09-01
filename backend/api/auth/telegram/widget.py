from fastapi import HTTPException

import schemas, telegram_auth
from api.auth.telegram import router
from helpers import _telegram_profile


@router.post("/api/auth/telegram", response_model=schemas.TelegramProfileOut)
async def auth_telegram(payload: schemas.TelegramWidgetAuth):
    """Вход через Telegram Login Widget (обычный веб)."""
    try:
        user = telegram_auth.verify_login_widget(payload.model_dump())
    except telegram_auth.TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    return await _telegram_profile(user)
