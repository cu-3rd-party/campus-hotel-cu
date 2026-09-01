from typing import Optional

from fastapi import Depends
from starlette.responses import Response

from backend import schemas, config
from backend.api import router
from backend.helpers import optional_telegram_user, _is_admin


@router.get("/api/config", response_model=schemas.ConfigOut)
def get_config(
    response: Response, user: Optional[dict] = Depends(optional_telegram_user)
):
    """Фронтенд спрашивает, показывать ли кнопку входа через Telegram."""
    # Ответ зависит от подписи в заголовке, поэтому кэшировать его нельзя.
    # Иначе браузер или WebView Telegram переиспользует ответ, полученный по
    # другой подписи (или вовсе без неё) — и админ не увидит свою кнопку.
    # Vary тут не спасает: заголовок нестандартный, а промежуточные кэши
    # ключуются по URL.
    response.headers["Cache-Control"] = "no-store"
    return schemas.ConfigOut(
        telegram_enabled=config.telegram_enabled(),
        telegram_bot_username=config.TELEGRAM_BOT_USERNAME or None,
        max_upload_bytes=config.MAX_UPLOAD_BYTES,
        # Кнопку админки показываем только своим. Это лишь про интерфейс —
        # сами ручки проверяют подпись отдельно (см. require_admin).
        is_admin=_is_admin(user),
    )
