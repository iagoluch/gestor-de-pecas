from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, Path, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response, StreamingResponse

from backend.api.dependencies.ai import get_ai_service
from backend.api.dependencies.auth import require_csrf, require_management_user
from backend.api.errors import AppError
from backend.api.schemas.ai import AIConversationCreateRequest, AIMessageRequest
from backend.api.schemas.auth import SessionUser
from mes.contracts import AIRequestContext, AIServiceError, AIStreamEvent


router = APIRouter(prefix="/ai", tags=["IA Industrial"])


def _cooldown(request: Request):
    return request.app.state.ai_rate_limit


def _stream_error(exc: AIServiceError, request: Request) -> dict:
    if exc.code == "groq_rate_limited":
        cooldown = _cooldown(request).activate(exc.technical_details)
        return {
            "code": "rate_limit",
            "message": "Limite temporário da IA atingido.",
            "retryable": True,
            "retry_after_seconds": cooldown["retry_after_seconds"],
            "blocked_until": cooldown["blocked_until"],
        }
    if exc.code == "request_token_limit":
        return {
            "code": "request_token_limit",
            "message": "Esta consulta reuniu informações demais para serem analisadas de uma vez.",
            "retryable": False,
        }
    return {
        "code": exc.code,
        "message": exc.user_message,
        "retryable": exc.retryable,
        "request_id": getattr(request.state, "request_id", None),
    }


def _app_error(exc: AIServiceError, *, default_status: int = 400):
    status = 404 if exc.code == "ai_conversation_not_found" else default_status
    if exc.code in {"ai_disabled", "ai_not_configured", "ai_sdk_unavailable"}:
        status = 503
    return AppError(exc.code, exc.user_message, status_code=status)


def _sse(event: AIStreamEvent) -> str:
    data = json.dumps(jsonable_encoder(event.data), ensure_ascii=False, separators=(",", ":"))
    return f"event: {event.event}\ndata: {data}\n\n"


@router.get("/status")
def status(
    request: Request,
    _user: SessionUser = Depends(require_management_user),
    service=Depends(get_ai_service),
):
    result = service.status()
    result["cooldown"] = _cooldown(request).snapshot()
    return result


@router.get("/conversations")
def conversations(
    user: SessionUser = Depends(require_management_user),
    service=Depends(get_ai_service),
):
    return service.list_conversations(user.id)


@router.post("/conversations", status_code=201)
def create_conversation(
    payload: AIConversationCreateRequest,
    user: SessionUser = Depends(require_management_user),
    _csrf: None = Depends(require_csrf),
    service=Depends(get_ai_service),
):
    return service.create_conversation(user.id, payload.title)


@router.get("/conversations/{conversation_id}")
def conversation(
    conversation_id: int = Path(ge=1),
    user: SessionUser = Depends(require_management_user),
    service=Depends(get_ai_service),
):
    try:
        return service.get_conversation(conversation_id, user.id)
    except AIServiceError as exc:
        raise _app_error(exc) from exc


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: int = Path(ge=1),
    user: SessionUser = Depends(require_management_user),
    _csrf: None = Depends(require_csrf),
    service=Depends(get_ai_service),
):
    try:
        service.delete_conversation(conversation_id, user.id)
    except AIServiceError as exc:
        raise _app_error(exc) from exc
    return Response(status_code=204)


@router.post("/conversations/{conversation_id}/messages")
async def message(
    request: Request,
    payload: AIMessageRequest,
    conversation_id: int = Path(ge=1),
    user: SessionUser = Depends(require_management_user),
    _csrf: None = Depends(require_csrf),
    service=Depends(get_ai_service),
):
    current_status = service.status()
    if not current_status["enabled"]:
        raise AppError("ai_disabled", "A IA Industrial está desabilitada no servidor.", status_code=503)
    if not current_status["configured"]:
        raise AppError(
            "ai_not_configured",
            "IA não configurada. Defina a chave da Groq no servidor.",
            status_code=503,
        )
    cooldown = _cooldown(request).snapshot()
    if cooldown["active"]:
        raise AppError(
            "rate_limit",
            "Limite temporário da IA atingido.",
            status_code=429,
            details={
                "retryable": True,
                "retry_after_seconds": cooldown["retry_after_seconds"],
                "blocked_until": cooldown["blocked_until"],
            },
        )
    context = AIRequestContext(
        user_id=user.id,
        management_access=user.management_access,
        request_id=getattr(request.state, "request_id", None),
    )

    async def event_stream():
        try:
            async for event in service.stream_message(
                conversation_id,
                payload.content,
                context,
                retry=payload.retry,
            ):
                yield _sse(event)
        except asyncio.CancelledError:
            raise
        except AIServiceError as exc:
            yield _sse(
                AIStreamEvent(
                    "error",
                    _stream_error(exc, request),
                )
            )
        except Exception:
            logging.exception("Falha não tratada na IA request_id=%s", context.request_id)
            yield _sse(
                AIStreamEvent(
                    "error",
                    {
                        "code": "ai_internal_error",
                        "message": "Não foi possível concluir a consulta da IA.",
                        "retryable": True,
                        "request_id": context.request_id,
                    },
                )
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )
