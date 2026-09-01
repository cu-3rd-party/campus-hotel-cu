from typing import List

from fastapi import Depends
from sqlalchemy.orm import Session

from backend import schemas, campuses, models
from backend.api.blocks import router
from backend.database import get_db
from backend.helpers import telegram_user, _get_group_or_404


@router.get(
    "/api/groups/{group_id}/block-candidates",
    response_model=List[schemas.BlockRoomOut],
    dependencies=[Depends(telegram_user)],
)
def list_block_candidates(group_id: int, db: Session = Depends(get_db)):
    """Комнаты, с которыми эта соберёт полный блок.

    Подбираем по размеру: комнате на 4 нужна комната на 2, комнате на 3 — на 3.
    Занятость людьми не важна — блок делят комнаты, а не отдельные жильцы.
    """
    group = _get_group_or_404(db, group_id)
    partner = campuses.block_partner(group.campus, group.capacity)
    if partner is None or group.block_id:
        return []

    return (
        db.query(models.Group)
        .filter(
            models.Group.id != group.id,
            models.Group.campus == group.campus,
            models.Group.gender == group.gender,
            models.Group.capacity == partner,
            models.Group.block_id.is_(None),
        )
        .order_by(models.Group.created_at.desc())
        .all()
    )
