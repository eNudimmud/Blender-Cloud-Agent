import hashlib
import hmac
import secrets
import time

from starlette.responses import JSONResponse

COOKIE = "bca_session"
MAX_BODY = 32768


def session_cookie(token):
    message = f"{int(time.time())}.{secrets.token_hex(16)}"
    return message + "." + hmac.new(token.encode(), message.encode(), hashlib.sha256).hexdigest()


def authenticated(request, token):
    bearer = request.headers.get("authorization", "")
    if bearer.startswith("Bearer "):
        return hmac.compare_digest(bearer[7:].encode(), token.encode())
    cookie = request.cookies.get(COOKIE, "")
    try:
        stamp, nonce, signature = cookie.split(".")
        age = time.time() - int(stamp)
        expected = hmac.new(token.encode(), f"{stamp}.{nonce}".encode(), hashlib.sha256).hexdigest()
        return 0 <= age < 43200 and hmac.compare_digest(signature, expected)
    except (ValueError, TypeError):
        return False


class BodyLimitMiddleware:
    """Count streamed bytes before FastAPI parses JSON, including chunked requests."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > MAX_BODY:
                return await JSONResponse({"detail": "Request body too large"}, 413)(scope, receive, send)
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
