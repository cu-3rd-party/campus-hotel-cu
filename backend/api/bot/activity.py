from datetime import datetime
from typing import Literal

from fastapi import BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import notifier
import profile_review
from api.bot import router
from database import get_db
from helpers import _check_bot_secret
from models import Profile


class BotActivity(BaseModel):
    telegram_id: int = Field(gt=0, le=2**52 - 1)
    blocked: bool = False


class ReviewAnswer(BaseModel):
    telegram_id: int = Field(gt=0, le=2**52 - 1)
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{24}$")
    answer: Literal["keep", "leaving", "done"]


@router.post("/api/bot/activity", status_code=204, dependencies=[Depends(_check_bot_secret)])
def bot_activity(payload: BotActivity, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    profile = profile_review.disk_profiles(db).filter(
        Profile.telegram_id == payload.telegram_id
    ).with_for_update().first()
    if profile is None:
        return
    if payload.blocked:
        if profile_review.enabled():
            messages = profile_review.remove_profile(db, profile)
            db.commit()
            background_tasks.add_task(notifier.deliver, messages)
        return
    profile_review.record_activity(profile, datetime.utcnow())
    db.commit()


@router.post("/api/bot/activity-review", dependencies=[Depends(_check_bot_secret)])
def answer_review(payload: ReviewAnswer, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    if not profile_review.enabled():
        raise HTTPException(status_code=503, detail="Проверка анкет приостановлена.")
    now = datetime.utcnow()
    profile = profile_review.disk_profiles(db).filter(
        Profile.telegram_id == payload.telegram_id,
        Profile.review_token == payload.token,
    ).with_for_update().first()
    if profile is None or (
        profile.review_sent_at is not None
        and profile.review_sent_at + profile_review.RESPONSE_WINDOW <= now
    ):
        raise HTTPException(status_code=410, detail="Этот вопрос уже не актуален.")
    if payload.answer == "keep":
        profile_review.record_activity(profile, now)
        profile_review.clear_review(profile)
        db.commit()
        return {"status": "kept"}
    messages = profile_review.remove_profile(db, profile)
    db.commit()
    background_tasks.add_task(notifier.deliver, messages)
    return {"status": "deleted"}
