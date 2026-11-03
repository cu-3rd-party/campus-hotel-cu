from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

import schemas, campuses
from api.bot import router
from database import get_db
from helpers import _check_bot_secret, _find_profile_by_telegram


@router.post("/api/bot/link", dependencies=[Depends(_check_bot_secret)])
def bot_link(payload: schemas.BotLink, db: Session = Depends(get_db)):
    """/start у бота: запоминаем chat_id, чтобы было куда слать уведомления."""
    if payload.chat_id != payload.telegram_id or payload.chat_id <= 0:
        raise HTTPException(status_code=400, detail="Уведомления подключаются только в личном чате с ботом.")
    profile = _find_profile_by_telegram(db, payload.telegram_id, payload.username)
    if not profile:
        return {"linked": False, "profile": None}

    profile.telegram_chat_id = payload.chat_id
    db.commit()
    db.refresh(profile)
    return {
        "linked": True,
        "profile": {
            "id": profile.id,
            "name": profile.name,
            "group_id": profile.group_id,
            # Готовую подпись отдаём с бэкенда: у бота своего справочника
            # кампус-отелей нет, и заводить второй смысла не имеет.
            "campus": campuses.label(profile.campus),
        },
    }
