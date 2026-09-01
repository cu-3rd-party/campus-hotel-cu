from typing import Optional

from fastapi import BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

import schemas, models, block_flow, notifier
from api.blocks import router
from database import get_db
from helpers import current_profile, _assert_is_me, _get_block_request_or_404, _get_profile_or_404, \
    _apply_block_vote, _block_request_out


@router.post(
    "/api/blocks/requests/{request_id}/vote",
    response_model=schemas.BlockRequestOut,
)
def vote_block_request(
    request_id: int,
    payload: schemas.BlockRequestVoteIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    actor: Optional[models.Profile] = Depends(current_profile),
):
    _assert_is_me(actor, payload.profile_id)
    req = _get_block_request_or_404(db, request_id)
    voter = _get_profile_or_404(db, payload.profile_id)

    if req.status != block_flow.PENDING:
        raise HTTPException(status_code=409, detail="Заявка на блок уже закрыта")
    if voter.group_id != req.to_group_id:
        raise HTTPException(
            status_code=403,
            detail="Решают только жильцы комнаты, которую позвали",
        )

    _status, msgs = _apply_block_vote(db, req, voter, payload.approve)
    background_tasks.add_task(notifier.deliver, msgs)
    db.refresh(req)
    return _block_request_out(req)
