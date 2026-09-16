"""Planejamento de quais fatos canônicos viram itens da outbox TOTVS.

Este módulo é a fronteira ENQUEUE. Ele recebe fatos canônicos já lidos dentro
da transação do operador e devolve ``OutboxEnqueueRequest`` — nunca envia nada,
nunca abre conexão e nunca conhece SOAP.

Somente contratos homologados na Etapa 5 são planejados:

* ``ProductionAppointment`` para parcial, finalização e marco terminal;
* ``ProductionAppointment`` de quantidade zero no início, apenas quando
  explicitamente habilitado por configuração;
* ``StopReport`` somente para intervalo fechado (parada anterior + retomada).

Retrabalho continua **bloqueado**: não existe destino comprovado no
MATA681/SH6, então o fato simplesmente não gera outbound.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import json
import os

from mes.integrations.totvs.errors import TotvsContractError
from mes.integrations.totvs.outbound_mapper import (
    build_production_appointment_xml,
    build_stop_report_xml,
    map_production_appointment,
    map_stop_report,
    map_terminal_production_appointment,
)
from mes.integrations.totvs.outbound_models import (
    CanonicalExecutionEvent,
    CanonicalTerminalMilestone,
)
from mes.integrations.totvs.outbox import OutboxEnqueueRequest, OutboxStatus


EVENT_PRODUCTION_APPOINTMENT = "production_appointment"
EVENT_PRODUCTION_APPOINTMENT_ZERO = "production_appointment_zero"
EVENT_PRODUCTION_APPOINTMENT_TERMINAL = "production_appointment_terminal"
EVENT_STOP_REPORT = "stop_report"

AGGREGATE_EXECUTION_EVENT = "execution_event"
AGGREGATE_PRODUCTION_ORDER = "production_order"

# Estados canônicos que carregam resultado produtivo apontável.
_QUANTITY_STATES = frozenset({"parcial", "finalizado"})
# Estados canônicos que podem iniciar a execução no recurso.
_START_STATES = frozenset({"producao", "setup"})

# Prefixo reservado pelo gerador de OPs da simulação industrial. A guarda é
# permanente: mesmo que uma execução ligue a outbox por engano, uma ordem SOAK
# nunca pode virar obrigação para o Protheus. Prefixos adicionais podem ser
# declarados na configuração para outros cenários sintéticos.
_RESERVED_SYNTHETIC_ORDER_PREFIXES = ("SOAK",)


@dataclass(frozen=True)
class OutboundEnqueueConfig:
    """Parâmetros TOTVS que o Gestor não pode inferir sozinho.

    ``WasteCode`` e ``StopReasonCode`` pertencem a cadastros do Protheus
    (Motivo Refugo e SX5 grupo 44). A Etapa 5 provou que o texto/motivo do
    Gestor **não** pode ser convertido implicitamente, então eles chegam por
    configuração de ambiente e nunca por semelhança de nome.
    """

    enabled: bool = False
    emit_zero_quantity_start: bool = False
    waste_codes: dict[str, str] = field(default_factory=dict)
    default_waste_code: str | None = None
    stop_reason_codes: dict[str, str] = field(default_factory=dict)
    default_stop_reason_code: str | None = None
    emit_terminal_milestone: bool = True
    additional_synthetic_order_prefixes: tuple[str, ...] = ()

    def resolve_waste_code(self, event: CanonicalExecutionEvent) -> str | None:
        for candidate in (
            event.scrap_reason,
            event.event_reason,
            event.resource_status_code,
        ):
            key = str(candidate or "").strip().upper()
            if key and key in self.waste_codes:
                return self.waste_codes[key]
        return str(self.default_waste_code or "").strip() or None

    def resolve_stop_reason_code(self, event: CanonicalExecutionEvent) -> str | None:
        for candidate in (
            event.previous_resource_status_code,
            event.previous_reason,
        ):
            key = str(candidate or "").strip().upper()
            if key and key in self.stop_reason_codes:
                return self.stop_reason_codes[key]
        return str(self.default_stop_reason_code or "").strip() or None


def _has_totvs_identity(fact) -> bool:
    """Uma OP sem identidade TOTVS não possui destino outbound.

    ``CompanyId``/``BranchId`` chegam no ``ProductionOrder``. Uma OP criada
    apenas no Gestor (semente local, simulação, importação histórica) nunca foi
    planejada pelo Protheus e não pode ser reportada de volta a ele. Ela não
    entra na fila nem como item bloqueado: não há mensagem a recuperar depois,
    e enfileirá-la só produziria ruído permanente de ERROR.
    """

    return bool(
        str(getattr(fact, "company_id", "") or "").strip()
        and str(getattr(fact, "branch_id", "") or "").strip()
    )


def _is_synthetic_order(fact, config: OutboundEnqueueConfig) -> bool:
    """Reconhece OPs que jamais podem sair pela integração corporativa.

    A simulação exercita o pipeline inbound canônico e, por isso, seus XMLs
    carregam ``CompanyId`` e ``BranchId``. Identidade preenchida prova que o
    contrato foi projetado, mas não prova que a OP existe no Protheus. O prefixo
    reservado é a fronteira explícita que separa essas ordens das OPs reais.
    """

    production_order = (
        str(getattr(fact, "production_order", "") or "").strip().upper()
    )
    prefixes = (
        *_RESERVED_SYNTHETIC_ORDER_PREFIXES,
        *config.additional_synthetic_order_prefixes,
    )
    return bool(
        production_order
        and any(
            production_order.startswith(str(prefix or "").strip().upper())
            for prefix in prefixes
            if str(prefix or "").strip()
        )
    )


def _event_context(event: CanonicalExecutionEvent) -> dict:
    """Fotografia completa do fato, suficiente para remontar a mensagem depois.

    Um item bloqueado por falta de código TOTVS (refugo sem ``WasteCode``,
    parada sem ``StopReasonCode``) precisa guardar **os valores**, não só a
    notícia de que faltou configuração. Com este contexto, o refugo e a parada
    ficam registrados e auditáveis desde já e podem ser lançados no Protheus
    quando o cadastro correspondente for definido — sem depender do estado
    mutável do banco no momento do reprocessamento.
    """

    return {
        "canonical_event_id": event.event_id,
        "appointment_id": event.appointment_id,
        "state": event.state,
        "event_time": event.event_time.isoformat() if event.event_time else None,
        "execution_started_at": (
            event.execution_started_at.isoformat()
            if event.execution_started_at
            else None
        ),
        "production_order": event.production_order,
        "operation": event.operation,
        "activity_id": event.activity_id,
        "resource_code": event.resource_code,
        "item_code": event.item_code,
        "item_description": event.item_description,
        "warehouse_code": event.warehouse_code,
        "company_id": event.company_id,
        "branch_id": event.branch_id,
        "good_quantity": str(event.good_quantity),
        "scrap_quantity": str(event.scrap_quantity),
        "rework_quantity": str(event.rework_quantity),
        "planned_quantity": str(event.planned_quantity),
        "accumulated_good_quantity": str(event.accumulated_good_quantity),
        # Motivos do Gestor preservados como texto original. Eles não são
        # convertidos em código TOTVS por semelhança; ficam aqui para que a
        # Manufatura/PCP possa mapeá-los depois.
        "event_reason": event.event_reason,
        "scrap_reason": event.scrap_reason,
        "resource_status_code": event.resource_status_code,
        "operator_code": event.operator_code,
    }


def _milestone_context(milestone: CanonicalTerminalMilestone) -> dict:
    return {
        "production_order": milestone.production_order,
        "terminal_operation": milestone.terminal_operation,
        "terminal_resource_code": milestone.terminal_resource_code,
        "last_operation": milestone.last_operation,
        "last_operation_good_quantity": str(milestone.last_operation_good_quantity),
        "planned_quantity": str(milestone.planned_quantity),
        "pointable_operations": milestone.pointable_operations,
        "concluded_operations": milestone.concluded_operations,
        "execution_finished_at": (
            milestone.execution_finished_at.isoformat()
            if milestone.execution_finished_at
            else None
        ),
    }


def _blocked(
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    idempotency_key: str,
    transaction: str,
    production_order: str,
    operation_code: str | None,
    canonical_event_id: int | None,
    context: dict,
    error_code: str,
    error_message: str,
) -> OutboxEnqueueRequest:
    return OutboxEnqueueRequest(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        idempotency_key=idempotency_key,
        transaction=transaction,
        production_order=production_order,
        operation_code=operation_code,
        canonical_event_id=canonical_event_id,
        payload_xml=None,
        payload_context={
            **context,
            # O item bloqueado é a obrigação registrada, não um descarte. Ele
            # guarda os valores do fato e o que falta para transmiti-lo.
            "bloqueado": True,
            "bloqueio_codigo": error_code,
            "bloqueio_motivo": error_message,
        },
        status=OutboxStatus.ERROR,
        error_code=error_code,
        error_message=error_message,
    )


def _production_appointment_request(
    event: CanonicalExecutionEvent,
    *,
    event_type: str,
    waste_code: str | None,
    allow_zero_quantity: bool,
) -> OutboxEnqueueRequest:
    context = _event_context(event)
    context["waste_code"] = waste_code
    context["close_operation"] = (
        str(event.state or "").strip().casefold() == "finalizado"
    )
    # A chave determinística existe mesmo quando o contrato é recusado: o item
    # bloqueado ocupa a identidade lógica e impede duplicata no reprocessamento.
    fallback_key = f"gestor-pecas:blocked:{event_type}:{event.event_id}"
    try:
        contract = map_production_appointment(
            event,
            waste_code=waste_code,
            allow_zero_quantity=allow_zero_quantity,
        )
    except TotvsContractError as exc:
        return _blocked(
            event_type=event_type,
            aggregate_type=AGGREGATE_EXECUTION_EVENT,
            aggregate_id=str(event.event_id),
            idempotency_key=fallback_key,
            transaction="productionappointment",
            production_order=event.production_order,
            operation_code=event.operation,
            canonical_event_id=event.event_id,
            context=context,
            error_code=getattr(exc, "code", "invalid_totvs_contract"),
            error_message=str(exc),
        )
    message = build_production_appointment_xml(contract)
    return OutboxEnqueueRequest(
        event_type=event_type,
        aggregate_type=AGGREGATE_EXECUTION_EVENT,
        aggregate_id=str(event.event_id),
        idempotency_key=message.idempotency_key,
        transaction=message.transaction,
        production_order=event.production_order,
        operation_code=event.operation,
        canonical_event_id=event.event_id,
        payload_xml=message.xml,
        payload_context=context,
        status=OutboxStatus.PENDING,
    )


def _stop_report_request(
    event: CanonicalExecutionEvent,
    *,
    stop_reason_code: str | None,
) -> OutboxEnqueueRequest:
    context = _event_context(event)
    # Intervalo fechado da parada, do jeito que o StopReport exige: início do
    # evento anterior, fim na retomada. Preservado mesmo quando o código TOTVS
    # ainda não existe, para que a parada possa ser lançada depois.
    context["previous_state"] = event.previous_state
    context["stop_started_at"] = (
        event.previous_event_time.isoformat() if event.previous_event_time else None
    )
    context["stop_ended_at"] = event.event_time.isoformat() if event.event_time else None
    context["stop_reason_gestor"] = event.previous_reason
    context["stop_resource_status_code"] = event.previous_resource_status_code
    context["stop_interruption_planned"] = event.previous_interruption_planned
    context["stop_reason_code"] = stop_reason_code
    fallback_key = f"gestor-pecas:blocked:{EVENT_STOP_REPORT}:{event.event_id}"
    if not str(stop_reason_code or "").strip():
        return _blocked(
            event_type=EVENT_STOP_REPORT,
            aggregate_type=AGGREGATE_EXECUTION_EVENT,
            aggregate_id=str(event.event_id),
            idempotency_key=fallback_key,
            transaction="stopreport",
            production_order=event.production_order,
            operation_code=event.operation,
            canonical_event_id=event.event_id,
            context=context,
            error_code="stop_reason_code_nao_configurado",
            error_message=(
                "A parada exige um StopReasonCode do SX5 grupo 44 comprovado no "
                "TOTVS; o motivo do Gestor não é convertido implicitamente."
            ),
        )
    try:
        contract = map_stop_report(event, stop_reason_code=str(stop_reason_code))
    except TotvsContractError as exc:
        return _blocked(
            event_type=EVENT_STOP_REPORT,
            aggregate_type=AGGREGATE_EXECUTION_EVENT,
            aggregate_id=str(event.event_id),
            idempotency_key=fallback_key,
            transaction="stopreport",
            production_order=event.production_order,
            operation_code=event.operation,
            canonical_event_id=event.event_id,
            context=context,
            error_code=getattr(exc, "code", "invalid_totvs_contract"),
            error_message=str(exc),
        )
    message = build_stop_report_xml(contract)
    return OutboxEnqueueRequest(
        event_type=EVENT_STOP_REPORT,
        aggregate_type=AGGREGATE_EXECUTION_EVENT,
        aggregate_id=str(event.event_id),
        idempotency_key=message.idempotency_key,
        transaction=message.transaction,
        production_order=event.production_order,
        operation_code=event.operation,
        canonical_event_id=event.event_id,
        payload_xml=message.xml,
        payload_context=context,
        status=OutboxStatus.PENDING,
    )


def plan_execution_event(
    event: CanonicalExecutionEvent,
    *,
    config: OutboundEnqueueConfig,
) -> list[OutboxEnqueueRequest]:
    """Decide o que um único evento canônico deve enfileirar.

    Um mesmo evento pode gerar duas mensagens lógicas independentes — por
    exemplo uma retomada que também encerra a operação fecha a parada anterior
    (``StopReport``) e reporta a produção (``ProductionAppointment``). Cada uma
    possui sua própria chave determinística.
    """

    if (
        not config.enabled
        or not _has_totvs_identity(event)
        or _is_synthetic_order(event, config)
    ):
        return []
    requests: list[OutboxEnqueueRequest] = []
    state = str(event.state or "").strip().casefold()

    # StopReport exige início e fim: só a retomada/encerramento que sucede uma
    # parada fecha o intervalo. Parada ainda aberta nunca entra na fila.
    if str(event.previous_state or "").strip().casefold() == "parada":
        requests.append(
            _stop_report_request(
                event, stop_reason_code=config.resolve_stop_reason_code(event)
            )
        )

    rework = Decimal(str(event.rework_quantity or 0))
    good = Decimal(str(event.good_quantity or 0))
    scrap = Decimal(str(event.scrap_quantity or 0))

    if state in _QUANTITY_STATES:
        if rework > 0:
            # Retrabalho outbound continua bloqueado por decisão de contrato.
            # Nada é enviado e nada é reclassificado como boa ou refugo.
            return requests
        requests.append(
            _production_appointment_request(
                event,
                event_type=EVENT_PRODUCTION_APPOINTMENT,
                waste_code=config.resolve_waste_code(event) if scrap > 0 else None,
                allow_zero_quantity=False,
            )
        )
        return requests

    if (
        config.emit_zero_quantity_start
        and state in _START_STATES
        and str(event.previous_state or "").strip().casefold() == "fila"
        and good == 0
        and scrap == 0
        and rework == 0
    ):
        requests.append(
            _production_appointment_request(
                event,
                event_type=EVENT_PRODUCTION_APPOINTMENT_ZERO,
                waste_code=None,
                allow_zero_quantity=True,
            )
        )
    return requests


def plan_terminal_milestone(
    milestone: CanonicalTerminalMilestone,
    *,
    config: OutboundEnqueueConfig,
) -> list[OutboxEnqueueRequest]:
    """Planeja o marco terminal apenas quando a execução da OP terminou.

    Nenhuma regra do marco terminal muda aqui: a decisão continua sendo do
    ``map_terminal_production_appointment``, que recusa a emissão enquanto
    houver operação apontável em aberto. A única diferença da Etapa 6 é que o
    resultado vira item da outbox em vez de um POST síncrono.
    """

    if not config.enabled or not config.emit_terminal_milestone:
        return []
    if not _has_totvs_identity(milestone) or _is_synthetic_order(milestone, config):
        return []
    if not milestone.execution_completed:
        return []
    context = _milestone_context(milestone)
    fallback_key = (
        "gestor-pecas:blocked:"
        f"{EVENT_PRODUCTION_APPOINTMENT_TERMINAL}:{milestone.production_order}"
        f":{milestone.terminal_operation}"
    )
    try:
        contract = map_terminal_production_appointment(milestone)
    except TotvsContractError as exc:
        return [
            _blocked(
                event_type=EVENT_PRODUCTION_APPOINTMENT_TERMINAL,
                aggregate_type=AGGREGATE_PRODUCTION_ORDER,
                aggregate_id=milestone.production_order,
                idempotency_key=fallback_key,
                transaction="productionappointment",
                production_order=milestone.production_order,
                operation_code=milestone.terminal_operation,
                canonical_event_id=None,
                context=context,
                error_code=getattr(exc, "code", "invalid_totvs_contract"),
                error_message=str(exc),
            )
        ]
    message = build_production_appointment_xml(contract)
    return [
        OutboxEnqueueRequest(
            event_type=EVENT_PRODUCTION_APPOINTMENT_TERMINAL,
            aggregate_type=AGGREGATE_PRODUCTION_ORDER,
            aggregate_id=milestone.production_order,
            idempotency_key=message.idempotency_key,
            transaction=message.transaction,
            production_order=milestone.production_order,
            operation_code=milestone.terminal_operation,
            canonical_event_id=None,
            payload_xml=message.xml,
            payload_context=context,
            status=OutboxStatus.PENDING,
        )
    ]


def _flag(env, name: str, *, default: bool) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    return str(raw).strip().casefold() in {"1", "true", "yes", "sim", "on"}


def _code_map(env, name: str) -> dict[str, str]:
    raw = str(env.get(name) or "{}").strip() or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TotvsContractError(f"{name} deve ser um objeto JSON válido.") from exc
    if not isinstance(parsed, dict):
        raise TotvsContractError(f"{name} deve ser um objeto JSON.")
    resolved: dict[str, str] = {}
    for key, value in parsed.items():
        source = str(key).strip().upper()
        target = str(value).strip() if isinstance(value, str) else ""
        if not source or not target:
            raise TotvsContractError(
                f"{name} aceita somente chaves e códigos TOTVS de texto não vazios."
            )
        resolved[source] = target
    return resolved


def _prefixes(env, name: str) -> tuple[str, ...]:
    raw = str(env.get(name) or "").strip()
    if not raw:
        return ()
    return tuple(
        dict.fromkeys(
            prefix.strip().upper()
            for prefix in raw.replace(";", ",").split(",")
            if prefix.strip()
        )
    )


def load_outbound_enqueue_config(env=None) -> OutboundEnqueueConfig:
    """Carrega a configuração da outbox a partir do ambiente.

    Nenhum nome de banco entra nesta lógica: o mesmo código roda em TESTE e no
    piloto REAL, mudando apenas variáveis. A outbox nasce desabilitada, então
    habilitar o envio automático é sempre uma decisão explícita de ambiente.
    """

    environ = env if env is not None else os.environ
    return OutboundEnqueueConfig(
        enabled=_flag(environ, "GESTOR_TOTVS_OUTBOX_ENABLED", default=False),
        emit_zero_quantity_start=_flag(
            environ, "GESTOR_TOTVS_OUTBOX_ZERO_START_ENABLED", default=False
        ),
        emit_terminal_milestone=_flag(
            environ, "GESTOR_TOTVS_OUTBOX_TERMINAL_ENABLED", default=True
        ),
        waste_codes=_code_map(environ, "GESTOR_TOTVS_OUTBOUND_WASTE_CODE_MAP_JSON"),
        default_waste_code=str(
            environ.get("GESTOR_TOTVS_OUTBOUND_DEFAULT_WASTE_CODE") or ""
        ).strip()
        or None,
        stop_reason_codes=_code_map(
            environ, "GESTOR_TOTVS_OUTBOUND_STOP_REASON_MAP_JSON"
        ),
        default_stop_reason_code=str(
            environ.get("GESTOR_TOTVS_OUTBOUND_DEFAULT_STOP_REASON_CODE") or ""
        ).strip()
        or None,
        additional_synthetic_order_prefixes=_prefixes(
            environ, "GESTOR_TOTVS_OUTBOX_SYNTHETIC_OP_PREFIXES"
        ),
    )


__all__ = [
    "AGGREGATE_EXECUTION_EVENT",
    "AGGREGATE_PRODUCTION_ORDER",
    "EVENT_PRODUCTION_APPOINTMENT",
    "EVENT_PRODUCTION_APPOINTMENT_TERMINAL",
    "EVENT_PRODUCTION_APPOINTMENT_ZERO",
    "EVENT_STOP_REPORT",
    "OutboundEnqueueConfig",
    "load_outbound_enqueue_config",
    "plan_execution_event",
    "plan_terminal_milestone",
]
