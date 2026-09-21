from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class OperatorActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    action: Literal[
        "Início", "Parada", "Setup", "Retrabalho", "Retomar", "Retornar", "Finalizado"
    ]
    resource: str = Field(min_length=1, max_length=120)
    op: str | None = Field(default=None, min_length=1, max_length=80)
    operation_id: int | None = None
    operation_number: str | None = Field(default=None, max_length=40)
    stop_reason_code: str | None = Field(default=None, max_length=40)
    comment: str | None = Field(default=None, max_length=1000)
    good: int = Field(default=0, ge=0)
    scrap: int = Field(default=0, ge=0)
    rework: int = Field(default=0, ge=0)
    lot: str | None = Field(default=None, max_length=120)
    scrap_reason: str | None = Field(default=None, max_length=240)
    root_cause: str | None = Field(default=None, max_length=240)
    setup_type: str | None = Field(default=None, max_length=120)
    badges: list[str] = Field(default_factory=list, max_length=20)
    confirm_resource_divergence: bool = False
    confirm_previous_step: bool = False
    # Crachá do responsável que autoriza o refugo apontado. Mesmo cadastro do
    # responsável do retrabalho da primeira peça; não existe perfil novo.
    scrap_authorization_badge: str | None = Field(default=None, max_length=80)


class FirstPieceMeasure(BaseModel):
    """Medida de uma cota do checklist. O status é conta do backend."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    sequencia: int = Field(ge=1)
    medida: str = Field(min_length=1, max_length=60)
    # Só é lido quando o padrão cadastrado da cota não é numérico (templates
    # legados em texto livre); com faixa numérica a conformidade é calculada.
    status: Literal["CONFORME", "NAO_CONFORME"] | None = None


class FirstPieceRequest(BaseModel):
    """Ciclo da primeira peça, todo no próprio posto do operador (Wave 5).

    ``produzida`` declara que a peça saiu da máquina, ``inspecionar`` registra
    a decisão do operador e ``autorizar`` é o crachá do responsável liberando o
    bloqueio de retrabalho. Não existe login para o responsável.

    ``checklist`` é o portão Setup/Qualidade do botão Iniciar (Wave 6B): uma
    submissão com as medidas das cotas, da qual o backend deriva o resultado.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    action: Literal["produzida", "inspecionar", "autorizar", "checklist"]
    resource: str = Field(min_length=1, max_length=120)
    op: str = Field(min_length=1, max_length=80)
    operation_id: int | None = None
    operation_number: str | None = Field(default=None, max_length=40)
    result: Literal["CONFORME", "RETRABALHO", "REFUGO"] | None = None
    note: str | None = Field(default=None, max_length=500)
    badge: str | None = Field(default=None, max_length=80)
    measures: list[FirstPieceMeasure] = Field(default_factory=list, max_length=60)
    # Destino físico da peça reprovada. Ele não decide conformidade: só diz se a
    # peça fora da faixa vai para retrabalho (padrão) ou para refugo. Refugo
    # exige o crachá do responsável designado em `badge`.
    destination: Literal["RETRABALHO", "REFUGO"] | None = None


class CuttingActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    action: Literal["Início", "Parada", "Retomada", "Finalizado"]
    resource: str = Field(min_length=1, max_length=120)
    plan_hash: str | None = Field(default=None, max_length=256)
    appointment_id: int | None = None
    stop_reason_code: str | None = Field(default=None, max_length=40)
    comment: str | None = Field(default=None, max_length=1000)


class HighlightActionRequest(BaseModel):
    # Escopo do apontamento: nulo é a tarefa inteira, preenchido é uma
    # chapa já cortada — o fluxo oficial permite os dois.
    plan_hash: str | None = None
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # "Retomar" é a retomada física do posto após uma parada registrada sem
    # tarefa. A retomada do destaque de uma tarefa parada continua sendo
    # "Início" (``registrar_destacando`` aceita o estado ``parada``).
    action: Literal["Início", "Parada", "Retomar", "Fim"]
    task_code: str | None = Field(default=None, min_length=1, max_length=80)
    stop_reason_code: str | None = Field(default=None, max_length=40)
    comment: str | None = Field(default=None, max_length=1000)
    badge: str | None = Field(default=None, max_length=80)
