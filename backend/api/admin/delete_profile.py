from fastapi import Depends, BackgroundTasks
from sqlalchemy.orm import Session

from backend import config, notifier
from backend.api.admin import router
from backend.database import get_db
from backend.helpers import require_admin, _get_profile_or_404, _remove_from_group, _close_pending, _msg


@router.delete(
    "/api/admin/profiles/{profile_id}",
    status_code=204,
    dependencies=[Depends(require_admin)],
)
def admin_delete_profile(
    profile_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Убрать лишнюю анкету. Модерация тут ровно такая: чистим мусор.

    Всё остальное — как при самостоятельном удалении: человек выходит из
    комнаты, его заявки и приглашения закрываются, соседи получают уведомление.
    Самому хозяину анкеты тоже пишем: иначе анкета просто исчезает, и он этого
    не поймёт.
    """
    profile = _get_profile_or_404(db, profile_id)

    # Сообщения собираем ДО удаления, пока объекты ещё в сессии.
    msgs = _remove_from_group(
        db, profile, note="анкету удалил администратор — сосед(ка) выбыл(а)"
    )
    _close_pending(db, profile)
    if profile.telegram_chat_id:
        msgs.append(
            _msg(
                profile.telegram_chat_id,
                "🗑 Твою анкету удалил администратор.\n"
                "Если это ошибка — напиши администратору. "
                f"Разместить анкету заново можно тут: {config.SITE_URL}",
            )
        )

    db.delete(profile)
    db.commit()

    background_tasks.add_task(notifier.deliver, msgs)
    return None
