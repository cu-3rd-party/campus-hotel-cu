from typing import Optional

from fastapi import Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

import schemas, models
from api.profiles import router
from database import get_db
from helpers import telegram_user


@router.get(
    "/api/profiles/{profile_id}",
    response_model=schemas.ProfileOut,
)
def get_profile(
    profile_id: int,
    db: Session = Depends(get_db),
    viewer: Optional[dict] = Depends(telegram_user),
):
    visible = models.Profile.review_sent_at.is_(None)
    if viewer is not None:
        visible = or_(visible, models.Profile.telegram_id == int(viewer["id"]))
    profile = db.query(models.Profile).filter(models.Profile.id == profile_id, visible).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Профиль не найден")
    return profile
