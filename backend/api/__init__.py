from fastapi import APIRouter

from .profiles import router as profiles_router
from .uploads import router as uploads_router
from .auth import router as auth_router
from .bot import router as bot_router
from .blocks import router as blocks_router
from .groups import router as groups_router
from .invites import router as invites_router
from .requests import router as requests_router
from .admin import router as admin_router
from .telegram import router as telegram_router

router = APIRouter()
router.include_router(profiles_router)
router.include_router(uploads_router)
router.include_router(auth_router)
router.include_router(bot_router)
router.include_router(blocks_router)
router.include_router(groups_router)
router.include_router(invites_router)
router.include_router(requests_router)
router.include_router(admin_router)
router.include_router(telegram_router)

from . import health, config  # noqa: E402, F401


