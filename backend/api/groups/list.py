from typing import List, Optional

from fastapi import Depends, Query
from sqlalchemy.orm import Session

import schemas, models, campuses
from api.groups import router
from database import get_db
from helpers import telegram_user


@router.get(
    "/api/groups",
    response_model=List[schemas.GroupOut],
    dependencies=[Depends(telegram_user)],
)
def list_groups(
    db: Session = Depends(get_db),
    gender: Optional[str] = Query(None, pattern="^(male|female|other)$"),
    campus: Optional[str] = Query(None, pattern=campuses.PATTERN),
    only_open: Optional[bool] = Query(None, description="true — только с местами"),
):
    query = db.query(models.Group)
    if gender:
        query = query.filter(models.Group.gender == gender)
    if campus:
        query = query.filter(models.Group.campus == campus)
    groups = query.order_by(models.Group.created_at.desc()).all()
    if only_open:
        groups = [g for g in groups if g.spots_left > 0]
    return groups
