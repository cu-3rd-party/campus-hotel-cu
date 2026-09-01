from typing import Optional

from fastapi import BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

import schemas, models, join_flow, notifier
from api.requests import router
from database import get_db
from helpers import current_profile, _assert_is_me, _get_request_or_404, _get_profile_or_404, _apply_vote, \
    _request_out


@router.post("/api/requests/{request_id}/vote", response_model=schemas.JoinRequestOut)
def vote_request(
    request_id: int,
    payload: schemas.JoinRequestVoteIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    actor: Optional[models.Profile] = Depends(current_profile),
):
    _assert_is_me(actor, payload.profile_id)
    req = _get_request_or_404(db, request_id)
    voter = _get_profile_or_404(db, payload.profile_id)

    if req.status != join_flow.PENDING:
        raise HTTPException(status_code=409, detail="Заявка уже закрыта")
    if voter.group_id != req.group_id:
        raise HTTPException(
            status_code=403, detail="Голосовать могут только те, кто в комнате"
        )

    _status, msgs = _apply_vote(db, req, voter, payload.approve)
    background_tasks.add_task(notifier.deliver, msgs)
    db.refresh(req)
    return _request_out(req)
