from typing import Optional

from fastapi import BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from backend import schemas, models, campuses, join_flow, notifier
from backend.api.groups import router
from backend.database import get_db
from backend.helpers import current_profile, _assert_is_me, _get_group_or_404, _get_profile_or_404, _request_msgs, \
    _request_out


@router.post(
    "/api/groups/{group_id}/requests",
    response_model=schemas.JoinRequestOut,
    status_code=201,
)
def create_join_request(
    group_id: int,
    payload: schemas.JoinRequestCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    actor: Optional[models.Profile] = Depends(current_profile),
):
    """Заявка на вступление. Сама по себе в комнату не пускает."""
    _assert_is_me(actor, payload.profile_id)
    group = _get_group_or_404(db, group_id)
    profile = _get_profile_or_404(db, payload.profile_id)

    if profile.group_id == group.id:
        raise HTTPException(status_code=409, detail="Ты уже в этой комнате")
    if profile.group_id:
        raise HTTPException(status_code=409, detail="Сначала выйди из текущей комнаты")
    if profile.gender != group.gender:
        raise HTTPException(
            status_code=403, detail="Парни живут с парнями, девушки — с девушками"
        )
    if profile.campus != group.campus:
        raise HTTPException(
            status_code=403,
            detail=f"Эта комната в кампус-отеле «{campuses.label(group.campus)}»",
        )
    if group.spots_left <= 0:
        raise HTTPException(status_code=409, detail="В комнате больше нет мест")

    existing = (
        db.query(models.JoinRequest)
        .filter(
            models.JoinRequest.group_id == group.id,
            models.JoinRequest.profile_id == profile.id,
            models.JoinRequest.status == join_flow.PENDING,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Заявка уже отправлена")

    req = models.JoinRequest(group_id=group.id, profile_id=profile.id)
    db.add(req)
    db.commit()
    db.refresh(req)

    background_tasks.add_task(notifier.deliver, _request_msgs(req))
    return _request_out(req)
