from typing import List

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

import schemas, telegram_auth, storage
from api.telegram import router


@router.post("/api/telegram/photos", response_model=schemas.TelegramPhotosOut)
async def telegram_photos(payload: schemas.TelegramPhotosIn):
    """Аватарки из профиля Telegram — чтобы человек выбрал нужную.

    Раньше молча бралась первая, хотя у многих аватарок несколько.
    Отдаём порциями: total подскажет фронту, осталось ли что догружать.
    """
    try:
        user = telegram_auth.verify_webapp_init_data(payload.init_data)
    except telegram_auth.TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))

    blobs, total = await telegram_auth.fetch_profile_photos(
        int(user["id"]), limit=payload.limit, offset=payload.offset
    )

    # Пачку аватарок обрабатываем одним заходом в поток, а не по одной: так
    # событийный цикл переключается на другие запросы между картинками, а не
    # стоит всё время, пока перебираем список.
    def _save_all(items: List[bytes]) -> List[str]:
        saved: List[str] = []
        for item in items:
            try:
                saved.append(storage.save_image(item))
            except storage.InvalidImage:
                continue
        return saved

    urls = await run_in_threadpool(_save_all, blobs)
    return schemas.TelegramPhotosOut(photos=urls, total=total)
