from api import router


@router.get("/api/health")
def health():
    return {"status": "ok"}
