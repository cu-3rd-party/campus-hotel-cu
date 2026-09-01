from typing import Optional

from fastapi import BackgroundTasks, Depends
from sqlalchemy.orm import Session

import models, notifier
from api.profiles import router
from database import get_db
from helpers import current_profile, _assert_is_me, _get_profile_or_404, _remove_from_group, _close_pending


@router.delete("/api/profiles/{profile_id}", status_code=204)
def delete_profile(
    profile_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    actor: Optional[models.Profile] = Depends(current_profile),
):
    """Удаление своей анкеты: заодно выводим из комнаты и чистим заявки."""
    _assert_is_me(actor, profile_id)
    profile = _get_profile_or_404(db, profile_id)

    # Сообщения собираем ДО удаления, пока объекты ещё в сессии.
    msgs = _remove_from_group(
        db, profile, note="удалил(а) анкету и вышел(а) из комнаты"
    )
    _close_pending(db, profile)

    db.delete(profile)
    db.commit()

    background_tasks.add_task(notifier.deliver, msgs)
    return None
