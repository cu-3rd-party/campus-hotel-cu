from typing import List, Optional

from fastapi import Depends, Query
from sqlalchemy import and_, func, literal, or_
from sqlalchemy.orm import Session

import schemas, campuses, models
from api.profiles import router
from database import get_db
from helpers import telegram_user


@router.get(
    "/api/profiles",
    response_model=List[schemas.FeedProfileOut],
    response_model_exclude_unset=True,
    dependencies=[Depends(telegram_user)],
)
def list_profiles(
    db: Session = Depends(get_db),
    gender: Optional[str] = Query(None, pattern="^(male|female|other)$"),
    campus: Optional[str] = Query(None, pattern=campuses.PATTERN),
    room_capacity: Optional[int] = Query(None, ge=2, le=4),
    smoking: Optional[str] = Query(None, pattern=schemas.SMOKING_PATTERN),
    sleep_schedule: Optional[str] = Query(None, pattern="^(lark|owl|any)$"),
    track: Optional[str] = Query(None, pattern=schemas.TRACK_PATTERN),
    course: Optional[int] = Query(None, ge=1, le=4),
    tidiness: Optional[str] = Query(None, pattern=schemas.TIDINESS_PATTERN),
    wakeup: Optional[str] = Query(None, pattern=schemas.WAKEUP_PATTERN),
    cooking: Optional[str] = Query(None, pattern=schemas.COOKING_ITEM_PATTERN),
    guests: Optional[str] = Query(None, pattern=schemas.GUESTS_PATTERN),
    shower: Optional[str] = Query(None, pattern=schemas.SHOWER_PATTERN),
    temperature: Optional[str] = Query(None, pattern=schemas.TEMPERATURE_PATTERN),
    noise: Optional[str] = Query(None, pattern=schemas.NOISE_PATTERN),
    alcohol: Optional[str] = Query(None, pattern=schemas.ALCOHOL_PATTERN),
    snoring: Optional[str] = Query(None, pattern=schemas.SNORING_PATTERN),
    search: Optional[str] = Query(None),
    without_group: Optional[bool] = Query(
        None, description="true — только те, кто ещё не в комнате"
    ),
    recruiting: bool = Query(False, description="Люди без комнаты и участники комнат со свободными местами"),
):
    query = db.query(models.Profile).filter(models.Profile.review_sent_at.is_(None))
    room = models.Group
    if recruiting:
        occupancy = (
            db.query(models.Profile.group_id.label("room_id"), func.count().label("taken"))
            .filter(models.Profile.group_id.isnot(None))
            .group_by(models.Profile.group_id)
            .subquery()
        )
        spots_left = room.capacity - occupancy.c.taken
        query = (
            query.outerjoin(room, room.id == models.Profile.group_id)
            .outerjoin(occupancy, occupancy.c.room_id == room.id)
            .filter(or_(
                models.Profile.group_id.is_(None),
                and_(spots_left > 0, room.gender == models.Profile.gender, room.campus == models.Profile.campus),
            ))
            .add_columns(room.capacity, spots_left.label("spots_left"))
        )
    if gender:
        query = query.filter(models.Profile.gender == gender)
    if campus:
        query = query.filter(models.Profile.campus == campus)
    if without_group is True:
        query = query.filter(models.Profile.group_id.is_(None))
    elif without_group is False:
        query = query.filter(models.Profile.group_id.isnot(None))
    if room_capacity:
        # room_capacities — список через запятую ("3,4"). Обрамляем запятыми с
        # обеих сторон, чтобы искать число целиком. Пустой список — «не важно»,
        # подходит любой размер, поэтому такие анкеты показываем тоже.
        desired = (
            (literal(",") + models.Profile.room_capacities + ",").like(f"%,{room_capacity},%")
            | (models.Profile.room_capacities == "")
        )
        if recruiting:
            desired = or_(
                and_(models.Profile.group_id.is_(None), desired),
                room.capacity == room_capacity,
            )
        query = query.filter(desired)
    if smoking:
        query = query.filter(models.Profile.smoking == smoking)
    if sleep_schedule:
        query = query.filter(models.Profile.sleep_schedule == sleep_schedule)
    if track:
        query = query.filter(models.Profile.track == track)
    if course:
        query = query.filter(models.Profile.course == course)
    if tidiness:
        query = query.filter(models.Profile.tidiness == tidiness)
    if wakeup:
        query = query.filter(models.Profile.wakeup == wakeup)
    if guests:
        query = query.filter(models.Profile.guests == guests)
    if shower:
        query = query.filter(models.Profile.shower == shower)
    if temperature:
        query = query.filter(models.Profile.temperature == temperature)
    if noise:
        query = query.filter(models.Profile.noise == noise)
    if alcohol:
        query = query.filter(models.Profile.alcohol == alcohol)
    if snoring:
        query = query.filter(models.Profile.snoring == snoring)
    if cooking:
        # cooking хранится списком через запятую ("self,together"). Обрамляем
        # запятыми с обеих сторон, чтобы искать элемент целиком, а не подстроку.
        query = query.filter(
            func.concat(",", models.Profile.cooking, ",").like(f"%,{cooking},%")
        )
    if search:
        # Направление теперь выбирается фильтром, а не ищется текстом.
        like = f"%{search.lower()}%"
        query = query.filter(
            (models.Profile.name.ilike(like)) | (models.Profile.bio.ilike(like))
        )
    results = query.order_by(models.Profile.created_at.desc()).all()
    if not recruiting:
        return results
    return [
        schemas.FeedProfileOut.model_validate(profile).model_copy(update={
            "open_room": schemas.RecruitingRoomOut(capacity=capacity, spots_left=left)
        }) if profile.group_id is not None else profile
        for profile, capacity, left in results
    ]
