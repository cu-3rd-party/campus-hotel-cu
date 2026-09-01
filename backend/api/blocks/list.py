from typing import List, Optional

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from backend import schemas, campuses, models
from backend.api.blocks import router
from backend.database import get_db
from backend.helpers import telegram_user


@router.get(
    "/api/blocks",
    response_model=List[schemas.BlockOut],
    dependencies=[Depends(telegram_user)],
)
def list_blocks(
    db: Session = Depends(get_db),
    gender: Optional[str] = Query(None, pattern="^(male|female|other)$"),
    campus: Optional[str] = Query(None, pattern=campuses.PATTERN),
):
    """Уже собранные блоки — посмотреть, кто с кем объединился."""
    query = db.query(models.Block)
    if gender:
        query = query.filter(models.Block.gender == gender)
    if campus:
        query = query.filter(models.Block.campus == campus)
    return query.order_by(models.Block.created_at.desc()).all()
