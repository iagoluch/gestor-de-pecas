"""Erros HTTP padronizados e sem vazamento de detalhes internos."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.database.errors import DatabaseError
from backend.observability.capture import mark_error
from mes.contracts.reports import ReportError


class AppError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: Any = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _http_error_code(exc: HTTPException) -> str:
    """Código de negócio quando o ``detail`` já traz um, senão o genérico.

    Alguns endpoints recusam com ``detail={"error": {"code": ...}}``. Preservar
    esse código faz a recusa aparecer como bloqueio esperado no observatório em
    vez de virar um ``http_error`` anônimo.
    """

    detail = exc.detail
    if isinstance(detail, dict):
        error = detail.get("error")
        if isinstance(error, dict) and str(error.get("code") or "").strip():
            return str(error["code"]).strip()
        if str(detail.get("code") or "").strip():
            return str(detail["code"]).strip()
    return "http_error"


def error_payload(request: Request, code: str, message: str, details=None) -> dict:
    payload = {
        "code": code,
        "message": message,
        "request_id": _request_id(request),
    }
    if details is not None:
        payload["details"] = details
    return payload


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        # Recusa decidida pelo domínio: o Dev Observatory a classifica como
        # bloqueio esperado, não como defeito.
        mark_error(request, code=exc.code, message=exc.message, exception=exc)
        return JSONResponse(
            status_code=exc.status_code,
            content=jsonable_encoder(
                error_payload(request, exc.code, exc.message, exc.details)
            ),
        )

    @app.exception_handler(ReportError)
    async def report_error_handler(request: Request, exc: ReportError):
        # A camada `mes` não conhece HTTP: ela sinaliza a recusa com o código e
        # o status já decididos pela regra. Aqui isso vira apenas transporte.
        mark_error(request, code=exc.code, message=exc.user_message, exception=exc)
        return JSONResponse(
            status_code=exc.status_code,
            content=jsonable_encoder(
                error_payload(request, exc.code, exc.user_message)
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        details = [
            {
                "location": [str(item) for item in error.get("loc", ())],
                "message": error.get("msg"),
                "type": error.get("type"),
            }
            for error in exc.errors()
        ]
        mark_error(
            request,
            code="validation_error",
            message="Os dados enviados são inválidos.",
            exception=exc,
        )
        return JSONResponse(
            status_code=422,
            content=error_payload(
                request,
                "validation_error",
                "Os dados enviados são inválidos.",
                details,
            ),
        )

    @app.exception_handler(DatabaseError)
    async def database_error_handler(request: Request, exc: DatabaseError):
        logging.warning("Falha controlada de banco no request %s: %s", _request_id(request), exc)
        mark_error(
            request,
            code="database_unavailable",
            message=str(exc),
            exception=exc,
        )
        return JSONResponse(
            status_code=503,
            content=error_payload(
                request,
                "database_unavailable",
                "O banco de dados está indisponível no momento.",
            ),
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException):
        message = exc.detail if isinstance(exc.detail, str) else "A requisição não pôde ser concluída."
        mark_error(request, code=_http_error_code(exc), message=message, exception=exc)
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(request, "http_error", message),
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception):
        logging.exception("Erro não tratado no request %s", _request_id(request))
        # Único ponto do sistema que significa "ninguém previu isto": é o que
        # o Dev Observatory classifica como REAL_ERROR, com stack trace.
        mark_error(
            request,
            code="internal_error",
            message=str(exc),
            unhandled=True,
            exception=exc,
        )
        return JSONResponse(
            status_code=500,
            content=error_payload(
                request,
                "internal_error",
                "Não foi possível concluir a operação.",
            ),
        )
