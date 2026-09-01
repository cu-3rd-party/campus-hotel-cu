from datetime import datetime
from typing import Optional

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from backend import schemas, models
from backend.api.invites import router
from backend.database import get_db
from backend.helpers import current_profile, _assert_is_me, _get_invite_or_404


@router.post("/api/invites/{invite_id}/cancel", status_code=204)
def cancel_invite(
    invite_id: int,
    payload: schemas.GroupMembership,
    db: Session = Depends(get_db),
    actor: Optional[models.Profile] = Depends(current_profile),
):
    _assert_is_me(actor, payload.profile_id)
    invite = _get_invite_or_404(db, invite_id)
    if invite.from_profile_id != payload.profile_id:
        raise HTTPException(status_code=403, detail="Это не твоё приглашение")
    if invite.status != "pending":
        raise HTTPException(status_code=409, detail="Приглашение уже закрыто")
    invite.status = "cancelled"
    invite.decided_at = datetime.utcnow()
    db.commit()
    return None
