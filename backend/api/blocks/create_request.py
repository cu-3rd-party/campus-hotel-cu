from typing import Optional

from fastapi import BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

import schemas, models, block_flow, campuses, notifier
from api.blocks import router
from database import get_db
from helpers import current_profile, _my_group_or_403, _get_group_or_404, _group_msgs, _room_name, \
    _block_request_out


@router.post(
    "/api/blocks/requests",
    response_model=schemas.BlockRequestOut,
    status_code=201,
)
def create_block_request(
    payload: schemas.BlockRequestCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    actor: Optional[models.Profile] = Depends(current_profile),
):
    """Позвать другую комнату в блок. Блок появится только после согласия."""
    group = _my_group_or_403(db, payload.profile_id, actor)
    other = _get_group_or_404(db, payload.to_group_id)

    problem = block_flow.pair_problem(group, other)
    if problem:
        raise HTTPException(status_code=409, detail=problem)

    existing = (
        db.query(models.BlockRequest)
        .filter(
            models.BlockRequest.status == block_flow.PENDING,
            models.BlockRequest.from_group_id == group.id,
            models.BlockRequest.to_group_id == other.id,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Предложение уже отправлено")

    req = models.BlockRequest(from_group_id=group.id, to_group_id=other.id)
    db.add(req)
    db.commit()
    db.refresh(req)

    msgs = _group_msgs(
        other,
        f"🧩 <b>{_room_name(group)}</b> зовёт вас в блок — "
        f"{group.capacity}+{other.capacity}, всего {campuses.BLOCK_SIZE} человек.\n\n"
        f"Нужно согласие всех, кто живёт в вашей комнате "
        f"({block_flow.votes_needed(req)}).",
        # Кнопки под сообщением: голосовать можно, не открывая приложение.
    )
    for msg in msgs:
        msg["reply_markup"] = notifier.block_keyboard(req.id)

    background_tasks.add_task(notifier.deliver, msgs)
    return _block_request_out(req)
