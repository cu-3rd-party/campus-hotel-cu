"""Чтение и очистка прежних блоков комнат и их заявок."""

from datetime import datetime
from typing import List

from sqlalchemy.orm import Session

import models

PENDING = "pending"
CANCELLED = "cancelled"


def active_votes(req: models.BlockRequest) -> dict:
    """Голоса только от тех, кто сейчас живёт в позванной комнате."""
    member_ids = {m.id for m in req.to_group.members}
    return {v.member_id: v.approve for v in req.votes if v.member_id in member_ids}


def votes_needed(req: models.BlockRequest) -> int:
    return len(req.to_group.members)


def votes_done(req: models.BlockRequest) -> int:
    return len([a for a in active_votes(req).values() if a is True])


def dissolve(db: Session, block: models.Block) -> None:
    """Распускает блок: комнаты снова сами по себе.

    Блок из одной комнаты не имеет смысла — вторая половина всё равно пустая,
    поэтому выход одной комнаты распускает его целиком.
    """
    for group in list(block.groups):
        group.block_id = None
    db.flush()
    db.delete(block)


def cancel_for_group(db: Session, group: models.Group) -> List[models.BlockRequest]:
    """Закрывает висящие заявки комнаты — она выбыла или изменилась.

    Возвращает закрытые заявки: их участникам стоит сказать, что ждать нечего.
    """
    reqs = (
        db.query(models.BlockRequest)
        .filter(
            models.BlockRequest.status == PENDING,
            (models.BlockRequest.from_group_id == group.id)
            | (models.BlockRequest.to_group_id == group.id),
        )
        .all()
    )
    for req in reqs:
        req.status = CANCELLED
        req.decided_at = datetime.utcnow()
    return reqs
