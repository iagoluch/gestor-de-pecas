"""Botão de chamada: disponível ao operador e à gestão, aviso só via Telegram.

Decisão do usuário (14/09/2026): a lista de contatos (nome + função) é gerida
numa tela própria dentro do sistema — nunca pelo Dev Observatory, que é
somente leitura de propósito. Motivo e comentário são sempre obrigatórios.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from backend.api.database import get_database
from backend.api.dependencies.auth import (
    get_current_user,
    require_admin_user,
    require_csrf,
    require_management_user,
)
from backend.api.errors import AppError
from backend.api.schemas.auth import SessionUser
from backend.api.schemas.common import ChamadaContatoRequest, ChamadaRequest
from app.core.operator_sectors import OPERATOR_SECTORS
from app.core.permissions import operator_sector_for_user_level
from mes.integrations.notifications.telegram import format_chamada_message
from mes.services.telegram_alerts import deliver_chamada, station_context


router = APIRouter(prefix="/chamadas", tags=["Chamadas"])

# Lista fechada e pequena: não precisa de tela de gestão própria. Se a lista
# de motivos mudar, ajusta-se aqui.
MOTIVOS = (
    "Manutenção",
    "Qualidade",
    "Falta de material",
    "Ferramental",
    "Outro",
)


def _contexto_do_posto(user: SessionUser, database, recurso) -> dict:
    """Máquina e OP em andamento de onde a chamada partiu.

    Só o posto tem essa identidade: a chamada da gestão não parte de máquina
    alguma. O recurso informado é confrontado com o setor do login antes de
    virar contexto — a máquina que aparece no aviso é sempre uma do posto.
    """

    recurso = str(recurso or "").strip()
    if not recurso or not user.operator_access:
        return {}
    setor = operator_sector_for_user_level(user.role)
    if setor is None or recurso not in setor.resources:
        return {}
    return station_context(database, setor=setor.name, recurso=recurso)


@router.get("/motivos")
def listar_motivos(_user: SessionUser = Depends(get_current_user)):
    return {"items": list(MOTIVOS)}


@router.get("/contato-padrao-gestao")
def contato_padrao_gestao(
    _user: SessionUser = Depends(get_current_user),
    database=Depends(get_database),
):
    """Quem o botão de chamada da tela de gestão pré-seleciona."""

    return {"item": database.buscar_contato_padrao_gestao()}


@router.get("/contatos")
def buscar_contatos(
    q: str | None = None,
    setor: str | None = None,
    _user: SessionUser = Depends(get_current_user),
    database=Depends(get_database),
):
    """Dropdown com busca, usado tanto pelo operador quanto pela gestão.

    ``setor`` restringe aos contatos configurados para o setor do posto que
    está chamando; contato sem setor configurado aparece em qualquer setor.
    """

    items = database.listar_chamada_contatos(somente_ativos=True, busca=q, setor=setor)
    return {"items": items, "count": len(items)}


@router.get("/setores")
def listar_setores(_user: SessionUser = Depends(get_current_user)):
    """Setores disponíveis para configurar por contato, na tela de chamada."""

    nomes = sorted({sector.name for sector in OPERATOR_SECTORS})
    return {"items": nomes}


@router.post("", dependencies=[Depends(require_csrf)])
def criar_chamada(
    payload: ChamadaRequest,
    request: Request,
    background: BackgroundTasks,
    user: SessionUser = Depends(get_current_user),
    database=Depends(get_database),
):
    if payload.motivo not in MOTIVOS:
        raise AppError(
            "chamada_motivo_invalido",
            "Selecione um motivo da lista.",
            status_code=422,
        )

    # Login de posto do operador e conta gerencial podem ser compartilhados
    # entre várias pessoas; crachá (operador) e nome+e-mail (gestão) são quem
    # de fato identifica quem apertou o botão (decisão do usuário, 14/09/2026).
    solicitante_nome = user.name
    solicitante_cracha = None
    solicitante_email = None
    if user.management_access:
        nome_manual = str(payload.solicitante_nome_manual or "").strip()
        email = str(payload.solicitante_email or "").strip()
        if not nome_manual or not email:
            raise AppError(
                "chamada_identificacao_obrigatoria",
                "Informe seu nome e e-mail para registrar a chamada.",
                status_code=422,
            )
        solicitante_nome = nome_manual
        solicitante_email = email
    else:
        cracha = str(payload.solicitante_cracha or "").strip()
        if not cracha:
            raise AppError(
                "chamada_identificacao_obrigatoria",
                "Informe seu crachá para registrar a chamada.",
                status_code=422,
            )
        # O login do posto identifica a estação, não a pessoa. Resolva o
        # crachá no cadastro canônico antes de gravar ou enviar para que o
        # histórico e o Telegram não exibam apenas o código digitado.
        operadores = database.buscar_operadores_apontamento([cracha])
        operador = next(
            (
                item
                for item in operadores
                if str(item.get("cracha") or "").strip() == cracha
            ),
            None,
        )
        nome_canonico = str((operador or {}).get("nome") or "").strip()
        if not nome_canonico:
            raise AppError(
                "chamada_cracha_invalido",
                "Crachá não cadastrado ou inativo. Informe um crachá ativo.",
                status_code=422,
            )
        solicitante_nome = nome_canonico
        solicitante_cracha = cracha

    try:
        chamada = database.registrar_chamada(
            contato_id=payload.contato_id,
            motivo=payload.motivo,
            comentario=payload.comentario,
            solicitante_nome=solicitante_nome,
            solicitante_nivel=user.role,
            solicitante_cracha=solicitante_cracha,
            solicitante_email=solicitante_email,
        )
    except ValueError as exc:
        raise AppError("chamada_invalida", str(exc)) from exc

    # Sininho da tela de gestão: atualiza ao vivo, sem esperar recarregar a
    # página nem depender de polling.
    request.app.state.realtime.publish("chamadas")

    settings = request.app.state.settings
    bot_token = str(getattr(settings, "telegram_bot_token", "") or "").strip()
    # Contato com Telegram próprio recebe direto; sem isso, cai no chat geral
    # do ambiente (decisão do usuário, 15/09/2026).
    chat_id = str(chamada.get("contato_telegram_chat_id") or "").strip() or str(
        getattr(settings, "chamada_telegram_chat_id", "") or ""
    ).strip()
    if not bot_token or not chat_id:
        chamada = database.marcar_chamada_telegram(
            chamada["id"],
            enviado=False,
            erro="Telegram não configurado para o botão de chamada.",
        ) or chamada
        return {"ok": True, "item": chamada, "telegram_agendado": False}

    # A mensagem é montada agora, ainda dentro do request: máquina/OP/peça são
    # o retrato do posto no instante da chamada, não o de quando a tarefa rodar.
    # O envio em si sai depois da resposta — o operador não espera o Telegram.
    mensagem = format_chamada_message(
        {**_contexto_do_posto(user, database, payload.recurso), **chamada}
    )
    background.add_task(
        deliver_chamada,
        database,
        chamada["id"],
        bot_token=bot_token,
        chat_id=chat_id,
        texto=mensagem,
    )
    return {"ok": True, "item": chamada, "telegram_agendado": True}


# ---------------------------------------------------------------------------
# Cadastro dos contatos — exclusivo da conta admin (decisão do usuário,
# 14/09/2026: a gestão comum pode chamar e ver o histórico, mas não decide
# quem entra na lista de contatos). Nunca pelo Dev Observatory, que é
# somente leitura de propósito.
# ---------------------------------------------------------------------------
@router.get("/admin/contatos")
def listar_contatos_admin(
    _user: SessionUser = Depends(require_admin_user),
    database=Depends(get_database),
):
    items = database.listar_chamada_contatos(somente_ativos=False, completo=True)
    return {"items": items, "count": len(items)}


@router.post("/admin/contatos", dependencies=[Depends(require_csrf)])
def salvar_contato(
    payload: ChamadaContatoRequest,
    _user: SessionUser = Depends(require_admin_user),
    database=Depends(get_database),
):
    try:
        item = database.salvar_chamada_contato(
            contato_id=payload.id,
            nome=payload.nome,
            funcao=payload.funcao,
            ativo=payload.ativo,
            padrao_gestao=payload.padrao_gestao,
            telegram_chat_id=payload.telegram_chat_id,
            setores=payload.setores,
        )
    except ValueError as exc:
        raise AppError("contato_invalido", str(exc)) from exc
    return {"ok": True, "item": item}


@router.delete("/admin/contatos/{contato_id}", dependencies=[Depends(require_csrf)])
def remover_contato(
    contato_id: int,
    _user: SessionUser = Depends(require_admin_user),
    database=Depends(get_database),
):
    if not database.remover_chamada_contato(contato_id):
        raise AppError("contato_nao_encontrado", "Contato não encontrado.", status_code=404)
    return {"ok": True}


@router.get("/nao-vistas")
def chamadas_nao_vistas(
    user: SessionUser = Depends(require_management_user),
    database=Depends(get_database),
):
    """Sininho pessoal: quantas chamadas existem desde a última vez que esta conta viu."""

    return {"count": database.contar_chamadas_nao_vistas(user.id)}


@router.post("/marcar-vistas", dependencies=[Depends(require_csrf)])
def marcar_chamadas_vistas(
    user: SessionUser = Depends(require_management_user),
    database=Depends(get_database),
):
    database.marcar_chamadas_vistas(user.id)
    return {"ok": True, "count": 0}


@router.get("/admin/historico")
def historico_chamadas(
    _user: SessionUser = Depends(require_management_user),
    database=Depends(get_database),
):
    items = database.listar_chamadas(limite=200)
    return {"items": items, "count": len(items)}
