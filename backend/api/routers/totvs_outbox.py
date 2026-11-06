"""Fila de envios ao Protheus: ver o que travou, reenviar ou descartar (A58).

Só admin. Nenhuma rota altera fato produtivo: reenviar devolve o MESMO item à
fila; descartar marca DISCARDED com quem, quando e motivo, e libera os envios
seguintes da mesma OP. O histórico fica na tabela.
"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.api.database import get_database
from backend.api.dependencies.auth import require_admin_user, require_csrf
from backend.api.errors import AppError
from backend.api.schemas.auth import SessionUser
from mes.services.totvs_outbox_admin import TotvsOutboxAdminService


router = APIRouter(prefix="/admin/totvs-outbox", tags=["Envios ao Protheus"])

_CAMPOS = (
    "id", "event_type", "production_order", "operation_code", "status", "attempts",
    "created_at", "updated_at", "sent_at", "last_error_code", "last_error_message",
    "discarded_at", "discarded_by", "discard_reason",
)


class DiscardRequest(BaseModel):
    motivo: str = Field(min_length=3, max_length=500)


def _item(row):
    return {campo: row.get(campo) for campo in _CAMPOS}


_MENSAGENS = {
    "item_inexistente": "Envio não encontrado.",
    "motivo_obrigatorio": "Informe o motivo do descarte (mínimo 3 letras).",
    "item_nao_esta_em_erro": "Só um envio em ERRO pode ser reenviado ou descartado.",
    "item_mudou_de_estado": "O envio mudou de estado enquanto você agia; atualize a lista.",
}


def _resposta(result: dict):
    if result.get("ok"):
        return result
    code = str(result.get("code") or "outbox_action_failed")
    raise AppError(
        code,
        result.get("message") or _MENSAGENS.get(code, "Não foi possível concluir a ação."),
        status_code=404 if code == "item_inexistente" else 409,
    )


@router.get("")
def list_items(
    status: str | None = Query(default="ERROR", max_length=20),
    _user: SessionUser = Depends(require_admin_user),
    database=Depends(get_database),
):
    service = TotvsOutboxAdminService(database)
    rows = service.list_items(status=status or None, limit=200)
    return {"items": [_item(dict(row)) for row in rows or ()]}


@router.post("/{outbox_id}/reprocess", dependencies=[Depends(require_csrf)])
def reprocess(
    outbox_id: int,
    user: SessionUser = Depends(require_admin_user),
    database=Depends(get_database),
):
    result = TotvsOutboxAdminService(database).reprocess(outbox_id, operador=user.name)
    result.pop("item", None)
    return _resposta(result)


@router.post("/{outbox_id}/discard", dependencies=[Depends(require_csrf)])
def discard(
    outbox_id: int,
    payload: DiscardRequest,
    user: SessionUser = Depends(require_admin_user),
    database=Depends(get_database),
):
    return _resposta(
        TotvsOutboxAdminService(database).discard(outbox_id, motivo=payload.motivo, operador=user.name)
    )
