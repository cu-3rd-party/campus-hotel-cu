from typing import Optional

from fastapi import Depends, Query
from sqlalchemy.orm import Session
from starlette.responses import Response

from backend import campuses
from backend.api.admin import router
from backend.database import get_db
from backend.helpers import require_admin, _build_export


@router.get("/api/admin/export", dependencies=[Depends(require_admin)])
async def download_export(  # имя не admin_export: так звался бы и модуль рядом
    db: Session = Depends(get_db),
    fmt: str = Query("xlsx", pattern="^(xlsx|csv|json)$", alias="format"),
    scope: str = Query("full", pattern="^(full|short)$"),
    campus: Optional[str] = Query(None, pattern=campuses.PATTERN),
):
    """Та же выгрузка, но скачиванием — удобно дёрнуть curl'ом с компьютера.

    В интерфейсе не используется: см. /api/admin/export/send.
    """
    body, filename, media = await _build_export(db, fmt, scope, campus)
    return Response(
        content=body,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
