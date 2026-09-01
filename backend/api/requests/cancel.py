from datetime import datetime
from typing import Optional

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

import schemas, models, join_flow
from api.requests import router
from database import get_db
from helpers import current_profile, _assert_is_me, _get_request_or_404


@router.post("/api/requests/{request_id}/cancel", status_code=204)
def cancel_request(
    request_id: int,
    payload: schemas.GroupMembership,
    db: Session = Depends(get_db),
    actor: Optional[models.Profile] = Depends(current_profile),
):
    _assert_is_me(actor, payload.profile_id)
    req = _get_request_or_404(db, request_id)
    if req.profile_id != payload.profile_id:
        raise HTTPException(status_code=403, detail="Это не твоя заявка")
    if req.status != join_flow.PENDING:
        raise HTTPException(status_code=409, detail="Заявка уже закрыта")
    req.status = join_flow.CANCELLED
    req.decided_at = datetime.utcnow()
    db.commit()
    return None
