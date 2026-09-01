from fastapi import APIRouter

router = APIRouter()

from . import webapp, widget  # noqa: E402, F401


