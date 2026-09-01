from datetime import datetime
from typing import Optional, List

from fastapi import BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from backend import schemas, models, join_flow, config, notifier
from backend.api.groups import router
from backend.database import get_db
from backend.helpers import current_profile, _assert_is_me, _get_group_or_404, _get_profile_or_404, \
    _assert_capacity_allowed, _close_group_blocks, _msg, _h


@router.post("/api/groups/{group_id}/capacity", response_model=schemas.GroupOut)
def change_group_capacity(
    group_id: int,
    payload: schemas.GroupCapacityIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    actor: Optional[models.Profile] = Depends(current_profile),
):
    """Сузить или расширить уже созданную комнату.

    Собрались вчетвером, а набралось двое — не нужно распускать комнату и
    собирать заново: комнату на 4 можно сделать комнатой на 2. Меняет любой
    жилец, остальные узнают об этом из Telegram.
    """
    _assert_is_me(actor, payload.profile_id)
    group = _get_group_or_404(db, group_id)
    profile = _get_profile_or_404(db, payload.profile_id)

    if profile.group_id != group.id:
        raise HTTPException(
            status_code=403, detail="Размер комнаты меняют только те, кто в ней живёт"
        )
    # В блоке ровно 6 человек: изменить размер комнаты — значит сломать его.
    # Сами блок не распускаем: это решение соседей, а не побочный эффект.
    if group.block_id:
        raise HTTPException(
            status_code=409,
            detail=(
                "Комната в блоке — её размер зафиксирован. Сначала выйдите из блока"
            ),
        )
    _assert_capacity_allowed(group.campus, payload.capacity)

    taken = len(group.members)
    if payload.capacity < taken:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Вас уже {taken} — комната на {payload.capacity} не вместит. "
                "Сначала кто-то должен выйти"
            ),
        )
    if payload.capacity == group.capacity:
        return group

    was = group.capacity
    group.capacity = payload.capacity
    db.flush()
    db.refresh(group)

    # Комнату могли ужать «под ноль» — тогда ждущие заявки теряют смысл.
    rejected: List[models.JoinRequest] = []
    if group.spots_left <= 0:
        for req in list(group.requests):
            if req.status == join_flow.PENDING:
                req.status = join_flow.REJECTED
                req.decided_at = datetime.utcnow()
                rejected.append(req)

    # Комната другого размера в прежний блок уже не складывается — висящие
    # предложения объединиться пришлось бы всё равно отклонить при подсчёте.
    msgs: List[dict] = _close_group_blocks(
        db, group, note=f"комната стала на {payload.capacity}"
    )
    for member in group.members:
        if member.id != profile.id and member.telegram_chat_id:
            msgs.append(
                _msg(
                    member.telegram_chat_id,
                    f"🔁 <b>{_h(profile.name)}</b> изменил(а) размер вашей комнаты: "
                    f"была на {was}, стала на {payload.capacity}.\n"
                    f"{config.SITE_URL}",
                )
            )
    for req in rejected:
        if req.profile.telegram_chat_id:
            msgs.append(
                _msg(
                    req.profile.telegram_chat_id,
                    "😔 Комнату сделали меньше, и мест в ней не осталось — "
                    f"твоя заявка закрыта. Есть другие варианты: {config.SITE_URL}",
                )
            )

    db.commit()
    db.refresh(group)

    background_tasks.add_task(notifier.deliver, msgs)
    return group
