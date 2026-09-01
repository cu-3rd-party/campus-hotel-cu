from fastapi import Depends, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session

import schemas, block_flow, notifier
from api.bot import router
from database import get_db
from helpers import _check_bot_secret, _find_profile_by_telegram, _get_block_request_or_404, _apply_block_vote, \
    _room_name


@router.post("/api/bot/block", dependencies=[Depends(_check_bot_secret)])
def bot_block_vote(
    payload: schemas.BotBlockVote,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Голос по предложению объединиться в блок — кнопкой в боте."""
    profile = _find_profile_by_telegram(db, payload.telegram_id, None)
    if not profile:
        raise HTTPException(status_code=404, detail="Анкета не найдена")

    req = _get_block_request_or_404(db, payload.request_id)
    if req.status != block_flow.PENDING:
        raise HTTPException(status_code=409, detail="Заявка на блок уже закрыта")
    if profile.group_id != req.to_group_id:
        raise HTTPException(
            status_code=403, detail="Решают только жильцы комнаты, которую позвали"
        )

    status, msgs = _apply_block_vote(db, req, profile, payload.approve)
    background_tasks.add_task(notifier.deliver, msgs)
    db.refresh(req)
    return {
        "status": status,
        "votes_done": block_flow.votes_done(req),
        "votes_needed": block_flow.votes_needed(req),
        "who": _room_name(req.from_group),
    }
