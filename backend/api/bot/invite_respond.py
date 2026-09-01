from fastapi import Depends, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session

from backend import schemas, notifier
from backend.api.bot import router
from backend.database import get_db
from backend.helpers import _check_bot_secret, _find_profile_by_telegram, _get_invite_or_404, \
    _assert_invite_still_valid, _accept_invite, _decline_invite


@router.post("/api/bot/invite", dependencies=[Depends(_check_bot_secret)])
def bot_invite_respond(
    payload: schemas.BotInviteRespond,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Ответ на приглашение «давай жить вместе» кнопкой в боте."""
    profile = _find_profile_by_telegram(db, payload.telegram_id, None)
    if not profile:
        raise HTTPException(status_code=404, detail="Анкета не найдена")

    invite = _get_invite_or_404(db, payload.invite_id)
    if invite.status != "pending":
        raise HTTPException(status_code=409, detail="Приглашение уже закрыто")
    if invite.to_profile_id != profile.id:
        raise HTTPException(status_code=403, detail="Это приглашение не тебе")

    if payload.accept:
        _assert_invite_still_valid(invite)
        _group, msgs = _accept_invite(db, invite)
        result = "accepted"
    else:
        msgs = _decline_invite(db, invite)
        result = "declined"

    background_tasks.add_task(notifier.deliver, msgs)
    return {
        "status": result,
        "capacity": invite.capacity,
        "who": invite.from_profile.name,
    }
