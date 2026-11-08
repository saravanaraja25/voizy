"""Request size limit and baseline security headers, as plain ASGI middleware."""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_BODY_BYTES = 1_048_576  # 1 MiB; agent configs and role edits are small

_SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"cache-control", b"no-store"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
]


class BodyTooLargeError(Exception):
    pass


class SecurityMiddleware:
    def __init__(self, app: ASGIApp, max_body_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        exceeded = False
        responded = False

        async def send_wrapped(message: Message) -> None:
            nonlocal responded
            if exceeded:
                # The app saw a truncated body and may answer 400 (or anything); we own the reply.
                if not responded:
                    responded = True
                    await self._reject(send_with_headers)
                return
            if message["type"] == "http.response.start":
                responded = True
            await send_with_headers(message)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                headers += [(k, v) for k, v in _SECURITY_HEADERS if k not in present]
                message = {**message, "headers": headers}
            await send(message)

        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None:
            try:
                too_big = int(declared) > self.max_body_bytes
            except ValueError:
                too_big = True
            if too_big:
                await self._reject(send_with_headers)
                return

        received = 0

        async def receive_limited() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    exceeded = True
                    raise BodyTooLargeError
            return message

        try:
            await self.app(scope, receive_limited, send_wrapped)
        except BodyTooLargeError:
            pass
        if exceeded and not responded:
            responded = True
            await self._reject(send_with_headers)

    @staticmethod
    async def _reject(send: Send) -> None:
        body = b'{"detail":"request body too large"}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
