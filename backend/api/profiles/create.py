from fastapi import BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

import schemas, telegram_auth, models, notifier
from api.profiles import router
from database import get_db
from helpers import _pack_lists, _feed_msgs


@router.post("/api/profiles", response_model=schemas.ProfileOut, status_code=201)
def create_profile(
    payload: schemas.ProfileCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    data = payload.model_dump()
    widget_auth = data.pop("telegram_auth", None)
    init_data = data.pop("telegram_init_data", None)

    data["telegram"] = payload.telegram.lstrip("@").strip()
    data["telegram_id"] = None
    data["telegram_verified"] = False

    # Флаг «подтверждено» ставим только сами, после повторной проверки подписи.
    verified_user = None
    try:
        if widget_auth:
            verified_user = telegram_auth.verify_login_widget(widget_auth)
        elif init_data:
            verified_user = telegram_auth.verify_webrouter_init_data(
                init_data
            )  # TODO: это откуда тут
    except telegram_auth.TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))

    if verified_user:
        data["telegram_id"] = int(verified_user["id"])
        data["telegram_verified"] = True
        # Ник берём из подтверждённых данных, чтобы нельзя было указать чужой.
        if verified_user.get("username"):
            data["telegram"] = str(verified_user["username"]).lstrip("@")

    _pack_lists(data)

    profile = models.Profile(**data)
    db.add(profile)
    db.commit()
    db.refresh(profile)

    # Лента ждать не должна: анкета уже сохранена, анонс уходит фоном.
    background_tasks.add_task(notifier.deliver, _feed_msgs(profile))
    return profile
