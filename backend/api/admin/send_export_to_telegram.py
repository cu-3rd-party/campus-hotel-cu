from typing import Optional

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

import schemas, campuses, admin_export, notifier
from api.admin import router
from database import get_db
from helpers import require_admin, optional_telegram_user, _build_export


@router.post("/api/admin/export/send", dependencies=[Depends(require_admin)])
async def send_export_to_telegram(
    payload: schemas.AdminExportIn,
    user: Optional[dict] = Depends(optional_telegram_user),
    db: Session = Depends(get_db),
):
    """Присылает выгрузку файлом в личку боту.

    Так надёжнее, чем скачивание: внутри Telegram на macOS и iOS скачанный
    файл открыть нечем, а присланный ботом документ система показывает сама.
    """
    body, filename, _media = await _build_export(
        db, payload.format, payload.scope, payload.campus
    )

    # В личной переписке chat_id совпадает с id пользователя, а он у нас из
    # проверенной подписи — то есть файл уходит ровно тому, кто его запросил.
    # Своей анкеты у админа может и не быть, поэтому её мы не спрашиваем.
    if user is None:
        raise HTTPException(
            status_code=400,
            detail="Не могу определить, кому отправлять: открой приложение из Telegram",
        )

    where = campuses.label(payload.campus) if payload.campus else "оба отеля"
    what = "имена и ники" if payload.scope == admin_export.SHORT else "все параметры"
    try:
        await notifier.send_document(
            int(user["id"]),
            filename,
            body,
            caption=f"📊 Выгрузка · {what} · {where}",
        )
    except notifier.DocumentError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return {"sent": True, "filename": filename}
