from typing import List, Optional

from fastapi import Depends, Query
from sqlalchemy.orm import Session

import schemas, models
from api.profiles import router
from database import get_db
from helpers import current_profile, _assert_is_me, _get_profile_or_404, _request_out


@router.get(
    "/api/profiles/{profile_id}/requests", response_model=List[schemas.JoinRequestOut]
)
def list_my_requests(
    profile_id: int,
    db: Session = Depends(get_db),
    status: Optional[str] = Query("pending"),
    actor: Optional[models.Profile] = Depends(current_profile),
):
    _assert_is_me(actor, profile_id)
    _get_profile_or_404(db, profile_id)
    query = db.query(models.JoinRequest).filter(
        models.JoinRequest.profile_id == profile_id
    )
    if status:
        query = query.filter(models.JoinRequest.status == status)
    return [_request_out(r) for r in query.all()]
