from fastapi import Depends
from sqlalchemy.orm import Session

from backend import models, join_flow
from backend.api.bot import router
from backend.database import get_db
from backend.helpers import _check_bot_secret, _find_profile_by_telegram, _who


@router.get("/api/bot/pending", dependencies=[Depends(_check_bot_secret)])
def bot_pending(telegram_id: int, db: Session = Depends(get_db)):
    """Заявки, ждущие голоса этого человека."""
    profile = _find_profile_by_telegram(db, telegram_id, None)
    if not profile or not profile.group_id:
        return {"requests": []}
    reqs = (
        db.query(models.JoinRequest)
        .filter(
            models.JoinRequest.group_id == profile.group_id,
            models.JoinRequest.status == join_flow.PENDING,
        )
        .all()
    )
    voted = {
        v.request_id
        for v in db.query(models.JoinRequestVote).filter(
            models.JoinRequestVote.member_id == profile.id
        )
    }
    return {
        "requests": [
            {
                "id": r.id,
                "who": _who(r.profile),
                "telegram": r.profile.telegram,
                "capacity": r.group.capacity,
            }
            for r in reqs
            if r.id not in voted
        ]
    }
