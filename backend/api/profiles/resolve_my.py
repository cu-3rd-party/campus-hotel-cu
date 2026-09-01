from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from backend import schemas, telegram_auth
from backend.api.profiles import router
from backend.database import get_db
from backend.helpers import _find_profile_by_telegram


@router.post("/api/profiles/me", response_model=schemas.ProfileOut)
def resolve_my_profile(
    payload: schemas.TelegramWebAppAuth, db: Session = Depends(get_db)
):
    """«Кто я» по подписи Telegram.

    Мини-апп зовёт это при старте: localStorage может быть пуст (другое
    устройство, очистка кэша), а анкета при этом уже есть — раньше в такой
    ситуации предлагалось создать вторую.
    """
    try:
        user = telegram_auth.verify_webapp_init_data(payload.init_data)
    except telegram_auth.TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))

    profile = _find_profile_by_telegram(db, int(user["id"]), user.get("username"))
    if not profile:
        raise HTTPException(status_code=404, detail="Анкета не найдена")

    # Анкету могли создать до входа через Telegram — привязываем id сейчас,
    # чтобы дальше находить её даже при смене ника.
    if not profile.telegram_id:
        profile.telegram_id = int(user["id"])
        db.commit()
        db.refresh(profile)
    return profile
