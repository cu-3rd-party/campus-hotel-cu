from typing import Optional

from fastapi import BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

import schemas, models, notifier
from api.groups import router
from database import get_db
from helpers import current_profile, _assert_is_me, _get_group_or_404, _get_profile_or_404, _remove_from_group


@router.post("/api/groups/{group_id}/leave", status_code=204)
def leave_group(
    group_id: int,
    payload: schemas.GroupMembership,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    actor: Optional[models.Profile] = Depends(current_profile),
):
    _assert_is_me(actor, payload.profile_id)
    group = _get_group_or_404(db, group_id)
    profile = _get_profile_or_404(db, payload.profile_id)
    if profile.group_id != group.id:
        raise HTTPException(status_code=409, detail="Ты не состоишь в этой комнате")

    # Сообщения собираем до коммита, пока объекты в сессии.
    msgs = _remove_from_group(db, profile)
    db.commit()

    background_tasks.add_task(notifier.deliver, msgs)
    return None
