"""Проверка анкет Диска по последней активности владельца."""

import asyncio
import logging
from datetime import datetime, timedelta
from secrets import token_urlsafe

from sqlalchemy import DateTime, bindparam, or_, text
from sqlalchemy.orm import Session

import campuses
import config
import notifier
from database import SessionLocal
from helpers import _close_pending, _msg, _remove_from_group
from models import Group, Profile

log = logging.getLogger(__name__)
INACTIVITY = timedelta(days=30)
RESPONSE_WINDOW = timedelta(days=2)
RETRY_INTERVAL = timedelta(days=7)
BATCH_SIZE = 20
POLL_INTERVAL = 15 * 60


def restore_legacy_activity(conn, initial_stamp: datetime) -> int:
    """Replace the rollout default with the last action attributable to the owner."""
    result = conn.execute(text("""
        WITH legacy AS (
            SELECT id, created_at
            FROM profiles
            WHERE campus = :campus AND last_activity_at = :initial_stamp
              AND created_at < :initial_stamp
        ), activity AS (
            SELECT id AS profile_id, created_at AS happened_at FROM legacy
            UNION ALL SELECT profile_id, created_at FROM join_requests
            UNION ALL SELECT member_id, created_at FROM join_request_votes
            UNION ALL SELECT from_profile_id, created_at FROM group_invites
            UNION ALL SELECT to_profile_id, decided_at FROM group_invites
                WHERE status IN ('accepted', 'declined')
            UNION ALL SELECT member_id, created_at FROM block_request_votes
        ), latest AS (
            SELECT legacy.id, MAX(activity.happened_at) AS happened_at
            FROM legacy JOIN activity ON activity.profile_id = legacy.id
            GROUP BY legacy.id
        )
        UPDATE profiles
        SET last_activity_at = latest.happened_at
        FROM latest
        WHERE profiles.id = latest.id AND profiles.last_activity_at = :initial_stamp
    """).bindparams(bindparam("initial_stamp", type_=DateTime())), {
        "campus": campuses.DISK, "initial_stamp": initial_stamp,
    })
    return result.rowcount


def migrate_legacy_activity(conn):
    # PostgreSQL stores the common timestamp assigned by the former ADD COLUMN
    # DEFAULT. Real activity replaced that exact value, so keep such rows intact.
    initial_stamp = conn.execute(text("""
        SELECT (CAST(CAST(attmissingval AS text) AS timestamp[]))[1]
        FROM pg_attribute
        WHERE attrelid = 'profiles'::regclass AND attname = 'last_activity_at'
          AND atthasmissing
    """)).scalar_one_or_none()
    if initial_stamp is not None:
        count = restore_legacy_activity(conn, initial_stamp)
        log.info("Восстановлена история активности анкет Диска: %s", count)
    else:
        log.info("Дата начала старого учёта активности не найдена в метаданных profiles")


def enabled() -> bool:
    return bool(config.DISK_PROFILE_REVIEW_ENABLED and config.TELEGRAM_BOT_TOKEN and config.BOT_SECRET)


def disk_profiles(db: Session):
    return db.query(Profile).filter(
        Profile.campus == campuses.DISK,
        Profile.telegram_verified.is_(True),
        Profile.telegram_id > 0,
    )


def clear_review(profile: Profile):
    profile.review_attempted_at = None
    profile.review_sent_at = None
    profile.review_token = None


def record_activity(profile: Profile, now: datetime):
    profile.last_activity_at = max(profile.last_activity_at, now)
    # An already delivered question still needs an explicit answer.
    if profile.review_sent_at is None:
        clear_review(profile)


def remove_profile(db: Session, profile: Profile):
    if profile.group_id is not None:
        # Two reviews can remove roommates simultaneously. Serialize the
        # membership changes so the last removal also deletes the empty room.
        db.query(Group.id).filter(Group.id == profile.group_id).with_for_update().first()
    messages = _remove_from_group(db, profile, note="больше не участвует в поиске соседей")
    _close_pending(db, profile)
    db.delete(profile)
    return messages


def claim_review(db: Session, now: datetime):
    profile = (
        disk_profiles(db)
        .filter(
            Profile.last_activity_at < now - INACTIVITY,
            Profile.review_sent_at.is_(None),
            or_(Profile.review_attempted_at.is_(None), Profile.review_attempted_at <= now - RETRY_INTERVAL),
        )
        .order_by(Profile.last_activity_at, Profile.id)
        .with_for_update(skip_locked=True)
        .first()
    )
    if profile is None:
        return None
    profile.review_attempted_at = now
    if profile.review_token is None:
        profile.review_token = token_urlsafe(18)
    return profile.id, profile.telegram_id, profile.review_token


def finish_delivery(db: Session, profile_id: int, token: str, status: str, now: datetime):
    profile = disk_profiles(db).filter(
        Profile.id == profile_id, Profile.review_token == token, Profile.review_sent_at.is_(None)
    ).with_for_update().first()
    if not profile:
        return []
    if status == "blocked":
        return remove_profile(db, profile)
    if status == "sent":
        profile.review_sent_at = now
    return []


def expire_review(db: Session, now: datetime):
    profile = (
        disk_profiles(db)
        .filter(Profile.review_sent_at <= now - RESPONSE_WINDOW)
        .order_by(Profile.review_sent_at, Profile.id)
        .with_for_update(skip_locked=True)
        .first()
    )
    if profile is None:
        return None
    messages = remove_profile(db, profile)
    messages.append(_msg(
        profile.telegram_id,
        "Анкета Диска удалена: мы не получили ответ за 48 часов. "
        "Если снова ищешь соседей, можешь создать новую анкету в приложении.",
    ))
    return messages


def _transaction(operation, *args):
    with SessionLocal.begin() as db:
        return operation(db, *args, datetime.utcnow())


async def run_pass():
    for _ in range(BATCH_SIZE):
        messages = await asyncio.to_thread(_transaction, expire_review)
        if messages is None:
            break
        await notifier.deliver(messages)
    for _ in range(BATCH_SIZE):
        review = await asyncio.to_thread(_transaction, claim_review)
        if review is None:
            break
        profile_id, telegram_id, token = review
        status, retry_after = await notifier.send_profile_review(telegram_id, token)
        if status == "sent" or status == "blocked":
            messages = await asyncio.to_thread(_transaction, finish_delivery, profile_id, token, status)
            await notifier.deliver(messages)
        if retry_after:
            return retry_after
    return 0


async def run():
    while True:
        retry_after = 0
        try:
            retry_after = await run_pass()
        except Exception:
            log.exception("Не удалось завершить проверку анкет Диска")
        await asyncio.sleep(max(POLL_INTERVAL, retry_after))
