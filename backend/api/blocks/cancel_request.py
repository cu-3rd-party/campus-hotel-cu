from datetime import datetime
from typing import Optional

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

import schemas, models, block_flow
from api.blocks import router
from database import get_db
from helpers import current_profile, _assert_is_me, _get_block_request_or_404, _get_profile_or_404


@router.post("/api/blocks/requests/{request_id}/cancel", status_code=204)
def cancel_block_request(
    request_id: int,
    payload: schemas.BlockMembership,
    db: Session = Depends(get_db),
    actor: Optional[models.Profile] = Depends(current_profile),
):
    """Отозвать своё предложение о блоке. Может любой жилец звавшей комнаты."""
    _assert_is_me(actor, payload.profile_id)
    req = _get_block_request_or_404(db, request_id)
    profile = _get_profile_or_404(db, payload.profile_id)

    if profile.group_id != req.from_group_id:
        raise HTTPException(status_code=403, detail="Это не твоё предложение")
    if req.status != block_flow.PENDING:
        raise HTTPException(status_code=409, detail="Заявка на блок уже закрыта")

    req.status = block_flow.CANCELLED
    req.decided_at = datetime.utcnow()
    db.commit()
    return None
