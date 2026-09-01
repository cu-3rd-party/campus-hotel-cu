from fastapi import APIRouter

router = APIRouter()

from . import (  # noqa: E402, F401
    create,
    delete,
    get,
    list,
    list_ideal,
    list_requests,
    resolve_my,
    update,
)


