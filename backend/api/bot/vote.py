from fastapi import Depends, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session

import schemas, join_flow, notifier
from api.bot import router
from database import get_db
from helpers import _check_bot_secret, _find_profile_by_telegram, _get_request_or_404, _apply_vote


@router.post("/api/bot/vote", dependencies=[Depends(_check_bot_secret)])
def bot_vote(
    payload: schemas.BotVote,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Голос кнопкой в боте."""
    profile = _find_profile_by_telegram(db, payload.telegram_id, None)
    if not profile:
        raise HTTPException(status_code=404, detail="Анкета не найдена")

    req = _get_request_or_404(db, payload.request_id)
    if req.status != join_flow.PENDING:
        raise HTTPException(status_code=409, detail="Заявка уже закрыта")
    if profile.group_id != req.group_id:
        raise HTTPException(
            status_code=403, detail="Голосовать могут только те, кто в комнате"
        )

    status, msgs = _apply_vote(db, req, profile, payload.approve)
    background_tasks.add_task(notifier.deliver, msgs)
    db.refresh(req)
    return {
        "status": status,
        "votes_done": join_flow.votes_done(req),
        "votes_needed": join_flow.votes_needed(req),
        "who": req.profile.name,
    }
