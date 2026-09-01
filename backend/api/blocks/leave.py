from typing import Optional, List

from fastapi import BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from backend import schemas, models, config, block_flow, notifier
from backend.api.blocks import router
from backend.database import get_db
from backend.helpers import current_profile, _assert_is_me, _get_profile_or_404, _group_msgs, _room_name


@router.post("/api/blocks/{block_id}/leave", status_code=204)
def leave_block(
    block_id: int,
    payload: schemas.BlockMembership,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    actor: Optional[models.Profile] = Depends(current_profile),
):
    """Выйти из блока своей комнатой.

    Блок из одной комнаты не существует, поэтому выход распускает его целиком:
    обе комнаты снова свободны и могут искать других соседей по блоку.
    """
    _assert_is_me(actor, payload.profile_id)
    block = db.query(models.Block).filter(models.Block.id == block_id).first()
    if not block:
        raise HTTPException(status_code=404, detail="Блок не найден")

    profile = _get_profile_or_404(db, payload.profile_id)
    group = profile.group if profile.group_id else None
    if group is None or group.block_id != block.id:
        raise HTTPException(status_code=403, detail="Твоя комната не в этом блоке")

    msgs: List[dict] = []
    for other in block.groups:
        if other.id != group.id:
            msgs += _group_msgs(
                other,
                f"🚪 <b>{_room_name(group)}</b> вышла из вашего блока.\n"
                f"Можно объединиться с другой комнатой: {config.SITE_URL}",
            )
    block_flow.dissolve(db, block)
    db.commit()

    background_tasks.add_task(notifier.deliver, msgs)
    return None
