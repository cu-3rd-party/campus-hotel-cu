from fastapi import HTTPException

from backend import schemas, telegram_auth
from backend.api.auth.telegram import router
from backend.helpers import _telegram_profile


@router.post("/api/auth/telegram", response_model=schemas.TelegramProfileOut)
async def auth_telegram(payload: schemas.TelegramWidgetAuth):
    """Вход через Telegram Login Widget (обычный веб)."""
    try:
        user = telegram_auth.verify_login_widget(payload.model_dump())
    except telegram_auth.TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    return await _telegram_profile(user)
