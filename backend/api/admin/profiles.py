from typing import List, Optional

from fastapi import Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from starlette.responses import Response

from backend import schemas, campuses, models
from backend.api.admin import router
from backend.database import get_db
from backend.helpers import require_admin


@router.get(
    "/api/admin/profiles",
    response_model=List[schemas.AdminProfileOut],
    dependencies=[Depends(require_admin)],
)
def admin_profiles(
    response: Response,
    db: Session = Depends(get_db),
    search: Optional[str] = Query(None, description="Имя, ник или номер анкеты"),
    campus: Optional[str] = Query(None, pattern=campuses.PATTERN),
    gender: Optional[str] = Query(None, pattern="^(male|female|other)$"),
    limit: int = Query(50, ge=1, le=200),
):
    """Анкеты для модерации — самые свежие сверху.

    Лента админу не помощник: она разделена по полу и кампус-отелю и прячет
    тех, кто уже в комнате. Чистить же приходится любую анкету, поэтому здесь
    отдельный список — по всем сразу, с поиском.
    """
    response.headers["Cache-Control"] = "no-store"
    query = db.query(models.Profile)
    if campus:
        query = query.filter(models.Profile.campus == campus)
    if gender:
        query = query.filter(models.Profile.gender == gender)
    if search:
        needle = search.strip().lstrip("@")
        # «Петр» должен находить «Пётр»: букву ё в именах пишут по настроению,
        # а искать анкету админ будет по тому написанию, которое помнит.
        like = f"%{needle.lower().replace('ё', 'е')}%"

        def _no_yo(column):
            return func.replace(func.lower(column), "ё", "е")

        conditions = (
            _no_yo(models.Profile.name).like(like)
            | _no_yo(models.Profile.telegram).like(like)
            | _no_yo(models.Profile.bio).like(like)
        )
        # По номеру анкеты ищут, когда её прислали ссылкой из ленты.
        if needle.isdigit():
            conditions = conditions | (models.Profile.id == int(needle))
        query = query.filter(conditions)
    return query.order_by(models.Profile.created_at.desc()).limit(limit).all()
