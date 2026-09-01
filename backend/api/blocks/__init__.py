from fastapi import APIRouter

router = APIRouter()

from . import (  # noqa: E402, F401
    cancel_request,
    create_request,
    leave,
    list,
    list_candidates,
    list_requests,
    vote_request,
)

