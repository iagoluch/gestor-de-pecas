from datetime import time
from typing import Any

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str | None = None
    details: Any = None


class PageMeta(BaseModel):
    page: int
    page_size: int
    total: int
    pages: int



class AutomaticPauseRequest(BaseModel):
    """Pausa automática de um setor, mantida pela tela dos gestores."""

    id: int | None = None
    tipo_setor: str = Field(min_length=1, max_length=60)
    nome: str = Field(min_length=1, max_length=60)
    hora_inicio: time
    hora_fim: time
    ativo: bool = True
    ordem: int = Field(default=1, ge=1, le=99)


class ShiftParameterRequest(BaseModel):
    """Turno automático (H1/expediente/H2...), mantido pela tela IagoDev.

    ``tipo='expediente'`` é a janela oficial (só uma por vez); ``hora_extra``
    são as janelas fora dela — antes (tipo H1, sem corte automático próprio:
    quem já está trabalhando é protegido pela execução ativa) ou encadeadas
    depois (tipo H2, H3...: cada uma ganha seu próprio corte automático de
    fim de turno).
    """

    id: int | None = None
    nome: str = Field(min_length=1, max_length=60)
    tipo: str = Field(pattern="^(expediente|hora_extra)$")
    hora_inicio: time
    hora_fim: time
    ativo: bool = True
    ordem: int = Field(default=1, ge=1, le=99)


class OperatorBadgeRequest(BaseModel):
    """Crachá do chão de fábrica, mantido pela tela dos gestores (Wave 5).

    ``autorizador_retrabalho`` designa quem pode atender o chamado de
    retrabalho da primeira peça. É a mesma tabela de crachás que já existe:
    nenhum login novo e nenhuma autenticação paralela são criados.
    """

    cracha: str = Field(min_length=1, max_length=40)
    nome: str = Field(min_length=1, max_length=120)
    ativo: bool = True
    autorizador_retrabalho: bool = False


class UserAccountRequest(BaseModel):
    """Cadastro de login (tela exclusiva do admin — 14/09/2026).

    ``senha`` é obrigatória ao criar (``id`` ausente) e opcional ao editar —
    enviar em branco preserva a senha atual.
    """

    id: int | None = None
    nome: str = Field(min_length=1, max_length=120)
    nivel: str = Field(min_length=1, max_length=40)
    ativo: bool = True
    senha: str | None = Field(default=None, min_length=6, max_length=256)


class ChamadaContatoRequest(BaseModel):
    """Pessoa que pode ser chamada, mantida pela gestão numa tela própria."""

    id: int | None = None
    nome: str = Field(min_length=1, max_length=120)
    funcao: str = Field(min_length=1, max_length=80)
    ativo: bool = True
    padrao_gestao: bool = False
    telegram_chat_id: str | None = Field(default=None, max_length=64)
    # Setores em que este contato aparece no dropdown de chamada do operador.
    # Vazio = aparece em todos os setores (comportamento anterior, sem
    # configuração por setor).
    setores: list[str] = Field(default_factory=list)


class ChamadaRequest(BaseModel):
    """Chamada disparada pelo operador ou pela gestão.

    Motivo e comentário são obrigatórios por decisão do usuário (14/09/2026) —
    quem atende precisa saber o porquê sem ter que perguntar de volta.
    ``solicitante_cracha``/``solicitante_nome_manual``/``solicitante_email``
    identificam quem chamou de fato quando o login é compartilhado (posto do
    operador, conta genérica da gestão); a obrigatoriedade por perfil é
    validada no endpoint, que conhece o papel de quem está logado.
    """

    contato_id: int
    motivo: str = Field(min_length=1, max_length=60)
    comentario: str = Field(min_length=1, max_length=500)
    solicitante_cracha: str | None = Field(default=None, max_length=40)
    solicitante_nome_manual: str | None = Field(default=None, max_length=120)
    solicitante_email: str | None = Field(default=None, max_length=160)
