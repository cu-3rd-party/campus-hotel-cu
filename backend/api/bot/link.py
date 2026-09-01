from fastapi import Depends
from sqlalchemy.orm import Session

from backend import schemas, campuses
from backend.api.bot import router
from backend.database import get_db
from backend.helpers import _check_bot_secret, _find_profile_by_telegram


@router.post("/api/bot/link", dependencies=[Depends(_check_bot_secret)])
def bot_link(payload: schemas.BotLink, db: Session = Depends(get_db)):
    """/start у бота: запоминаем chat_id, чтобы было куда слать уведомления."""
    profile = _find_profile_by_telegram(db, payload.telegram_id, payload.username)
    if not profile:
        return {"linked": False, "profile": None}

    profile.telegram_chat_id = payload.chat_id
    if not profile.telegram_id:
        profile.telegram_id = payload.telegram_id
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
