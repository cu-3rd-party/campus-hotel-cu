from typing import Optional

from fastapi import BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from backend import schemas, models, notifier
from backend.api.invites import router
from backend.database import get_db
from backend.helpers import current_profile, _assert_is_me, _get_invite_or_404, _assert_invite_still_valid, \
    _accept_invite, _decline_invite


@router.post("/api/invites/{invite_id}/respond", response_model=schemas.GroupInviteOut)
def respond_invite(
    invite_id: int,
    payload: schemas.GroupInviteRespond,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    actor: Optional[models.Profile] = Depends(current_profile),
):
    _assert_is_me(actor, payload.profile_id)
    invite = _get_invite_or_404(db, invite_id)
    if invite.status != "pending":
        raise HTTPException(status_code=409, detail="Приглашение уже закрыто")
    if invite.to_profile_id != payload.profile_id:
        raise HTTPException(status_code=403, detail="Это приглашение не тебе")

    if payload.accept:
        _assert_invite_still_valid(invite)
        _group, msgs = _accept_invite(db, invite)
    else:
        msgs = _decline_invite(db, invite)

    background_tasks.add_task(notifier.deliver, msgs)
    db.refresh(invite)
    return invite
