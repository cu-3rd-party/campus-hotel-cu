from fastapi import Depends, HTTPException

from api.bot import router
from helpers import _check_bot_secret


@router.post("/api/bot/block", status_code=410, dependencies=[Depends(_check_bot_secret)])
def bot_block_vote():
    raise HTTPException(status_code=410, detail="Объединение комнат в блоки отключено")
