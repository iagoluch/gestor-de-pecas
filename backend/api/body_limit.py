"""Teto de tamanho do corpo HTTP antes de qualquer parse (BK-10, API4:2023).

Os schemas Pydantic limitam campos, mas só depois de o corpo inteiro estar em
memória. Este middleware ASGI recusa com 413 pelo ``Content-Length`` sem ler
nada, e conta os bytes de verdade para quem mente ou manda chunked.
"""

from __future__ import annotations

from typing import Mapping

from fastapi import Request
from fastapi.responses import JSONResponse

from backend.api.errors import PayloadTooLarge, error_payload


DEFAULT_MAX_BODY_BYTES = 1024 * 1024


class BodySizeLimitMiddleware:
    def __init__(self, app, *, max_bytes: int, overrides: Mapping[str, int | None]):
        # ``overrides`` casa o caminho exato. ``None`` = rota com limite próprio
        # (o SOAP TOTVS lê o envelope com teto e responde com fault SOAP).
        self.app = app
        self.max_bytes = max_bytes
        self.overrides = dict(overrides)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.overrides.get(scope["path"], self.max_bytes)
        if limit is None:
            await self.app(scope, receive, send)
            return
        declared = dict(scope.get("headers") or ()).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > limit:
            request = Request(scope)
            response = JSONResponse(
                status_code=413,
                content=error_payload(request, PayloadTooLarge.code, PayloadTooLarge.message),
            )
            await response(scope, receive, send)
            return

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # HTTPException é a única exceção que o parse de corpo do
                    # FastAPI deixa passar intacta; o handler a vira em 413.
                    raise PayloadTooLarge()
            return message

        await self.app(scope, limited_receive, send)
