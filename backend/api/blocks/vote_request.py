from typing import Optional

from fastapi import Depends, HTTPException

import models
import schemas
from api.blocks import router
from helpers import _assert_is_me, current_profile


@router.post("/api/blocks/requests/{request_id}/vote", status_code=410)
def vote_block_request(
    request_id: int,
    payload: schemas.BlockRequestVoteIn,
    actor: Optional[models.Profile] = Depends(current_profile),
):
    _assert_is_me(actor, payload.profile_id)
    raise HTTPException(status_code=410, detail="Объединение комнат в блоки отключено")
