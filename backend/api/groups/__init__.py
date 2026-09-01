from fastapi import APIRouter

router = APIRouter()

from . import (  # noqa: E402, F401
    change_capacity,
    create,
    create_join_request,
    get,
    leave,
    list,
    list_requests,
)


