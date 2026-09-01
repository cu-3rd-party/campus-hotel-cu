from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

import schemas, models
from api.profiles import router
from database import get_db
from helpers import telegram_user


@router.get(
    "/api/profiles/{profile_id}",
    response_model=schemas.ProfileOut,
    dependencies=[Depends(telegram_user)],
)
def get_profile(profile_id: int, db: Session = Depends(get_db)):
    profile = db.query(models.Profile).filter(models.Profile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Профиль не найден")
    return profile
