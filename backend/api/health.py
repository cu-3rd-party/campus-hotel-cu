import os
from api import router


@router.get("/api/health")
def health():
    return {"status": "ok", "commit": os.getenv("RELEASE_ID", "development")}
