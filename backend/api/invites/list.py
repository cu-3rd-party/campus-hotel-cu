from typing import List, Optional

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from backend import schemas, models
from backend.api.invites import router
from backend.database import get_db
from backend.helpers import current_profile, _assert_is_me, _get_profile_or_404


@router.get(
    "/api/profiles/{profile_id}/invites", response_model=List[schemas.GroupInviteOut]
)
def list_my_invites(
    profile_id: int,
    db: Session = Depends(get_db),
    status: Optional[str] = Query("pending"),
    actor: Optional[models.Profile] = Depends(current_profile),
):
    """Приглашения, где человек участвует — и как звавший, и как позванный."""
    _assert_is_me(actor, profile_id)
    _get_profile_or_404(db, profile_id)
    query = db.query(models.GroupInvite).filter(
        (models.GroupInvite.from_profile_id == profile_id)
        | (models.GroupInvite.to_profile_id == profile_id)
    )
    if status:
        query = query.filter(models.GroupInvite.status == status)
    return query.order_by(models.GroupInvite.created_at.desc()).all()
