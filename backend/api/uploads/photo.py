from fastapi import UploadFile, File, HTTPException, Depends
from starlette.concurrency import run_in_threadpool

import schemas, config, storage
from api.uploads import router
from helpers import telegram_user


@router.post("/api/uploads/photo", response_model=schemas.PhotoOut, status_code=201, dependencies=[Depends(telegram_user)])
async def upload_photo(file: UploadFile = File(...)):
    raw = await file.read(config.MAX_UPLOAD_BYTES + 1)
    if not raw:
        raise HTTPException(status_code=400, detail="Пустой файл")
    if len(raw) > config.MAX_UPLOAD_BYTES:
        limit_mb = config.MAX_UPLOAD_BYTES // (1024 * 1024)
        raise HTTPException(
            status_code=413, detail=f"Файл больше {limit_mb} МБ — выбери поменьше"
        )
    try:
        url = await run_in_threadpool(storage.save_image, raw)
    except storage.InvalidImage as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return schemas.PhotoOut(photo_url=url)
