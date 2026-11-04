from fastapi import BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

import schemas, telegram_auth, models, notifier
from api.profiles import router
from database import get_db
from helpers import _pack_lists, _feed_msgs, optional_telegram_user, telegram_user
from typing import Optional
from sqlalchemy import text


@router.post("/api/profiles", response_model=schemas.ProfileOut, status_code=201)
def create_profile(
    payload: schemas.ProfileCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: Optional[dict] = Depends(optional_telegram_user),
):
    data = payload.model_dump()
    widget_auth = data.pop("telegram_auth", None)
    init_data = data.pop("telegram_init_data", None)

    data["telegram"] = payload.telegram.lstrip("@").strip()
    data["telegram_id"] = None
    data["telegram_verified"] = False

    # Флаг «подтверждено» ставим только сами, после повторной проверки подписи.
    verified_user = user
    try:
        if widget_auth:
            verified_user = telegram_auth.verify_login_widget(widget_auth)
        elif init_data:
            verified_user = telegram_auth.verify_webapp_init_data(
                init_data
            )
    except telegram_auth.TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))

    if user and verified_user and user["id"] != verified_user["id"]:
        raise HTTPException(status_code=403, detail="Данные входа относятся к разным аккаунтам.")
    if not verified_user:
        # Widget payload is accepted only after signature verification above.
        # With no payload/header, the same fail-closed policy as every mutation.
        telegram_user(None)

    if verified_user:
        # Serialize simultaneous creates for the same identity without changing
        # legacy rows or requiring a destructive unique-index migration.
        if db.bind.dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(:identity)"), {"identity": int(verified_user["id"])})
        if db.query(models.Profile).filter(models.Profile.telegram_id == int(verified_user["id"])).first():
            raise HTTPException(status_code=409, detail="У тебя уже есть анкета. Открой приложение заново, чтобы продолжить.")
        data["telegram_id"] = int(verified_user["id"])
        data["telegram_verified"] = True
        # Ник берём из подтверждённых данных, чтобы нельзя было указать чужой.
        data["telegram"] = str(verified_user.get("username") or "").lstrip("@")

    _pack_lists(data)

    profile = models.Profile(**data)
    db.add(profile)
    db.commit()
    db.refresh(profile)

    # Лента ждать не должна: анкета уже сохранена, анонс уходит фоном.
    background_tasks.add_task(notifier.deliver, _feed_msgs(profile))
    return profile
