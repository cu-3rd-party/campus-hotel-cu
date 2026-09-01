from fastapi import APIRouter

router = APIRouter()

from . import (  # noqa: E402, F401
    delete_profile,
    download_export,
    profiles,
    send_export_to_telegram,
    stats,
)
