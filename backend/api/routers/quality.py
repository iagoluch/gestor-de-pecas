"""Casos de uso Web da Qualidade dentro da experiência normal do operador.

Não existe login, perfil nem aplicação de Qualidade. O acesso é derivado do
setor canônico já autenticado, e cada regra funcional é validada no serviço —
o React apenas apresenta e coleta.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse

from app.core.permissions import (
    can_manage_quality_template,
    quality_sector_for_user_level,
)
from backend.api.database import get_database
from backend.api.dependencies.auth import require_csrf, get_current_user
from backend.api.dependencies.clock import request_now_func
from backend.api.errors import AppError
from backend.api.schemas.auth import SessionUser
from backend.api.schemas.quality import (
    QualityDrawingRequest,
    QualityFinishRequest,
    QualityBypassRequest,
    QualityOpenRequest,
    QualityPieceRequest,
    QualityTemplateRequest,
)
from mes.services.quality import (
    QualityInspectionService,
    desenho_publico,
    template_publico,
)


router = APIRouter(prefix="/quality", tags=["Qualidade"])

PDF_MAGIC = b"%PDF-"
MAX_DRAWING_BYTES = 20 * 1024 * 1024
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def _sector(user: SessionUser):
    """Setor operacional habilitado para Qualidade, ou 403 explícito."""

    sector = quality_sector_for_user_level(user.role)
    if sector is None:
        raise AppError(
            "quality_sector_unavailable",
            "Seu setor não possui inspeção de qualidade habilitada.",
            status_code=403,
        )
    return sector


def _service(database, user: SessionUser, request: Request | None = None):
    return QualityInspectionService(
        database,
        user.name,
        now_func=request_now_func(request) if request is not None else None,
        usuario_id=user.id,
        nivel=user.role,
    )


def _result(result):
    if not result.ok:
        raise AppError(
            result.code or "quality_action_failed",
            result.message,
            status_code=409,
            details=result.data,
        )
    return {"ok": True, "message": result.message, "code": result.code, "data": result.data}


def _inspection(service, inspecao_id: int):
    data = service.obter_inspecao(inspecao_id)
    if data is None:
        raise AppError(
            "quality_inspection_not_found",
            "Inspeção não encontrada.",
            status_code=404,
        )
    return data


@router.get("/context")
def context(user: SessionUser = Depends(get_current_user)):
    """Diz à UI se a aba Qualidade existe para este usuário — e por quê."""

    sector = quality_sector_for_user_level(user.role)
    return {
        "available": sector is not None,
        "sector": sector.name if sector else None,
        "resources": list(sector.resources) if sector else [],
        "can_edit_template": can_manage_quality_template(user.role),
    }


@router.get("/queue")
def queue(
    request: Request,
    search: str | None = Query(default=None, max_length=120),
    resource: str | None = Query(default=None, max_length=120),
    user: SessionUser = Depends(get_current_user),
    database=Depends(get_database),
):
    sector = _sector(user)
    data = _service(database, user, request).listar_fila(
        sector.name, busca=search, recurso=resource
    )
    return {"sector": sector.name, **data}


@router.post("/inspections", dependencies=[Depends(require_csrf)])
def open_inspection(
    payload: QualityOpenRequest,
    request: Request,
    user: SessionUser = Depends(get_current_user),
    database=Depends(get_database),
):
    sector = _sector(user)
    service = _service(database, user, request)
    response = _result(service.abrir_inspecao(payload.op, sector.name))
    request.app.state.realtime.publish("quality_inspection_opened")
    return response


@router.post("/inspections/bypass", dependencies=[Depends(require_csrf)])
def bypass_inspection(
    payload: QualityBypassRequest,
    request: Request,
    user: SessionUser = Depends(get_current_user),
    database=Depends(get_database),
):
    """Registra que a inspeção foi **pulada**, com autor e crachá.

    Regra transitória: enquanto os operadores são treinados para inspecionar
    as próprias peças, a inspeção não bloqueia o fluxo. Nada de aprovação,
    cota ou RNC fictícios — o que fica gravado é a decisão, auditável.
    """

    sector = _sector(user)
    service = _service(database, user, request)
    response = _result(
        service.dispensar_inspecao(
            payload.op, sector.name, badges=payload.badges, motivo=payload.motivo
        )
    )
    request.app.state.realtime.publish("quality_inspection_bypassed")
    return response


@router.get("/inspections/{inspecao_id}")
def inspection(
    request: Request,
    inspecao_id: int,
    user: SessionUser = Depends(get_current_user),
    database=Depends(get_database),
):
    _sector(user)
    return _inspection(_service(database, user, request), inspecao_id)


@router.post("/inspections/{inspecao_id}/pieces", dependencies=[Depends(require_csrf)])
def register_piece(
    payload: QualityPieceRequest,
    request: Request,
    inspecao_id: int,
    user: SessionUser = Depends(get_current_user),
    database=Depends(get_database),
):
    _sector(user)
    service = _service(database, user, request)
    response = _result(
        service.registrar_peca(
            inspecao_id,
            numero_peca=payload.numero_peca,
            resultado=payload.resultado,
            medidas=[item.model_dump() for item in payload.medidas],
            rnc=payload.rnc.model_dump() if payload.rnc else None,
            badges=payload.badges,
        )
    )
    request.app.state.realtime.publish("quality_piece_registered")
    return response


@router.post("/inspections/{inspecao_id}/finish", dependencies=[Depends(require_csrf)])
def finish_inspection(
    payload: QualityFinishRequest,
    request: Request,
    inspecao_id: int,
    user: SessionUser = Depends(get_current_user),
    database=Depends(get_database),
):
    _sector(user)
    service = _service(database, user, request)
    response = _result(service.finalizar_inspecao(inspecao_id, badges=payload.badges))
    request.app.state.realtime.publish("quality_inspection_finished")
    return response


@router.get("/templates/{produto}")
def template(
    request: Request,
    produto: str,
    user: SessionUser = Depends(get_current_user),
    database=Depends(get_database),
):
    if quality_sector_for_user_level(user.role) is None and not can_manage_quality_template(
        user.role
    ):
        raise AppError(
            "quality_sector_unavailable",
            "Seu setor não possui inspeção de qualidade habilitada.",
            status_code=403,
        )
    template = database.buscar_template_qualidade(produto)
    return {
        "produto": produto,
        "template": template_publico(template),
        "can_edit": can_manage_quality_template(user.role) or template is None,
    }


@router.post("/templates", dependencies=[Depends(require_csrf)])
def save_template(
    payload: QualityTemplateRequest,
    request: Request,
    user: SessionUser = Depends(get_current_user),
    database=Depends(get_database),
):
    """Primeira definição é do operador; alteração posterior é de Supervisor/Líder."""

    if quality_sector_for_user_level(user.role) is None and not can_manage_quality_template(
        user.role
    ):
        raise AppError(
            "quality_sector_unavailable",
            "Seu setor não possui inspeção de qualidade habilitada.",
            status_code=403,
        )
    service = _service(database, user, request)
    response = _result(
        service.definir_template(
            payload.produto,
            [item.model_dump() for item in payload.cotas],
            pode_editar=can_manage_quality_template(user.role),
        )
    )
    request.app.state.realtime.publish("quality_template_saved")
    return response


@router.get("/history")
def history(
    request: Request,
    op: str | None = Query(default=None, max_length=60),
    product: str | None = Query(default=None, max_length=60),
    resource: str | None = Query(default=None, max_length=60),
    result: str | None = Query(default=None, max_length=20),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    user: SessionUser = Depends(get_current_user),
    database=Depends(get_database),
):
    sector = _sector(user)
    rows = _service(database, user, request).listar_historico(
        sector.name,
        op=op,
        produto=product,
        recurso=resource,
        resultado=result,
        inicio=start,
        fim=end,
        limite=page_size + 1,
        deslocamento=(page - 1) * page_size,
    )
    return {
        "sector": sector.name,
        "items": rows[:page_size],
        "page": page,
        "page_size": page_size,
        "has_more": len(rows) > page_size,
    }


@router.get("/history/pieces/{peca_id}")
def piece_detail(
    request: Request,
    peca_id: int,
    user: SessionUser = Depends(get_current_user),
    database=Depends(get_database),
):
    _sector(user)
    return {"peca_id": peca_id, "cotas": _service(database, user, request).detalhar_peca(peca_id)}


@router.get("/drawings/{produto}")
def drawing_metadata(
    produto: str,
    user: SessionUser = Depends(get_current_user),
    database=Depends(get_database),
):
    _sector(user)
    desenho = database.buscar_desenho_produto(produto)
    return {"produto": produto, "desenho": desenho_publico(desenho)}


@router.get("/drawings/{produto}/file")
def drawing_file(
    produto: str,
    user: SessionUser = Depends(get_current_user),
    database=Depends(get_database),
):
    """Serve o PDF mais recente para o visualizador embutido na própria tela."""

    _sector(user)
    desenho = database.buscar_desenho_produto(produto)
    if desenho is None:
        raise AppError(
            "quality_drawing_not_found",
            "Nenhum desenho/PDF disponível para este produto.",
            status_code=404,
        )
    path = Path(str(desenho.get("storage_path") or ""))
    if not path.is_file():
        logging.error("Desenho de qualidade ausente no armazenamento: %s", path)
        raise AppError(
            "quality_drawing_unavailable",
            "O arquivo do desenho não está disponível no servidor.",
            status_code=503,
        )
    return FileResponse(
        path,
        media_type="application/pdf",
        # inline: o quiosque precisa ler o desenho na própria página.
        headers={"Content-Disposition": f'inline; filename="{desenho["filename"]}"'},
    )


@router.post("/drawings", dependencies=[Depends(require_csrf)])
def upload_drawing(
    payload: QualityDrawingRequest,
    request: Request,
    user: SessionUser = Depends(get_current_user),
    database=Depends(get_database),
):
    """Publica uma nova versão do desenho do produto. Exclusivo de Supervisor/Líder."""

    if not can_manage_quality_template(user.role):
        raise AppError(
            "quality_drawing_forbidden",
            "Somente Supervisor ou Líder pode publicar o desenho do produto.",
            status_code=403,
        )
    try:
        conteudo = base64.b64decode(payload.conteudo_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AppError("quality_drawing_invalid", "Conteúdo do arquivo inválido.") from exc
    if not conteudo.startswith(PDF_MAGIC):
        raise AppError("quality_drawing_invalid", "O desenho precisa ser um arquivo PDF.")
    if len(conteudo) > MAX_DRAWING_BYTES:
        raise AppError(
            "quality_drawing_too_large",
            "O desenho excede o tamanho máximo permitido.",
            status_code=413,
        )
    directory = Path(request.app.state.settings.quality_drawing_dir)
    directory.mkdir(parents=True, exist_ok=True)
    seguro = _SAFE_FILENAME.sub("_", Path(payload.filename).name) or "desenho.pdf"
    if not seguro.lower().endswith(".pdf"):
        seguro = f"{seguro}.pdf"
    digest = hashlib.sha256(conteudo).hexdigest()[:16]
    destino = directory / f"{_SAFE_FILENAME.sub('_', payload.produto)}_{digest}.pdf"
    destino.write_bytes(conteudo)
    desenho = database.registrar_desenho_produto(
        produto_codigo=payload.produto,
        filename=seguro,
        storage_path=str(destino),
        content_type="application/pdf",
        size_bytes=len(conteudo),
        enviado_por=user.id,
        enviado_por_nome=user.name,
    )
    request.app.state.realtime.publish("quality_drawing_published")
    return {"ok": True, "desenho": desenho_publico(desenho)}
