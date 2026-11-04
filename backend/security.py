"""Request bounds before multipart parsing; no credentials or bodies are logged."""
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
import config


class RequestBounds:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = config.MAX_UPLOAD_BYTES + 128 * 1024 if scope["path"] == "/api/uploads/photo" else 64 * 1024
        headers = dict(scope.get("headers", []))
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            length = limit + 1
        if length < 0 or length > limit:
            return await JSONResponse({"detail": "Запрос слишком большой. Сократи текст или выбери фото поменьше."}, status_code=413)(scope, receive, send)
        size = 0

        async def bounded_receive():
            nonlocal size
            message = await receive()
            if message["type"] == "http.request":
                size += len(message.get("body", b""))
                if size > limit:
                    raise HTTPException(413, "Запрос слишком большой. Выбери файл поменьше.")
            return message

        async def safe_send(message):
            if message["type"] == "http.response.start":
                extra = [(b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer")]
                if scope["path"].startswith("/api/") and not scope["path"].startswith("/api/media/"):
                    extra.append((b"cache-control", b"no-store"))
                message["headers"] = [(k, v) for k, v in message.get("headers", []) if k.lower() not in {k for k, _ in extra}] + extra
            await send(message)

        await self.app(scope, bounded_receive, safe_send)
