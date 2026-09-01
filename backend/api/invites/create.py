from typing import Optional

from fastapi import BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from backend import schemas, models, notifier
from backend.api.invites import router
from backend.database import get_db
from backend.helpers import current_profile, _assert_is_me, _get_profile_or_404, _assert_capacity_allowed, _invite_msgs


@router.post("/api/invites", response_model=schemas.GroupInviteOut, status_code=201)
def create_invite(
    payload: schemas.GroupInviteCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    actor: Optional[models.Profile] = Depends(current_profile),
):
    """Позвать человека жить вместе. Комната создастся только после согласия."""
    _assert_is_me(actor, payload.from_profile_id)
    author = _get_profile_or_404(db, payload.from_profile_id)
    target = _get_profile_or_404(db, payload.to_profile_id)

    if author.id == target.id:
        raise HTTPException(status_code=400, detail="Нельзя позвать самого себя")
    if author.gender != target.gender:
        raise HTTPException(
            status_code=403, detail="Парни живут с парнями, девушки — с девушками"
        )
    if author.campus != target.campus:
        raise HTTPException(status_code=403, detail="Вы живёте в разных кампус-отелях")
    _assert_capacity_allowed(author.campus, payload.capacity)
    if author.group_id:
        raise HTTPException(status_code=409, detail="Ты уже состоишь в комнате")
    if target.group_id:
        raise HTTPException(status_code=409, detail="Человек уже в комнате")

    existing = (
        db.query(models.GroupInvite)
        .filter(
            models.GroupInvite.from_profile_id == author.id,
            models.GroupInvite.to_profile_id == target.id,
            models.GroupInvite.status == "pending",
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Приглашение уже отправлено")

    invite = models.GroupInvite(
        from_profile_id=author.id,
        to_profile_id=target.id,
        capacity=payload.capacity,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)

    background_tasks.add_task(notifier.deliver, _invite_msgs(invite))
    return invite
