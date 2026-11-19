from datetime import datetime

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

import profile_review, schemas, telegram_auth
from api.profiles import router
from database import get_db
from models import Profile


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

    profile = db.query(Profile).filter(Profile.telegram_id == int(user["id"])).with_for_update().first()
    if not profile:
        raise HTTPException(status_code=404, detail="Анкета не найдена")

    # Contacts can change; only this account's fresh signed data may refresh them.
    username = user.get("username") or ""
    if profile.telegram != username or not profile.telegram_verified:
        profile.telegram = username
        profile.telegram_verified = True
    profile_review.record_activity(profile, datetime.utcnow())
    db.commit()
    db.refresh(profile)

    return profile
