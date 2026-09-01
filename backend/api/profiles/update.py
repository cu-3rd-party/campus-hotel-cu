from typing import Optional, List

from fastapi import BackgroundTasks, Depends
from sqlalchemy.orm import Session

import schemas, models, notifier
from api.profiles import router
from database import get_db
from helpers import current_profile, _assert_is_me, _get_profile_or_404, _remove_from_group, _close_pending, \
    _pack_lists


@router.put("/api/profiles/{profile_id}", response_model=schemas.ProfileOut)
def update_profile(
    profile_id: int,
    payload: schemas.ProfileUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    actor: Optional[models.Profile] = Depends(current_profile),
):
    """Редактирование своей анкеты.

    Полноценной авторизации нет: правит тот, у кого в браузере сохранён id.
    Подтверждённый через Telegram ник менять нельзя — иначе подтверждение
    потеряет смысл.

    Кампус-отель и пол сменить можно, но и то и другое — переезд: в чужом отеле
    и в чужой по полу ленте комната, заявки и приглашения теряют смысл, поэтому
    они закрываются. Пол спрашивают на входе, ещё до анкеты, и промахиваются —
    без этой возможности исправить ошибку было негде.
    """
    _assert_is_me(actor, profile_id)
    profile = _get_profile_or_404(db, profile_id)
    data = payload.model_dump()

    if profile.telegram_verified:
        data.pop("telegram", None)
    else:
        data["telegram"] = payload.telegram.lstrip("@").strip()

    msgs: List[dict] = []
    if data["campus"] != profile.campus:
        msgs = _remove_from_group(
            db, profile, note="переехал(а) в другой кампус-отель и вышел(а) из комнаты"
        )
        _close_pending(db, profile)
    elif data["gender"] != profile.gender:
        # Комнаты и блоки однополые: сменил пол — прежние соседи больше не
        # соседи. Отдельной веткой, чтобы не выводить из комнаты дважды.
        msgs = _remove_from_group(
            db, profile, note="изменил(а) пол в анкете и вышел(а) из комнаты"
        )
        _close_pending(db, profile)

    _pack_lists(data)

    for key, value in data.items():
        setattr(profile, key, value)
    db.commit()
    db.refresh(profile)

    background_tasks.add_task(notifier.deliver, msgs)
    return profile
