from fastapi import APIRouter

router = APIRouter()

from . import (  # noqa: E402, F401
    create,
    delete,
    list,
    list_ideal,
    list_requests,
    resolve_my,
    get,
    update,
)


