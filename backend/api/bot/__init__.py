from fastapi import APIRouter

router = APIRouter()

from . import activity, block_vote, invite_respond, link, pending, vote  # noqa: E402, F401
