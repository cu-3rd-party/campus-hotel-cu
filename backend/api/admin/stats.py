from fastapi import Depends
from sqlalchemy.orm import Session
from starlette.responses import Response

import schemas, models, campuses
from api.admin import router
from database import get_db
from helpers import require_admin


@router.get(
    "/api/admin/stats",
    response_model=schemas.AdminStatsOut,
    dependencies=[Depends(require_admin)],
)
def admin_stats(response: Response, db: Session = Depends(get_db)):
    """Сводка перед выгрузкой: сколько всего и сколько с кем можно связаться."""
    # Чужие персональные данные не должны осесть в кэше браузера.
    response.headers["Cache-Control"] = "no-store"
    profiles = db.query(models.Profile).all()
    groups = db.query(models.Group).all()

    by_campus: dict = {}
    for profile in profiles:
        label = campuses.label(profile.campus)
        by_campus[label] = by_campus.get(label, 0) + 1

    return schemas.AdminStatsOut(
        profiles=len(profiles),
        with_username=len([p for p in profiles if p.telegram]),
        with_bot=len([p for p in profiles if p.telegram_chat_id]),
        groups=len(groups),
        in_groups=len([p for p in profiles if p.group_id]),
        blocks=db.query(models.Block).count(),
        by_campus=by_campus,
    )
