from fastapi import APIRouter

router = APIRouter()

from . import photos  # noqa: E402, F401
