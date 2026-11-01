"""HTTP hardening: request IDs, body-size limit, security headers and structured access logs.

Access logs carry the request ID, method, route template (never the raw path, which can hold
identifiers), status and latency. Bodies, query strings, headers and tokens are never logged.
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings

access_log = logging.getLogger("concepttrail.access")
app_log = logging.getLogger("concepttrail.app")

_API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": round(record.created, 3),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update(getattr(record, "fields", {}))
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(settings: Settings) -> None:
    root = logging.getLogger("concepttrail")
    if any(getattr(h, "_concepttrail", False) for h in root.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler._concepttrail = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(settings.log_level)
    root.propagate = False


def _route_template(scope: Scope) -> str:
    route = scope.get("route")
    return getattr(route, "path", None) or "unmatched"


class RequestContextMiddleware:
    """Request ID, body-size limit, security headers and one access-log line per request."""

    def __init__(self, app: ASGIApp, *, max_body_bytes: int, hsts: bool) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        started = time.monotonic()
        status_holder = {"status": 500}
        path: str = scope.get("path", "")

        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_body_bytes:
            await self._reject_too_large(send, request_id)
            self._log(scope, 413, started, request_id)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    raise _BodyTooLarge
            return message

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = list(message.get("headers") or [])
                extra = {
                    b"x-request-id": request_id.encode(),
                    b"x-content-type-options": b"nosniff",
                    b"x-frame-options": b"DENY",
                    b"referrer-policy": b"no-referrer",
                    b"permissions-policy": b"camera=(), microphone=(), geolocation=()",
                    b"cross-origin-opener-policy": b"same-origin",
                }
                if path.startswith("/api/") or path in ("/health", "/ready"):
                    extra[b"cache-control"] = b"no-store"
                    extra[b"pragma"] = b"no-cache"
                    extra[b"content-security-policy"] = _API_CSP.encode()
                if self.hsts:
                    extra[b"strict-transport-security"] = b"max-age=63072000; includeSubDomains"
                present = {k.lower() for k, _ in headers}
                headers += [(k, v) for k, v in extra.items() if k not in present]
                message["headers"] = headers
            await send(message)

        started_response = False

        async def tracking_send(message: Message) -> None:
            nonlocal started_response
            if message["type"] == "http.response.start":
                started_response = True
            await send_with_headers(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            await self._reject_too_large(send, request_id)
            status_holder["status"] = 413
        except Exception as exc:  # noqa: BLE001
            # Handled here (not re-raised) so the server keeps the connection healthy. Only the
            # class name is logged: messages can carry SQL, paths or data; no traceback to clients.
            app_log.error(
                "unhandled_error",
                extra={"fields": {"request_id": request_id, "error_class": type(exc).__name__}},
            )
            status_holder["status"] = 500
            if not started_response:
                await self._send_json(
                    send, 500, request_id, "internal_error", "An unexpected error occurred."
                )
        finally:
            self._log(scope, status_holder["status"], started, request_id)

    async def _reject_too_large(self, send: Send, request_id: str) -> None:
        await self._send_json(
            send, 413, request_id, "request_too_large", "The request body is too large."
        )

    async def _send_json(
        self, send: Send, status: int, request_id: str, code: str, message: str
    ) -> None:
        body = json.dumps(
            {"error": {"code": code, "message": message, "request_id": request_id}}
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"x-request-id", request_id.encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    def _log(self, scope: Scope, status: int, started: float, request_id: str) -> None:
        access_log.info(
            "request",
            extra={
                "fields": {
                    "request_id": request_id,
                    "method": scope.get("method"),
                    "route": _route_template(scope),
                    "status": status,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                }
            },
        )


class _BodyTooLarge(Exception):
    pass
