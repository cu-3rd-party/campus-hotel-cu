from typing import Optional

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from backend import schemas, models
from backend.api.groups import router
from backend.database import get_db
from backend.helpers import current_profile, _assert_is_me, _get_profile_or_404, _assert_capacity_allowed


@router.post("/api/groups", response_model=schemas.GroupOut, status_code=201)
def create_group(
    payload: schemas.GroupCreate,
    db: Session = Depends(get_db),
    actor: Optional[models.Profile] = Depends(current_profile),
):
    """Создаёт комнату: автор сразу становится первым жильцом."""
    _assert_is_me(actor, payload.profile_id)
    profile = _get_profile_or_404(db, payload.profile_id)
    if profile.group_id:
        raise HTTPException(status_code=409, detail="Ты уже состоишь в комнате")
    _assert_capacity_allowed(profile.campus, payload.capacity)

    group = models.Group(
        capacity=payload.capacity, gender=profile.gender, campus=profile.campus
    )
    db.add(group)
    db.flush()  # нужен id до привязки участника
    profile.group_id = group.id
    db.commit()
    db.refresh(group)
    return group
