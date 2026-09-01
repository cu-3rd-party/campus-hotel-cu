from typing import List, Optional

from fastapi import Depends, Query
from sqlalchemy.orm import Session

import schemas, models, config
from api.profiles import router
from database import get_db
from helpers import telegram_user, current_profile, _ideal_match, IDEAL_WILDCARD, IDEAL_FIELDS


@router.get(
    "/api/profiles/ideal",
    response_model=List[schemas.ProfileOut],
    dependencies=[Depends(telegram_user)],
)
def list_ideal_profiles(
    db: Session = Depends(get_db),
    me: Optional[models.Profile] = Depends(current_profile),
    profile_id: Optional[int] = Query(
        None, description="Только для локальной разработки, без токена бота"
    ),
):
    """Те, у кого совпали все мои бытовые параметры.

    Без анкеты сравнивать не с чем, как и в случае, когда я ничего о себе не
    указал — тогда «идеальным» оказался бы каждый, и подсказка теряет смысл.
    Пустой ответ фронт понимает как «кнопку показывать не надо».
    """
    # На проде «кто я» решает подпись Telegram. Без токена бота подписи нет
    # вовсе (локальная разработка) — только там верим параметру из адреса,
    # иначе им можно было бы спрашивать за других.
    if me is None and profile_id and not config.TELEGRAM_BOT_TOKEN:
        me = db.query(models.Profile).filter(models.Profile.id == profile_id).first()
    if me is None:
        return []
    if not any(
        getattr(me, f) and getattr(me, f) != IDEAL_WILDCARD for f in IDEAL_FIELDS
    ):
        return []

    # Ищем только среди тех, к кому вообще можно проситься: свой отель, свой
    # пол, ещё не в комнате.
    candidates = (
        db.query(models.Profile)
        .filter(
            models.Profile.id != me.id,
            models.Profile.gender == me.gender,
            models.Profile.campus == me.campus,
            models.Profile.group_id.is_(None),
        )
        .order_by(models.Profile.created_at.desc())
        .all()
    )
    return [p for p in candidates if _ideal_match(me, p)]
