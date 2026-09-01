from typing import List, Optional

from fastapi import Depends, Query, HTTPException
from sqlalchemy.orm import Session

import schemas, models
from api.groups import router
from database import get_db
from helpers import current_profile, _get_group_or_404, _request_out


@router.get(
    "/api/groups/{group_id}/requests", response_model=List[schemas.JoinRequestOut]
)
def list_group_requests(
    group_id: int,
    db: Session = Depends(get_db),
    status: Optional[str] = Query("pending"),
    actor: Optional[models.Profile] = Depends(current_profile),
):
    group = _get_group_or_404(db, group_id)
    # Заявки — внутреннее дело комнаты: чужим их видеть незачем.
    if actor is not None and actor.group_id != group.id:
        raise HTTPException(status_code=403, detail="Это не твоя комната")
    reqs = [r for r in group.requests if not status or r.status == status]
    reqs.sort(key=lambda r: r.created_at)
    return [_request_out(r) for r in reqs]
