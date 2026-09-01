from fastapi import Depends
from sqlalchemy.orm import Session

from backend import schemas
from backend.api.groups import router
from backend.database import get_db
from backend.helpers import telegram_user, _get_group_or_404


@router.get(
    "/api/groups/{group_id}",
    response_model=schemas.GroupOut,
    dependencies=[Depends(telegram_user)],
)
def get_group(group_id: int, db: Session = Depends(get_db)):
    return _get_group_or_404(db, group_id)
