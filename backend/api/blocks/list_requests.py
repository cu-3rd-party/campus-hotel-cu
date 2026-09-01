from typing import List, Optional

from fastapi import Depends, Query, HTTPException
from sqlalchemy.orm import Session

import schemas, models
from api.blocks import router
from database import get_db
from helpers import current_profile, _get_group_or_404, _block_request_out


@router.get(
    "/api/groups/{group_id}/block-requests",
    response_model=List[schemas.BlockRequestOut],
)
def list_block_requests(
    group_id: int,
    db: Session = Depends(get_db),
    status: Optional[str] = Query("pending"),
    actor: Optional[models.Profile] = Depends(current_profile),
):
    """Заявки на блок этой комнаты — и входящие, и исходящие.

    Дело внутреннее: смотреть их могут только жильцы самой комнаты.
    """
    group = _get_group_or_404(db, group_id)
    if actor is not None and actor.group_id != group.id:
        raise HTTPException(status_code=403, detail="Это не твоя комната")

    query = db.query(models.BlockRequest).filter(
        (models.BlockRequest.from_group_id == group.id)
        | (models.BlockRequest.to_group_id == group.id)
    )
    if status:
        query = query.filter(models.BlockRequest.status == status)
    reqs = query.order_by(models.BlockRequest.created_at).all()
    return [_block_request_out(r) for r in reqs]
