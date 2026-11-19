import os
from api import router
from profile_review import enabled


@router.get("/api/health")
def health():
    return {
        "status": "ok",
        "commit": os.getenv("RELEASE_ID", "development"),
        "disk_profile_review_enabled": enabled(),
    }
