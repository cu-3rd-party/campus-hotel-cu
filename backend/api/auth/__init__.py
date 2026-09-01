from fastapi import APIRouter

router = APIRouter()

from .telegram import router as telegram_router  # noqa: E402

router.include_router(telegram_router)
